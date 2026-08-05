# Mini Server Dashboard — Sci-Fi Cyberpunk Edition

**A self-hosted, real-time server monitoring & management dashboard with a Cyberpunk/Sci-Fi HUD interface.**  
Connect to any remote Linux host over SSH and control live system metrics, processes, services, containers, files, and logs — all from a stunning, futuristic web UI.

---

## Table of Contents

- [Overview](#overview)
- [Screenshots / Demo](#screenshots--demo)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Local Development Setup](#local-development-setup)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Mini Server Dashboard provides a **single-pane-of-glass operational center** for remote Linux servers — no agent installation required on target hosts.

The Spring Boot backend maintains a **persistent SSH session** (via JSch with root-level command elevation) and executes standard Linux shell commands (`top`, `free`, `df`, `sensors`, `ps`, `systemctl`, `docker`, `ss`, `journalctl`, etc.) to collect metrics in real time. The React frontend renders live charts, gauges, 3D globe maps, and interactive control panels with a custom Cyberpunk aesthetic.

> **Designed for**: Developers and sysadmins who want a beautiful, self-hosted alternative to Grafana/Netdata for single-server monitoring.

---

## Screenshots / Demo

### 1. System Overview Dashboard (`/`)

Real-time KPI metrics, CPU & RAM gauges, load average, disk space, and active server telemetry.
![Dashboard Overview](./docs/assets/dashboard-overview.png)

### 2. Process Explorer (`/processes`)

Live Linux process monitor with column sorting, CPU/Memory filtering, process termination modal, and CSV export.
![Process Explorer](./docs/assets/dashboard-processes.png)

### 3. Services & Docker Runtime Center (`/services`)

Manage systemd services, view live Docker container statuses, inspect container logs, and monitor host runtimes.
![Services & Docker](./docs/assets/dashboard-services.png)

### 4. Interactive Web SSH Terminal Console (`/terminal`)

Embedded web terminal with command history, security sandbox, and 1-click Quick Command Macro Chips with `SciFiLightningIcon`.
![Terminal Console](./docs/assets/dashboard-terminal.png)

### 5. Control Center & Settings (`/settings`)

Configure critical alert threshold sliders, global refresh speeds, Telegram AI agent settings, and Sci-Fi HUD effects.
![Settings](./docs/assets/dashboard-settings.png)

---

## Key Features

### Autonomous Telegram AI Agent

- **Groq LLM Engine (`llama-3.1-8b-instant`):** Natural language system diagnostics and administration via Telegram.
- **SSH Tool Execution (`run_command` & `sudo`):** Automatically formulates and runs system commands over SSH, using `executeSudoCommand` for privileged tasks.
- **Resilient Context Window & Token Protection:** Rolling 6-message context window and 1,000 char output cap to stay strictly under Groq's 6,000 TPM limit. Includes 3-attempt exponential backoff on 429 rate limits and self-healing conversation history resets.

### System Overview Dashboard (`/`)

- **Live metric cards**: CPU usage (chart + sparkline), RAM usage (donut gauge), Disk Space (partition bars), Load Average, Network Traffic, CPU Thermal, Voltage & Power, Fan Control.
- **CRITICAL ALERT system**: Header turns pulsing red when any threshold is breached (configurable in Settings).
- **Adaptive polling engine**: Automatically slows refresh rate when SSH response time exceeds 5 seconds to protect both server and UX.

### 3D Interactive Globe Map (`/map`)

- **Real orthographic 3D globe** rendered with D3-geo + TopoJSON with detailed country boundaries.
- **Server location marker**: Geolocates the monitored server and displays a neon teardrop pin with sonar pulse rings.
- **Connected nodes panel**: Tracks active SSH tunnel connections with country flags and IP metadata.
- Auto-rotating globe with drag-to-rotate interaction.

### Process Explorer (`/processes`)

- Smart column sorting by **CPU%**, **Memory MB**, **PID**, or **Name**.
- Quick filter tabs: `ALL` / `HIGH CPU (>20%)` / `HIGH MEM (>100MB)`.
- Force-kill processes via a Glassmorphic confirmation modal.
- **1-click CSV export** of the filtered process table.

### Services & Runtime Center (`/services`)

- **Systemd Services**: View status and 1-click **Start / Stop / Restart**.
- **Docker Containers**: Full container list with port mappings, live status badges, control actions, and an interactive **Log Viewer Modal** (`docker logs --tail`).
- **Systemd Timers**: Monitor daily automated update/upgrade timers (`apt-daily.timer` at 06:00 AM, `apt-daily-upgrade.timer` at 06:30 AM).
- **Host Runtimes**: Detect installed runtimes (Docker, Node.js, Java, Python) and daemons (Nginx, PostgreSQL, Redis, UFW).

### File Manager (`/files`)

- SSH-powered filesystem browser — navigate directories, view file contents, create, rename, and delete files/folders.
- Syntax-aware file viewer for common code and config file types.

### Docker Containers (`/containers`)

- Dedicated container management page with real-time status monitoring.
- One-click container lifecycle control (start, stop, restart).
- Inspect container logs with configurable tail lines.

### Terminal Console (`/terminal`)

- Embedded web-based SSH terminal (`root@server:~#`).
- **Command history** navigation with ↑/↓ arrow keys.
- **Quick command chips** with custom `SciFiLightningIcon` vector graphics for common diagnostics (`uname -a`, `df -h`, `docker ps`, `ss -tulpn`...).
- Built-in **security sandbox** blocking destructive commands (`rm -rf`, `mkfs`, `reboot`, etc.).
- Copy output to clipboard or clear console with 1-click.

### Security & Logs (`/security`)

- **Listening Ports**: TCP & UDP socket scanning with PID/process mapping.
- **Active SSH Sessions**: Real-time user login tracking via `who`.
- **Colorized Log Viewer**: `ERROR`/`DENIED` → Pink, `WARN` → Yellow, `INFO` → Green.
- Log search by keyword/level + export to `.log` file.

### Settings (`/settings`)

- **Alert Thresholds**: Configurable sliders for CPU, RAM, and Disk — changes instantly affect the CRITICAL ALERT system.
- **Polling Interval**: Override global refresh speed per-session.
- **Display Toggles**: Enable/disable cursor FX, click sounds, scanline overlay, and grid background.
- **SSH Connection Status**: Live ping to backend with connection info.
- All preferences persist via `localStorage`.

### Sci-Fi UX Layer (Global)

- **Custom HUD Cursor**: Rotating dual-ring SVG crosshair (replaces native cursor globally).
- **Click Effects**: Canvas-based energy shockwave, particle burst, diamond shards, and crosshair flash on every click.
- **Synthesized Audio**: Web Audio API laser chirp + sub-bass thump + static crackle — no external audio files needed.
- **Cyberpunk design system**: Neon cyan/green/pink palette, `clip-path` angled panels, `Share Tech Mono` monospace font, animated Tron grid background, scanline overlay.

---

## Tech Stack

| Layer | Technology | Version |
| --- | --- | --- |
| Frontend Framework | React | 19 |
| Frontend Build Tool | Vite | 8 |
| Routing | React Router DOM | 7 |
| Charts | Recharts | 3 |
| 3D Globe | D3-geo + TopoJSON | 3 / 3 |
| HTTP Client | Axios | 1 |
| Icons | Custom Sci-Fi SVG (`SciFiIcons.jsx`) | — |
| Frontend Server | Nginx (Alpine) | latest |
| Unit Tests | Vitest | 4 |
| Backend Services | Spring Boot (Metrics, Auth, File Services) | 4.1.0 |
| Backend Language | Java | 21 |
| AI Integration | Groq REST API (`llama-3.1-8b-instant`) | — |
| Bot Protocol | Telegram Bot Long Polling | — |
| Database | PostgreSQL | 17 |
| SSH Client | JSch (mwiede fork) | 2.28.5 |
| Containerization | Docker + Compose V2 | — |
| CI/CD | GitHub Actions | — |

---

## Architecture

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

## Project Structure

```text
quan_ly_server/
├── .env                                  # Root environment file (SSH & DB credentials)
├── .gitignore
├── docker-compose.yml                    # Orchestrates backend services, frontend & db containers
├── LICENSE
├── SECURITY.md
│
├── docs/                                 # 11 Comprehensive Technical Guides
│   ├── README.md                         # Documentation index
│   ├── architecture.md                   # System design & microservices topology
│   ├── api-reference.md                  # REST endpoints reference
│   ├── frontend-internals.md             # React state & parser layer
│   ├── backend-internals.md              # Spring Boot & JSch SSH service
│   ├── telegram-ai-agent.md              # Autonomous Telegram bot & Groq LLM agent
│   ├── database-and-auth.md              # Auth service, JWT security & PostgreSQL schema
│   ├── system-automation.md              # Daily APT timers & auto-cleanup policy
│   ├── deployment.md                     # Docker & CI/CD deployment guide
│   ├── security.md                       # Security trade-offs & hardening
│   └── troubleshooting.md                # Diagnostic guides & fixes
│
├── services/                             # Spring Boot 4.1.0 Microservices
│   ├── metrics-service/                  # Telemetry, SSH JSch tunnel, Telegram & Groq AI
│   ├── auth-service/                     # Authentication & JWT security
│   └── file-service/                     # Remote file system operations
│
└── frontend/                             # React 19 + Vite 8 SPA
    ├── src/
    │   ├── App.jsx                       # Root layout & routing outlet
    │   ├── components/
    │   │   ├── SciFiIcons.jsx            # Custom vector SVG icons library
    │   │   └── SpaceInteractionLayer.jsx # Global cursor, click FX & audio engine
    │   ├── pages/
    │   │   ├── OverviewPage.jsx          # Overview cards, charts & Fan HUD
    │   │   ├── ProcessesPage.jsx         # Process explorer & CSV export
    │   │   ├── ServicesPage.jsx          # Systemd, Docker, timers & runtimes
    │   │   ├── TerminalPage.jsx          # Web SSH terminal console with macro chips
    │   │   └── SettingsPage.jsx          # User preferences & alert thresholds
    │   └── utils/
    ├── nginx.conf                        # Reverse proxy (/api/* → backend services)
    ├── vite.config.js                    # Rolldown / ManualChunks code splitting
    └── Dockerfile
```

---

## API Reference

All `GET` endpoints return `{ status, data }` JSON. `POST` endpoints accept query params.

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/metrics/system` | GET | Hostname, OS, kernel, uptime |
| `/api/metrics/cpu` | GET | CPU usage % (top) |
| `/api/metrics/ram` | GET | Memory breakdown via `free -m` |
| `/api/metrics/disk` | GET | Partition usage via `df -h` |
| `/api/metrics/disk-io` | GET | Read/write throughput via `/proc/diskstats` |
| `/api/metrics/network` | GET | Interface TX/RX deltas via `/proc/net/dev` |
| `/api/metrics/temperature` | GET | Sensor temps via `sensors` |
| `/api/metrics/voltage` | GET | Voltage readings via `sensors` |
| `/api/metrics/fan` | GET | Fan RPM & control mode |
| `/api/metrics/gpu` | GET | GPU stats via `nvidia-smi` (if available) |
| `/api/metrics/load-average` | GET | 1/5/15-min load averages |
| `/api/metrics/processes` | GET | Process list via `ps -eo` |
| `/api/metrics/services` | GET | Systemd unit statuses |
| `/api/metrics/timers` | GET | Systemd timer schedules |
| `/api/metrics/runtimes` | GET | Installed runtimes & daemon health |
| `/api/metrics/ports` | GET | Listening sockets via `ss -tulpn` |
| `/api/metrics/connections` | GET | Active SSH connections via `ss` |
| `/api/metrics/logs` | GET | Recent system log entries |
| `/api/metrics/docker` | GET | Docker container list |
| `/api/metrics/geolocation` | GET | Server geolocation via `curl ipapi.co` |
| `/api/metrics/docker/logs` | GET | Tail Docker container logs (`containerId`, `lines`) |
| `/api/metrics/services/control` | POST | Control systemd service (`service`, `action`) |
| `/api/metrics/docker/control` | POST | Control Docker container (`containerId`, `action`) |
| `/api/metrics/kill-process` | POST | Kill process by PID (`pid`) |
| `/api/metrics/execute-command` | POST | Execute allowlisted command in terminal |

---

## Local Development Setup

### Prerequisites

- Docker & Docker Compose V2
- A remote Linux server accessible via SSH (or Ngrok TCP tunnel)

### 1. Clone & Configure Environment

```bash
git clone https://github.com/tranvanmanh9325/quan_ly_server.git
cd quan_ly_server
```

Create `.env` in the root directory:

```dotenv
# ==========================================
# ROOT ENVIRONMENT CONFIGURATION (.env)
# ==========================================

# Primary SSH Target Credentials (LAN)
SSH_HOST=your_target_server_ip
SSH_PORT=22
SSH_USER=your_ssh_user
SSH_PASSWORD=your_ssh_password

# SSH Fallback via Ngrok (used automatically when LAN is unreachable)
SSH_FALLBACK_HOST=your_fallback_ngrok_host
SSH_FALLBACK_PORT=12345

# Database Configuration (PostgreSQL 17)
POSTGRES_DB=quan_ly_server
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password

# Auth Service Credentials & JWT Secret (>= 32 chars)
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=your_bcrypt_hashed_password
JWT_SECRET=your_secret_jwt_key_at_least_32_characters_long

# Telegram Bot Integration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
TELEGRAM_POLLING_ENABLED=true

# Groq AI Integration (llama-3.1-8b-instant)
GROQ_API_KEY=your_groq_api_key
```

> ⚠️ **Never commit `.env` to git.** It is already in `.gitignore`.

### 2. Run with Docker Compose

```bash
# Build and start all containers (db → backend → frontend)
docker compose up -d --build

# Follow logs
docker compose logs -f

# Stop everything
docker compose down
```

Access the Web UI at **`http://localhost:5173`**

Backend health check: `http://localhost:8080/actuator/health`

### 3. Local Frontend Dev (Hot Reload)

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev      # Vite dev server on :5174, proxies /api/* to localhost:8080
```

### 4. Run Unit Tests

```bash
cd frontend
npm test         # Vitest — 11 parser unit tests
```

---

## Contributing

1. **Fork** the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit with conventional commits: `git commit -m "feat: add new metric card"`
4. Push and open a **Pull Request** against `main`
5. Ensure all CI checks pass before requesting review

Please read [`SECURITY.md`](./SECURITY.md) before reporting any security issues.

---

## License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for details.

Copyright © 2026 [Tran Van Manh](https://github.com/tranvanmanh9325)
