# Architecture

A detailed walkthrough of how the Mini Server Dashboard is structured, how data flows through the system, and the rationale behind key design decisions.

---

## High-Level Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                   Docker Network  (bridge)                       │
│                                                                 │
│  ┌───────────────────────┐   /api/*   ┌─────────────────────┐  │
│  │      Frontend         │ ─────────▶ │       Backend       │  │
│  │   React 19 + Nginx    │            │  Spring Boot 4.0.5  │  │
│  │   Host port 5173:80   │            │   Host port 8080    │  │
│  └───────────────────────┘            │   JSch SSH Client   │  │
│                                       └──────────┬──────────┘  │
└──────────────────────────────────────────────────│─────────────┘
                                                   │ SSH (port 22 / Ngrok TCP)
                                                   ▼
                                        ┌──────────────────────┐
                                        │  Remote Linux Server │
                                        │  (any standard host) │
                                        └──────────────────────┘
```

---

## Component Breakdown

### 1. Frontend — React + Nginx

| Responsibility | Details |
| --- | --- |
| Render UI | Single-page application built with React 19 and Vite 8 |
| Serve static files | Nginx Alpine serves the `dist/` bundle |
| Proxy API calls | Nginx forwards all `/api/*` requests to the backend container named `backend:8080` |
| Parse raw data | All SSH output parsing happens in `parsers.js` (pure functions, no side effects) |
| Adaptive polling | Two separate `useEffect` loops with `setTimeout` chains and Visibility API integration |

**Why Nginx as the production server?**
Nginx acts as both the static file server and an API reverse proxy. This single-origin architecture eliminates all CORS friction in production — the browser only talks to port `5173`, and Nginx transparently forwards `/api/*` calls to the backend. The backend's `CorsConfig` is only exercised during local development (Vite dev server on `5173` ↔ Spring Boot on `8080`).

---

### 2. Backend — Spring Boot

The backend is intentionally a **thin tunnel**: it receives an HTTP `GET`, translates it into a shell command, executes it over an SSH channel, and returns the raw output wrapped in a JSON envelope. No parsing logic lives in Java.

#### Package Structure

```
com.miniserver.dashboard
├── DashboardApplication.java     ← Spring Boot entry point (@SpringBootApplication)
├── config/
│   └── CorsConfig.java           ← WebMvcConfigurer: whitelists localhost:5173 for dev
├── controller/
│   └── MetricsController.java    ← @RestController: maps HTTP routes to shell commands
└── service/
    └── SshService.java           ← Persistent JSch session + retry + lifecycle management
```

#### Why keep parsing in the frontend?

Moving all parsing to `parsers.js` means:

- The Java layer has zero awareness of output format changes — updating a parser never requires a backend rebuild.
- Each parser can be unit-tested in isolation with plain string fixtures.
- The backend JAR stays small and dependency-light.

---

### 3. SSH Layer — `SshService`

`SshService` maintains **one shared `JSch` session** for the entire Spring Boot process lifetime.

```
Application start
    │
    └──▶ getOrCreateSession()  [synchronized]
              │
              ├── Session exists & connected? ──▶ Return it
              │
              └── Create new session
                      │
                      ├── StrictHostKeyChecking = no  (Ngrok compatibility)
                      ├── ServerAliveInterval = 30 s  (keep tunnel alive)
                      └── connect(15 000 ms timeout)

For each HTTP request:
    executeCommand(cmd)
        │
        ├── Open ChannelExec on shared session
        ├── Read stdout via BufferedReader (UTF-8)
        ├── Capture stderr → SLF4J WARN  (not System.err)
        ├── On failure: disconnect session → retry (250 ms / 500 ms / 1 000 ms)
        └── @PreDestroy: disconnect on Spring shutdown
```

**Why a shared session instead of per-request sessions?**
Opening a new SSH session requires a TCP handshake + key exchange, which typically costs 200–800 ms. With a persistent session, each command only opens a lightweight `ChannelExec` on the existing connection, reducing per-request overhead to <10 ms of channel setup.

**Retry strategy:** Exponential backoff with three delays `[250, 500, 1000]` ms guards against transient Ngrok disruptions. Each retry attempt invalidates and recreates the session to handle cases where the session handle itself is stale.

---

### 4. Data Flow — End to End

```
Browser tab (visible)
    │
    ├── Every 10 s (adaptive → 20 s if SSH > 5 s)
    │       │
    │       └── Promise.all([9 axios GET calls])
    │               │
    │               └── Nginx /api/* proxy
    │                       │
    │                       └── Spring Boot MetricsController
    │                               │
    │                               └── SshService.executeCommand(shellCmd)
    │                                       │
    │                                       └── JSch ChannelExec → Remote Linux
    │                                               │
    │                                               └── stdout → JSON { "data": "..." }
    │
    └── Every 30 s (separate effect)
            │
            └── axios GET /api/metrics/processes  (heavier ps command, isolated)
```

**Visibility API optimisation:** When `document.visibilityState === 'hidden'` (tab in background), polling is suspended entirely — no SSH calls are made. Polling resumes immediately on `visibilitychange` to `visible`, firing a fetch before the next scheduled interval.

---

### 5. Docker Composition

```yaml
# Simplified topology
services:
  backend:                         # Spring Boot JAR on Alpine JRE 21
    healthcheck: /actuator/health  # 30 s interval, 90 s start period
    resource limits:
      CPU: 1.5 cores | RAM: 1 GB (reservation: 512 MB)

  frontend:                        # React build served by Nginx Alpine
    depends_on: backend (healthy)  # Never starts before backend is ready
    resource limits:
      CPU: 0.5 cores | RAM: 256 MB (reservation: 64 MB)

networks:
  dashboard-network: bridge        # Isolated bridge; containers resolve each other by name
```

Both Dockerfiles use **multi-stage builds** to separate build-time tooling (Maven / Node) from the minimal runtime image, keeping final image sizes small.

---

### 6. CI/CD — Self-Hosted Runner

```
Developer workstation
    │
    └── git push origin main
            │
            └── GitHub Actions trigger (deploy.yml)
                    │
                    └── Self-hosted runner (running on the production server)
                            │
                            ├── git reset --hard
                            ├── git pull origin main
                            └── docker compose up -d --build
                                    │
                                    └── Rolling rebuild — only changed layers/images rebuilt
```

**Why self-hosted?** The runner executes directly on the server, so no external SSH secrets are stored in GitHub. The `backend/.env` file — which holds SSH credentials — is never part of the repository and is already present on disk before the runner touches the project.

---

## Key Design Trade-offs

| Decision | Choice | Rationale |
| --- | --- | --- |
| Parsing location | Frontend (`parsers.js`) | Independently testable; no backend rebuild when output format changes |
| SSH session lifecycle | Persistent + shared | Eliminates per-request handshake overhead (~200–800 ms) |
| StrictHostKeyChecking | Disabled | Required for Ngrok tunnels (host key changes on every reconnect); **not for production** fixed IPs |
| Auth on API routes | None | Intended for private-network deployment behind a firewall |
| Polling strategy | `setTimeout` chains (not `setInterval`) | Allows dynamic interval adjustment and prevents overlapping concurrent fetches |
| Process poll cadence | 30 s (separate effect) | `ps` with full args is heavier; kept isolated to avoid slowing down lightweight metrics |
