# 🖥️ Mini Server Dashboard — Sci-Fi Cyberpunk Edition

**A self-hosted, real-time server monitoring & management dashboard with a Cyberpunk/Sci-Fi HUD interface.**  
Connect to any remote Linux host over SSH and control live system metrics, processes, services, containers, files, and logs — all from a stunning, futuristic web UI.

[![CI/CD](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml)
![Java](https://img.shields.io/badge/Java-21-orange?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-3.4-6DB33F?logo=springboot&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose_V2-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

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

> 📸 _Insert screenshots or a demo GIF here._  
> Suggested shots: Dashboard overview, 3D Globe Map, Settings page, Terminal Console, Process Explorer.

---

## Key Features

### 🖥️ System Overview Dashboard (`/`)

- **Live metric cards**: CPU usage (chart + sparkline), RAM usage (donut gauge), Disk Space (partition bars), Load Average, Network Traffic, CPU Thermal, Voltage & Power, Fan Control.
- **CRITICAL ALERT system**: Header turns pulsing red when any threshold is breached (configurable in Settings).
- **Adaptive polling engine**: Automatically slows refresh rate when SSH response time exceeds 5 seconds to protect both server and UX.

### 🌍 3D Interactive Globe Map (`/map`)

- **Real orthographic 3D globe** rendered with D3-geo + TopoJSON with detailed country boundaries.
- **Server location marker**: Geolocates the monitored server and displays a neon teardrop pin with sonar pulse rings.
- **Connected nodes panel**: Tracks active SSH tunnel connections with country flags and IP metadata.
- Auto-rotating globe with drag-to-rotate interaction.

### 📈 Process Explorer (`/processes`)

- Smart column sorting by **CPU%**, **Memory MB**, **PID**, or **Name**.
- Quick filter tabs: `ALL` / `HIGH CPU (>20%)` / `HIGH MEM (>100MB)`.
- Force-kill processes via a Glassmorphic confirmation modal.
- **1-click CSV export** of the filtered process table.

### 🛡️ Services & Runtime Center (`/services`)

- **Systemd Services**: View status and 1-click **Start / Stop / Restart**.
- **Docker Containers**: Full container list with port mappings, live status badges, control actions, and an interactive **Log Viewer Modal** (`docker logs --tail`).
- **Systemd Timers**: Monitor countdown timers and next-run timestamps.
- **Host Runtimes**: Detect installed runtimes (Docker, Node.js, Java, Python) and daemons (Nginx, PostgreSQL, Redis, UFW).

### 📁 File Manager (`/files`)

- SSH-powered filesystem browser — navigate directories, view file contents, create, rename, and delete files/folders.
- Syntax-aware file viewer for common code and config file types.

### 🐳 Docker Containers (`/containers`)

- Dedicated container management page with real-time status monitoring.
- One-click container lifecycle control (start, stop, restart).
- Inspect container logs with configurable tail lines.

### 💻 Terminal Console (`/terminal`)

- Embedded web-based SSH terminal (`root@server:~#`).
- **Command history** navigation with ↑/↓ arrow keys.
- **Quick command chips** for common diagnostics (`uname -a`, `df -h`, `docker ps`, `ss -tulpn`...).
- Built-in **security sandbox** blocking destructive commands (`rm -rf`, `mkfs`, `reboot`, etc.).
- Copy output to clipboard or clear console with 1-click.

### 🔒 Security & Logs (`/security`)

- **Listening Ports**: TCP & UDP socket scanning with PID/process mapping.
- **Active SSH Sessions**: Real-time user login tracking via `who`.
- **Colorized Log Viewer**: `ERROR`/`DENIED` → Pink, `WARN` → Yellow, `INFO` → Green.
- Log search by keyword/level + export to `.log` file.

### ⚙️ Settings (`/settings`)

- **Alert Thresholds**: Configurable sliders for CPU, RAM, and Disk — changes instantly affect the CRITICAL ALERT system.
- **Polling Interval**: Override global refresh speed per-session.
- **Display Toggles**: Enable/disable cursor FX, click sounds, scanline overlay, and grid background.
- **SSH Connection Status**: Live ping to backend with connection info.
- All preferences persist via `localStorage`.

### ✨ Sci-Fi UX Layer (Global)

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
| Backend Framework | Spring Boot | 3.4 |
| Backend Language | Java | 21 |
| Database | PostgreSQL | 15 |
| SSH Client | JSch (mwiede fork) | 2.27.9 |
| Containerization | Docker + Compose V2 | — |
| CI/CD | GitHub Actions | — |

---

## Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                  Docker Network  (bridge)                 │
│                                                          │
│  ┌──────────────────┐   /api/*   ┌───────────────────┐   │
│  │    Frontend      │ ─────────▶ │      Backend      │   │
│  │  React + Nginx   │            │  Spring Boot 3.4  │   │
│  │   Port 5173:80   │            │    Port 8080      │   │
│  └──────────────────┘            │  JSch SSH Client  │   │
│                                  └────────┬──────────┘   │
│                          ┌────────────────┘              │
│                          │  PostgreSQL 15                 │
│                          │  (metric history)              │
└──────────────────────────┼────────────────────────────────┘
                           │ SSH (Port 22 / Ngrok TCP)
                           ▼
                 ┌──────────────────┐
                 │  Remote Linux    │
                 │  Server / VPS    │
                 └──────────────────┘
```

**Request flow:**

1. Browser loads the React SPA served by **Nginx** on port 5173.
2. `/api/*` XHR requests are reverse-proxied by Nginx to **Spring Boot** on port 8080.
3. Spring Boot executes shell commands over the **persistent SSH session** (with `sudo -S` elevation where needed).
4. Raw output is returned as JSON; parsing runs in **`frontend/src/utils/parsers.js`**.
5. Metric history is persisted to **PostgreSQL** by `MetricCollectorJob` (scheduled every 60s).

---

## Project Structure

```text
quan_ly_server/
├── .env                                  # Root environment file (SSH & DB credentials)
├── .gitignore
├── docker-compose.yml                    # Orchestrates backend, frontend & db containers
├── LICENSE
├── SECURITY.md
│
├── backend/                              # Spring Boot REST service
│   ├── src/main/java/com/miniserver/dashboard/
│   │   ├── DashboardApplication.java     # Entry point
│   │   ├── controller/
│   │   │   ├── MetricsController.java    # /api/metrics/* REST endpoints
│   │   │   └── FileManagerController.java
│   │   ├── service/
│   │   │   └── SshService.java           # Persistent SSH session + sudo elevation
│   │   └── job/
│   │       └── MetricCollectorJob.java   # Scheduled metric history recorder
│   ├── src/test/java/                    # JUnit 5 & Mockito unit tests
│   ├── Dockerfile
│   └── pom.xml
│
└── frontend/                             # React + Vite SPA
    ├── src/
    │   ├── App.jsx                       # Root router & adaptive polling engine
    │   ├── components/
    │   │   ├── Layout.jsx                # Sci-Fi header bar, sidebar & terminal modal
    │   │   ├── SciFiIcons.jsx            # 16 custom vector SVG icons
    │   │   ├── SpaceInteractionLayer.jsx # Global cursor, click FX & audio engine
    │   │   └── ErrorBoundary.jsx
    │   ├── pages/
    │   │   ├── DashboardPage.jsx         # Overview cards, charts & Fan HUD
    │   │   ├── ProcessesPage.jsx         # Process explorer & CSV export
    │   │   ├── ServicesPage.jsx          # Systemd, Docker, timers & runtimes
    │   │   ├── FileManagerPage.jsx       # SSH filesystem browser
    │   │   ├── ContainersPage.jsx        # Dedicated Docker container manager
    │   │   ├── WorldMapPage.jsx          # 3D orthographic globe with geo markers
    │   │   ├── TerminalPage.jsx          # Web SSH terminal console
    │   │   ├── SecurityPage.jsx          # Ports, sessions, logs & highlighter
    │   │   └── SettingsPage.jsx          # User preferences & alert thresholds
    │   └── utils/
    │       ├── parsers.js                # Shell output → structured data parsers
    │       ├── parsers.test.js           # Vitest unit tests (11 tests)
    │       └── settings.js               # localStorage settings utility
    ├── nginx.conf                        # Reverse proxy (/api/* → backend:8080)
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
# SSH Target Server
SSH_HOST=your.target.server.ip
SSH_PORT=22
SSH_USER=root
SSH_PASSWORD=your_secure_password

# PostgreSQL
POSTGRES_PASSWORD=your_db_password
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
