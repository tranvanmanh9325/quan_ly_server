# 🖥️ Mini Server Dashboard

**A self-hosted, real-time server monitoring dashboard.**
Connect to any remote Linux host over SSH and visualise live system metrics through a modern, dark-themed web interface.

[![CI/CD](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml)
![Java](https://img.shields.io/badge/Java-21-orange?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-4.0.5-6DB33F?logo=springboot&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-Compose_V2-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## Overview

Mini Server Dashboard gives you a single-pane-of-glass view of a remote Linux server without installing any agent software on the target host. The backend holds a **persistent SSH session** (via JSch) and executes standard Linux commands (`top`, `free`, `df`, `sensors`, `ps`, `who`, etc.) to gather metrics. The frontend polls these endpoints and renders the data as live charts and tables. The entire stack ships as two Docker containers orchestrated by Compose, with a self-hosted GitHub Actions runner providing zero-touch continuous deployment.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Local Development Setup](#local-development-setup)
- [Production Deployment](#production-deployment)
- [CI/CD Pipeline](#cicd-pipeline)
- [Environment Variables](#environment-variables)
- [Security Notes](#security-notes)
- [Automated Dependency Updates](#automated-dependency-updates)
- [License](#license)

> 📚 For in-depth technical documentation see the **[`/docs`](./docs/README.md)** directory.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                  Docker Network  (bridge)                │
│                                                         │
│  ┌──────────────────┐   /api/*   ┌───────────────────┐  │
│  │    Frontend      │ ─────────▶ │      Backend      │  │
│  │  React + Nginx   │            │  Spring Boot 3.5  │  │
│  │   Port 5173:80   │            │    Port 8080      │  │
│  └──────────────────┘            │  JSch SSH Client  │  │
│                                  └────────┬──────────┘  │
└───────────────────────────────────────────│─────────────┘
                                            │ SSH (port 22 / Ngrok TCP)
                                            ▼
                                  ┌──────────────────┐
                                  │  Remote Linux    │
                                  │  Server / VPS    │
                                  └──────────────────┘
```

**Request flow:**

1. The browser loads the React SPA served by **Nginx**.
2. All `/api/*` XHR calls are reverse-proxied by Nginx to **Spring Boot**.
3. Spring Boot forwards each request as a shell command over the **persistent SSH session**.
4. Raw shell output is returned as JSON; all parsing is done in **`frontend/src/utils/parsers.js`** — keeping the Java layer thin and parsers independently unit-testable.

---

## Tech Stack

| Layer | Technology | Version |
| --- | --- | --- |
| Frontend Framework | React | 19 |
| Frontend Build Tool | Vite | 6 |
| Charts | Recharts | 3 |
| HTTP Client | Axios | 1 |
| Icons | Lucide React | latest |
| Frontend Server | Nginx (Alpine) | latest |
| Backend Framework | Spring Boot | 4.0.5 |
| Backend Language | Java | 21 |
| SSH Client | JSch (mwiede fork) | 2.27.9 |
| Health Check | Spring Actuator | — |
| Containerization | Docker + Compose | V2 |
| CI/CD | GitHub Actions (self-hosted runner) | — |
| Dependency Updates | Dependabot | — |

---

## Features

### 📊 Real-Time Metrics *(polled every 10 s, adaptive)*

| Metric | Details |
| --- | --- |
| **CPU Usage** | Live area chart with a 15-data-point scrolling history window |
| **RAM Usage** | Donut chart with used / cached / swap breakdown |
| **Disk Space** | Per-partition usage bars; excludes `tmpfs` and `devtmpfs` |
| **Network Traffic** | Live download/upload speeds derived from `/proc/net/dev` deltas |
| **Temperature** | Per-core readings from `sensors`; warns at ≥ 70 °C, critical at ≥ 85 °C; falls back to `/sys/class/thermal/thermal_zone*/temp` |
| **Voltage Rails** | Per-rail values from `sensors` with ±5 % / ±10 % deviation thresholds |

### 🔧 System Information

| Feature | Details |
| --- | --- |
| **Process Table** | Full process list (PID, user, CPU %, memory, threads, args); updated every 30 s with debounced search (300 ms) |
| **Active Connections** | Live SSH sessions via `who`; clickable to view connection details |
| **Server Info** | Hostname, OS, kernel, and CPU model fetched in a single SSH round-trip |
| **Uptime & Load Average** | Parsed from `uptime` output |

### ⚡ Smart Polling

| Behaviour | Description |
| --- | --- |
| **Adaptive interval** | Automatically backs off from 10 s → 20 s when SSH response latency exceeds 5 s |
| **Visibility API integration** | Suspends all SSH polling when the browser tab is hidden; resumes immediately on focus |

---

## Project Structure

```text
quan_ly_server/
├── backend/                              # Spring Boot service
│   ├── src/main/java/com/miniserver/dashboard/
│   │   ├── DashboardApplication.java         # Entry point
│   │   ├── config/
│   │   │   └── CorsConfig.java               # CORS policy
│   │   ├── controller/
│   │   │   ├── MetricsController.java         # /api/metrics/* endpoints
│   │   │   └── FileManagerController.java     # /api/files/* endpoints
│   │   └── service/
│   │       └── SshService.java               # Persistent SSH session + retry logic
│   ├── src/main/resources/
│   │   └── application.properties            # Reads credentials from .env
│   ├── .env                                  # ⚠ Not committed — SSH credentials
│   ├── Dockerfile                            # Multi-stage: Maven builder → JRE Alpine
│   └── pom.xml
│
├── frontend/                             # React + Vite SPA
│   ├── src/
│   │   ├── App.jsx                           # Root component; all state & polling logic
│   │   ├── App.css / index.css               # Global styles (dark glassmorphism theme)
│   │   ├── main.jsx                          # React DOM entry point
│   │   └── utils/
│   │       └── parsers.js                    # Pure functions: raw SSH output → typed objects
│   ├── nginx.conf                            # Static serving + /api/ reverse proxy
│   ├── vite.config.js                        # Dev proxy: /api → localhost:8080
│   ├── Dockerfile                            # Multi-stage: Node builder → Nginx Alpine
│   └── package.json
│
├── .github/
│   ├── dependabot.yml                        # Weekly auto-PRs for npm, Maven, Docker, Actions
│   └── workflows/
│       └── deploy.yml                        # Self-hosted runner: pull + compose up
│
├── docker-compose.yml                    # Orchestrates backend + frontend with health checks
└── SECURITY.md                           # Vulnerability reporting policy
```

---

## API Reference

All endpoints are `GET /api/metrics/<resource>`. The backend returns raw shell output wrapped in a JSON envelope; parsing is intentionally delegated to the frontend.

| Endpoint | Shell Command | Response Shape |
| --- | --- | --- |
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

> **Design decision:** Keeping the Java layer as a thin tunnel (no parsing) means the entire parsing logic lives in `parsers.js`, where it can be unit-tested without a live SSH connection.

---

## Local Development Setup

### Development Prerequisites

| Tool | Minimum Version |
| --- | --- |
| Java | 21 |
| Maven | 3.9 |
| Node.js | 20 |
| Docker Desktop | 24 (for production mode) |

### 1 — Backend

```bash
# Copy the environment template and fill in your SSH target credentials
cp backend/.env.example backend/.env
nano backend/.env
```

```bash
cd backend
mvn spring-boot:run
# API available at http://localhost:8080
```

### 2 — Frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
# Vite automatically proxies /api/* → http://localhost:8080
```

---

## Production Deployment

### Server Prerequisites

- Docker Engine 24+ and Docker Compose V2 installed on the host
- A target Linux server reachable via SSH (direct or via an Ngrok TCP tunnel)

### Steps

**1. Clone the repository on your server:**

```bash
git clone https://github.com/<YOUR_USERNAME>/quan_ly_server.git ~/quan_ly_server
cd ~/quan_ly_server
```

**2. Create the environment file:**

```bash
cp backend/.env.example backend/.env
nano backend/.env   # fill in SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD
```

**3. Build and start all services:**

```bash
docker compose up -d --build
```

**4. Verify health:**

```bash
docker compose ps
# Both dashboard_backend and dashboard_frontend should report "healthy"
```

**5. Access the dashboard:**

| Service | URL |
| --- | --- |
| UI | `http://<server-ip>:5173` |
| Backend health | `http://<server-ip>:8080/actuator/health` |

### Resource Limits

| Container | CPU Limit | Memory Limit | Memory Reservation |
| --- | --- | --- | --- |
| `dashboard_backend` | 1.5 cores | 1 GB | 512 MB |
| `dashboard_frontend` | 0.5 cores | 256 MB | 64 MB |

> The backend health check polls `GET /actuator/health` every **30 s** (3 retries, 90 s start period). The frontend container only starts after the backend is `healthy`.

---

## CI/CD Pipeline

The repository uses a **self-hosted GitHub Actions runner** so the workflow executes directly on the production server — no SSH secrets stored in GitHub.

**Trigger:** any push to `main`.

**Workflow (`deploy.yml`):**

```text
git reset --hard  →  git pull origin main  →  docker compose up -d --build
```

This achieves a rolling rebuild with minimal downtime: only containers whose images have changed are recreated.

### Setting Up the Self-Hosted Runner

**1. Register a runner in GitHub:**

> Repository → **Settings** → **Actions** → **Runners** → **New self-hosted runner** → Linux / x64

Copy the exact commands GitHub generates (they embed a one-time registration token).

**2. Install the runner agent on the server:**

```bash
mkdir ~/actions-runner && cd ~/actions-runner

# Download — use the exact URL and filename GitHub provides
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-X.X.X.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz

# Register — use the token GitHub provides
./config.sh --url https://github.com/<YOUR_USERNAME>/quan_ly_server --token <YOUR_TOKEN>
```

**3. Run as a system service (survives reboots):**

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

**4. Verify:** Navigate to **Settings → Actions → Runners**. The runner should appear as **Idle** (green dot).

From this point, every `git push origin main` triggers an automated rebuild. Monitor progress in the **Actions** tab on GitHub.

---

## Environment Variables

Create `backend/.env` by copying the template below. This file is listed in `.gitignore` and must **never** be committed.

```dotenv
# backend/.env — SSH target credentials
SSH_HOST=your.ssh.host.or.ngrok.address
SSH_PORT=22
SSH_USER=your_ssh_username
SSH_PASSWORD=your_ssh_password
```

> **Recommended:** For production, prefer SSH key-based authentication over passwords. JSch supports key-pair authentication via `jsch.addIdentity(privateKeyPath)`. See `SshService.java` for the integration point.

---

## Security Notes

> [!WARNING]
> Ensure `backend/.env` has **never** been committed to the repository history. If it was committed by mistake, rotate your SSH credentials immediately and purge the file from git history using [`git filter-repo`](https://github.com/newren/git-filter-repo).
>
> [!CAUTION]
> The current `CorsConfig.java` whitelists only `localhost:5173`. In production, the frontend and backend share the same Nginx origin, so CORS is not exercised at runtime. However, if you ever expose port `8080` directly, restrict the `allowedOrigins` to your actual domain.
>
> [!CAUTION]
> All `/api/**` routes are **unauthenticated** by design — the dashboard is intended to run behind a private network or firewall. **Do not expose ports `8080` or `5173` to the public internet** without adding an authentication layer first.
>
> [!NOTE]
> `StrictHostKeyChecking` is disabled (`no`) in `SshService.java` to accommodate Ngrok tunnels, where the remote host key changes on every reconnect. For a stable production environment with a static server IP, enable host key checking and store the known host fingerprint.

For the full security policy and vulnerability reporting process, see [SECURITY.md](./SECURITY.md).

---

## Automated Dependency Updates

Dependabot is configured to open weekly pull requests across all four package ecosystems:

| Ecosystem | Directory | Max PRs / week |
| --- | --- | --- |
| npm (frontend) | `/frontend` | 10 |
| Maven (backend) | `/backend` | 10 |
| Docker base images | `/` | 5 |
| GitHub Actions | `/` | 5 |

---

## License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for details.
