# Rule 01 — Project Overview & Non-Negotiable Constraints

## What This Project Is

Mini Server Dashboard is a **self-hosted, real-time monitoring application**.
It connects to a remote Linux server over SSH and visualises system metrics
(CPU, RAM, disk, network, temperature, voltage, processes, active connections)
in a single-page React dashboard served through Nginx.

```text
Browser → React 19 (Nginx :5173)
              ↓  /api/*
       Spring Boot 4 (:8080)
              ↓  SSH (port 22 / Ngrok TCP)
       Remote Linux Server
```

This is a **personal / private-network tool**.
It is NOT designed for multi-tenant, multi-server, or public-internet scenarios.

---

## Technology Stack (pinned — do not silently upgrade)

| Layer | Technology | Version |
| --- | --- | --- |
| Frontend framework | React | 19.x |
| Frontend build | Vite | 8.x |
| Frontend charts | Recharts | 3.x |
| Frontend icons | lucide-react | 1.x |
| Frontend HTTP | Axios | 1.x |
| Frontend linting | ESLint 9 (flat config) | 9.x |
| Production server | Nginx Alpine | latest-alpine |
| Backend framework | Spring Boot | 4.0.x |
| Backend language | Java | 21 (LTS) |
| Backend SSH client | jsch (mwiede fork) | 2.x |
| Backend utility | Lombok | managed by Spring BOM |
| Backend runtime monitoring | Spring Actuator | managed by Spring BOM |
| Containerisation | Docker + Compose | v2 (compose v2 syntax) |
| CI/CD | GitHub Actions (self-hosted runner) | — |
| Dependency updates | Dependabot | weekly cadence |

> **Before adding any new library**, verify it does not duplicate functionality
> already provided by the stack above. Open an ADR (Architecture Decision
> Record) comment in the PR if you must deviate.

---

## Architectural Laws (never break these)

1. **All SSH output parsing lives in `frontend/src/utils/parsers.js`.**
   The Java layer must stay a thin tunnel — it executes commands and returns
   raw strings. No parsing logic in Java controllers or services.

2. **`SshService` maintains one shared `JSch` session per application lifetime.**
   Never open a new session per-request. Channel-per-request is correct.

3. **`StrictHostKeyChecking = no` is intentional for Ngrok compatibility.**
   Do not "fix" it without first introducing a proper known-hosts management
   strategy. Document any change in `SECURITY.md`.

4. **CORS is development-only.** In production Docker deployment, Nginx proxies
   `/api/*` to the backend — the browser never makes cross-origin calls.
   `CorsConfig.java` exists solely for the local `vite dev` workflow.

5. **No database, no persistence layer.** All data is ephemeral, fetched
   live from the remote server on every poll cycle.

6. **No authentication on API routes.** This is by design. The dashboard
   must be deployed behind a private network or firewall. Never expose
   ports 8080 or 5173 directly to the public internet.

---

## Deployment Model

```text
git push origin main
  └─▶ GitHub Actions (deploy.yml)
        └─▶ Self-hosted runner on production server
              ├─ git reset --hard
              ├─ git pull origin main
              └─ docker compose up -d --build
```

The `backend/.env` file holds live SSH credentials. It is **never committed**
to version control. It must exist on the production server before the runner
executes. Verify `.gitignore` covers it before every merge.
