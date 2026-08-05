# Architecture

A detailed walkthrough of how the Mini Server Dashboard is structured, how data flows through the system, and the rationale behind key design decisions.

---

## High-Level Overview

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               Docker Network (bridge)                                  │
│                                                                                        │
│  ┌──────────────────────┐  /api/auth/*   ┌──────────────────────┐                      │
│  │       Frontend       │───────────────▶│     Auth Service     │                      │
│  │   React 19 + Nginx   │                │  Spring Boot (8081)  │──┐                   │
│  │   Host port 5173:80  │                └──────────────────────┘  │                   │
│  └──────────┬───────────┘                                          │                   │
│             │ /api/metrics/*             ┌──────────────────────┐  │ PostgreSQL 17     │
│             ├───────────────────────────▶│   Metrics Service    │──┼─▶ ┌────────────┐  │
│             │                            │  Spring Boot (8082)  │  │   │     DB     │  │
│             │ /api/files/*               └──────────┬───────────┘  │   │Port 5432/tcp│  │
│             └───────────────────────────┐           │              │   └────────────┘  │
│                                         ▼           │              │                   │
│                              ┌──────────────────┐   │              │                   │
│                              │   File Service   │───┼──────────────┘                   │
│                              │Spring Boot (8083)│   │                                  │
│                              └──────────────────┘   │ SSH (22 LAN / 15774 Ngrok)       │
│                                                     ▼                                  │
│   ┌──────────────────────┐               ┌──────────────────────┐                      │
│   │     Telegram API     │◀──────────────│ Remote Linux Server  │                      │
│   │ (Long Polling Bot)   │               │ (sysadmin execution) │                      │
│   └──────────┬───────────┘               └──────────────────────┘                      │
│              │ (Tool Calling)                                                          │
│              ▼                                                                         │
│   ┌──────────────────────┐                                                             │
│   │       Groq AI        │                                                             │
│   │(llama-3.1-8b-instant)│                                                             │
│   └──────────────────────┘                                                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Microservices Topology

| Service | Port | Primary Responsibility | Key Technologies |
| --- | --- | --- | --- |
| **Frontend** | `5173` | React 19 SPA, Cyberpunk Sci-Fi UI, custom SVG icons (`SciFiIcons.jsx`), Nginx reverse proxy | React 19, Vite 8, Recharts, Nginx Alpine |
| **Metrics Service** | `8082` | System telemetry, JSch SSH persistent tunnel, `executeSudoCommand`, Telegram bot polling, Groq AI Agent | Spring Boot 4.1.0, JSch 2.28.5, Groq REST API |
| **Auth Service** | `8081` | Authentication, JWT token issuance, user credential validation | Spring Boot 4.1.0, Spring Data JPA, JJWT |
| **File Service** | `8083` | Remote file system browsing, file inspection & manipulation | Spring Boot 4.1.0, Spring Data JPA |
| **Database (DB)** | `5432` | Relational storage for users, tokens, and audit logs | PostgreSQL 17 Alpine |

---

### 2. Telegram Bot & Autonomous Groq AI Agent Architecture

The `metrics-service` integrates an autonomous AI assistant that monitors and executes administrative shell commands on the remote Linux server:

1. **Telegram Long Polling Engine:** `TelegramBotService` polls incoming Telegram messages asynchronously using a dedicated `SimpleClientHttpRequestFactory` with strict connect/read timeouts (5s / 12s) to prevent thread exhaustion.
2. **Dedicated Scheduling Thread Pool:** `SchedulingConfig` configures a 5-worker-thread `ThreadPoolTaskScheduler` so polling, metric updates, and notifications execute concurrently without blocking.
3. **Groq AI Tool Calling Agent (`AiChatService`):**
   - Model: `llama-3.1-8b-instant`.
   - Tool definition: `run_command` allows Groq to generate bash commands.
   - Context window limit: `MAX_HISTORY_MESSAGES = 6` (3 Q&A pairs) and `MAX_OUTPUT_CHARS = 1000` to guarantee token consumption stays under Groq's 6,000 TPM limit.
   - Strict System Prompt: Forbids nested double quotes (`"`) and `history` command; enforces single quotes (`'`) and exact log inspection commands (`stat /var/lib/apt/periodic/update-success-stamp`, `grep -E 'Start-Date|Commandline' /var/log/apt/history.log`).
   - Resiliency: Automatic 3-attempt retry with 2.5s backoff on 429 rate limit responses, and auto-clears conversation history on 400/429 errors to unblock user chats.

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
