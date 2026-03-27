# Mini Server Dashboard

A real-time server monitoring dashboard that connects to a remote Linux host over SSH and displays live system metrics through a modern web interface. The entire stack is containerized with Docker and ships with a self-hosted GitHub Actions CI/CD pipeline for zero-touch deployments.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Local Development Setup](#local-development-setup)
- [Production Deployment (Docker)](#production-deployment-docker)
- [CI/CD Pipeline](#cicd-pipeline)
- [Environment Variables](#environment-variables)
- [Security Notes](#security-notes)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                  Docker Network (bridge)              │
│                                                      │
│  ┌─────────────────┐       ┌──────────────────────┐  │
│  │   Frontend      │       │      Backend          │  │
│  │  React + Nginx  │──────▶│  Spring Boot (8080)  │  │
│  │   Port 5173:80  │ /api/ │                      │  │
│  └─────────────────┘       │  SSH Client (JSch)   │  │
│                            └──────────┬───────────┘  │
└───────────────────────────────────────│──────────────┘
                                        │ SSH
                                        ▼
                              ┌─────────────────┐
                              │  Remote Linux   │
                              │  Server / VPS   │
                              │  (via Ngrok)    │
                              └─────────────────┘
```

The frontend is a static React SPA served by Nginx. Nginx reverse-proxies all `/api/*` requests to the Spring Boot backend. The backend maintains a single persistent SSH session to the target server and executes shell commands to collect metrics, returning the raw output as JSON. All parsing happens on the frontend.

---

## Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Frontend Framework | React | 19 |
| Frontend Build Tool | Vite | 8 |
| Charts | Recharts | 3 |
| HTTP Client | Axios | 1 |
| Icons | Lucide React | latest |
| Frontend Server | Nginx (Alpine) | latest |
| Backend Framework | Spring Boot | 3.5 |
| Backend Language | Java | 21 |
| SSH Client | JSch (mwiede fork) | 0.2.16 |
| Health Check | Spring Actuator | - |
| Containerization | Docker + Compose | v2 |
| CI/CD | GitHub Actions (self-hosted) | - |
| Dependency Updates | Dependabot | - |

---

## Features

### Real-time Metrics (polled every 10 s, adaptive)
- **CPU Usage** — Live area chart with 15-data-point history window
- **RAM Usage** — Donut chart with used/cached/swap breakdown
- **Disk Space** — Per-partition usage bars (excludes `tmpfs` / `devtmpfs`)
- **Network Traffic** — Live download/upload speeds derivated from `/proc/net/dev` deltas
- **Temperature** — Per-core temperatures from `sensors` with `warn ≥ 70 °C` / `crit ≥ 85 °C` thresholds; falls back to `/sys/class/thermal/thermal_zone*/temp`
- **Voltage Rails** — Per-rail voltage from `sensors` with `±5%/±10%` deviation thresholds

### Other Features
- **Process Table** — Full process list (PID, user, CPU %, memory, threads, args) updated every 30 s with debounced search (300 ms)
- **Active Connections** — Live SSH sessions via `who`, clickable to view connection details
- **Server Info** — Hostname, OS, kernel, and CPU model fetched in a single SSH round-trip
- **System Uptime & Load Average** — Parsed from `uptime`
- **Adaptive Polling** — Automatically increases interval from 10 s → 20 s when SSH response takes > 5 s
- **Visibility API integration** — Pauses all SSH polling when the browser tab is hidden; resumes immediately on focus

---

## Project Structure

```
quan_ly_server/
├── backend/                        # Spring Boot service
│   ├── src/main/java/com/miniserver/dashboard/
│   │   ├── DashboardApplication.java      # Entry point
│   │   ├── config/
│   │   │   └── CorsConfig.java            # CORS policy (dev: localhost:5173)
│   │   ├── controller/
│   │   │   └── MetricsController.java     # REST API endpoints (/api/metrics/*)
│   │   └── service/
│   │       └── SshService.java            # Persistent SSH session + retry logic
│   ├── src/main/resources/
│   │   └── application.properties         # Spring config (reads from .env)
│   ├── .env                               # ⚠ Not committed — SSH credentials
│   ├── .gitignore
│   ├── Dockerfile                         # Multi-stage: Maven builder + JRE Alpine
│   └── pom.xml
│
├── frontend/                       # React + Vite SPA
│   ├── src/
│   │   ├── App.jsx                        # Root component, all state & polling logic
│   │   ├── App.css / index.css            # Global styles (dark glassmorphism theme)
│   │   ├── main.jsx                       # React DOM entry point
│   │   └── utils/
│   │       └── parsers.js                 # Pure functions: parse raw SSH output → typed objects
│   ├── nginx.conf                         # Nginx: static serve + /api/ proxy
│   ├── vite.config.js                     # Dev proxy: /api → localhost:8080
│   ├── Dockerfile                         # Multi-stage: Node builder + Nginx Alpine
│   └── package.json
│
├── .github/
│   ├── dependabot.yml                     # Weekly auto-PRs for npm, maven, docker, actions
│   └── workflows/
│       └── deploy.yml                     # Self-hosted runner: git pull + docker compose up
│
└── docker-compose.yml              # Orchestrates backend + frontend with healthchecks
```

---

## API Reference

All endpoints are under `/api/metrics` (GET).

| Endpoint | Shell Command | Response Shape |
|----------|--------------|----------------|
| `/cpu` | `top -bn1 \| grep 'Cpu(s)'` | `{ "data": "<raw top line>" }` |
| `/ram` | `free -m` | `{ "data": "<raw free output>" }` |
| `/disk` | `df -h -x tmpfs -x devtmpfs` | `{ "data": "<raw df output>" }` |
| `/network` | `cat /proc/net/dev` | `{ "data": "<raw proc output>" }` |
| `/processes` | `ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu` | `{ "data": "<raw ps output>" }` |
| `/temperature` | `sensors` (fallback: `/sys/class/thermal/*/temp`) | `{ "data": "<raw sensors output>" }` |
| `/voltage` | `sensors` | `{ "data": "<raw sensors output>" }` |
| `/system` | `uptime` | `{ "data": "<raw uptime string>" }` |
| `/connections` | `who` | `{ "data": [{ "user", "terminal", "loginTime", "ip" }] }` |
| `/sysinfo` | `uname -r` + `hostname` + `/etc/os-release` + `lscpu` | `{ "kernel", "hostname", "os", "cpuModel" }` |

> **Design note:** The backend intentionally returns raw shell output and delegates all parsing to `frontend/src/utils/parsers.js`. This keeps the Java layer thin and makes parsers independently unit-testable.

---

## Local Development Setup

### Prerequisites

- Java 21+
- Maven 3.9+
- Node.js 20+
- Docker Desktop (for production mode)

### 1. Backend

```bash
# Create the .env file (never commit this)
cp backend/.env.example backend/.env
# Edit backend/.env with your SSH target credentials
```

```bash
cd backend
mvn spring-boot:run
# API available at http://localhost:8080
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
# Vite automatically proxies /api/* → http://localhost:8080
```

---

## Production Deployment (Docker)

### Prerequisites

- Docker Engine 24+ and Docker Compose V2 installed on the server
- A running target Linux host accessible via SSH (or via an Ngrok TCP tunnel)

### Steps

**1. Clone the repository on your server:**
```bash
git clone https://github.com/<YOUR_USERNAME>/quan_ly_server.git ~/my-code/quan_ly_server
cd ~/my-code/quan_ly_server
```

**2. Create the environment file:**
```bash
cp backend/.env.example backend/.env
# Then edit backend/.env with the real SSH credentials
nano backend/.env
```

**3. Build and start all services:**
```bash
docker compose up -d --build
```

**4. Verify services are healthy:**
```bash
docker compose ps
# Both dashboard_backend and dashboard_frontend should show "healthy"
```

**5. Access the dashboard:**
- **UI:** `http://<server-ip>:5173`
- **Backend health:** `http://<server-ip>:8080/actuator/health`

### Resource Limits (configured in docker-compose.yml)

| Service | CPU Limit | Memory Limit | Memory Reserved |
|---------|-----------|-------------|-----------------|
| `dashboard_backend` | 1.5 cores | 1 GB | 512 MB |
| `dashboard_frontend` | 0.5 cores | 256 MB | 64 MB |

The backend health check polls `GET /actuator/health` every 30 s (3 retries, 90 s start period). The frontend only starts after the backend is `healthy`.

---

## CI/CD Pipeline

The repository uses a **self-hosted GitHub Actions runner** so that the workflow runs directly on the production server, eliminating the need for SSH secrets in GitHub.

**Trigger:** any push to the `main` branch.

**Workflow steps (`deploy.yml`):**
1. Navigate to the project directory on the server
2. `git reset --hard` — discard any local modifications
3. `git pull origin main` — fetch latest code
4. `docker compose up -d --build` — rebuild and restart changed containers (rolling, minimal downtime)

### Setting Up the Self-Hosted Runner

**1. Register a new runner in GitHub:**

> Repository → Settings → Actions → Runners → **New self-hosted runner** → Linux / x64

Copy the exact commands GitHub generates (they contain a unique registration token).

**2. Install the runner on the server:**

```bash
mkdir ~/actions-runner && cd ~/actions-runner

# Download (use the exact URL GitHub provides)
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-X.X.X.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz

# Register (use the exact command GitHub provides)
./config.sh --url https://github.com/<YOUR_USERNAME>/quan_ly_server --token <YOUR_TOKEN>
# Press Enter to accept all defaults
```

**3. Install as a system service (survives reboots):**

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

**4. Verify:** Go back to GitHub → Settings → Actions → Runners. The runner status should appear as **Idle** (green).

From now on, every `git push origin main` triggers an automated rebuild. Monitor progress in the **Actions** tab on GitHub.

---

## Environment Variables

Create `backend/.env` (copy from the example below). This file is listed in `.gitignore` and must **never** be committed.

```dotenv
# backend/.env
SSH_HOST=your.ssh.host.or.ngrok.address
SSH_PORT=22
SSH_USER=your_ssh_username
SSH_PASSWORD=your_ssh_password
```

> **Recommended:** For production, prefer SSH key-based authentication over passwords. JSch supports key-pair authentication via `jsch.addIdentity(privateKeyPath)`.

---

## Security Notes

> [!WARNING]
> The `backend/.env` file is listed in `backend/.gitignore`, but make sure it has never been committed to the repository history. If it was ever committed by mistake, rotate your SSH credentials immediately and consider purging the file from git history using `git filter-repo`.

> [!CAUTION]
> The current `CorsConfig.java` only whitelists `localhost:5173`. In production behind Nginx, the frontend and backend share the same origin (Nginx proxies `/api/`), so CORS is not exercised at runtime. However, if you expose port `8080` directly, ensure you restrict CORS to your actual domain.

> [!NOTE]
> `StrictHostKeyChecking` is disabled (`no`) in `SshService.java` to simplify Ngrok tunnel rotation where the host key changes. In a stable production environment with a fixed server, it is recommended to enable host key checking and store the known host key.

---

## Dependabot

Dependabot is configured to open automated pull requests weekly for all four ecosystems:

| Ecosystem | Directory | PRs/week |
|-----------|-----------|----------|
| npm (frontend) | `/frontend` | up to 10 |
| Maven (backend) | `/backend` | up to 10 |
| Docker base images | `/` | up to 5 |
| GitHub Actions | `/` | up to 5 |