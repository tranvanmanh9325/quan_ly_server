# 🖥️ Mini Server Dashboard (Sci-Fi Cyberpunk Edition)

**A self-hosted, real-time server monitoring & management dashboard.**
Connect to any remote Linux host over SSH and control live system metrics, processes, services, containers, and logs through an ultra-sleek, Cyberpunk/Sci-Fi HUD web interface.

[![CI/CD](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/tranvanmanh9325/quan_ly_server/actions/workflows/deploy.yml)
![Java](https://img.shields.io/badge/Java-21-orange?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-3.4.1-6DB33F?logo=springboot&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-Compose_V2-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## Overview

Mini Server Dashboard provides a single-pane-of-glass operational center for remote Linux servers without requiring agent installation on target hosts. The Spring Boot backend maintains a **persistent SSH session** (via JSch with root-level command elevation) and executes standard Linux commands (`top`, `free`, `df`, `sensors`, `ps`, `systemctl`, `docker ps`, `ss`, `journalctl`, etc.) to collect metrics. The React frontend renders live charts, gauges, logs, and interactive control panels with custom vector SVG icons and glassmorphism styling.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Key Features](#key-features)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Local Development Setup](#local-development-setup)
- [License](#license)

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                  Docker Network  (bridge)                │
│                                                         │
│  ┌──────────────────┐   /api/*   ┌───────────────────┐  │
│  │    Frontend      │ ─────────▶ │      Backend      │  │
│  │  React + Nginx   │            │  Spring Boot 3.4  │  │
│  │   Port 5173:80   │            │    Port 8080      │  │
│  └──────────────────┘            │  JSch SSH Client  │  │
│                                  └────────┬──────────┘  │
└───────────────────────────────────────────│─────────────┘
                                            │ SSH (Port 22 / Ngrok TCP)
                                            ▼
                                  ┌──────────────────┐
                                  │  Remote Linux    │
                                  │  Server / VPS    │
                                  └──────────────────┘
```

**Request flow:**

1. The browser loads the React SPA served by **Nginx**.
2. `/api/*` XHR requests are reverse-proxied by Nginx to **Spring Boot**.
3. Spring Boot forwards requests as shell commands over the **persistent SSH session** (with `sudo -S` elevation where needed).
4. Output is returned as JSON; parsing is handled in **`frontend/src/utils/parsers.js`**.

---

## Tech Stack

| Layer | Technology | Version |
| --- | --- | --- |
| Frontend Framework | React | 19 |
| Frontend Build Tool | Vite | 8 |
| Charts | Recharts | 3 |
| HTTP Client | Axios | 1 |
| Icons | Custom-Designed Sci-Fi SVG Icons (`SciFiIcons.jsx`) | Custom |
| Frontend Server | Nginx (Alpine) | latest |
| Backend Framework | Spring Boot | 3.4.1 |
| Backend Language | Java | 21 |
| Database | PostgreSQL | 16 |
| SSH Client | JSch (mwiede fork) | 2.27.9 |
| Containerization | Docker + Compose | V2 |
| CI/CD | GitHub Actions | — |

---

## Key Features

### 🖥️ Sci-Fi Top Operational Header Bar

- **System Health Status Badge**: Real-time `ONLINE / HEALTHY` indicator; automatically triggers a pulsing red `CRITICAL ALERT` banner when CPU > 85%, RAM > 90%, or Disk > 90%.
- **Live Node & Time**: Displays server hostname, OS kernel info, and live server clock.
- **Dynamic Auto-Refresh Controller**: Toggle metrics polling frequency between `5s (Fast)`, `10s (Normal)`, `15s (Slow)`, `30s (Eco)`, or `PAUSED`.

### 💻 Web Command Terminal Console (`>_`)

- Embedded web-based SSH command console (`root@server:~#`) for executing server diagnostic commands (`uname -a`, `free -m`, `df -h`, `docker ps`, `uptime`, `whoami`, etc.).
- **Command History Navigation**: Navigate previous commands seamlessly using **Up / Down arrow keys** (`↑` / `↓`).
- **Quick Command Chips**: 1-click execution for standard sysadmin diagnostics (`uname -a`, `free -h`, `df -h`, `docker ps`, `ss -tulpn`).
- **Output Management**: Copy full output to clipboard or clear console with 1-click.
- Built-in **Security Sandbox** preventing destructive commands (`rm -rf`, `mkfs`, `reboot`, `shutdown`, etc.).

### 🛡️ 4-Panel Services & Runtime Center (`/services`)

- **System Services (Systemd)**: List and control 1-click **Start / Stop / Restart** for all host systemd services.
- **Docker Containers & Log Viewer**: View 100% of containers (`Up` & `Exited`), published port mappings, 1-click **Start / Stop / Restart** controls, and an interactive **Sci-Fi Docker Container Log Viewer Modal** (`docker logs --tail`).
- **Systemd Timers & Scheduled Jobs**: Monitor active countdown timers (`certbot`, `logrotate`, `apt-daily`...) and next execution timestamps.
- **Host Runtimes & Server Daemons**: Detect installed programming runtimes (Docker, Node.js, Java, Python) and application servers (Nginx, PostgreSQL, Redis, UFW Firewall).

### 📈 Process Explorer & Smart Filters (`/processes`)

- **Smart Column Sorting**: Sort processes by **Highest CPU %**, **Highest Memory MB**, **PID**, or **Name**.
- **Quick Filters**: Instant tabs for `ALL`, `HIGH CPU (>20%)`, `HIGH MEM (>100MB)`.
- **Sci-Fi Confirmation Modal**: Glassmorphic confirmation modal with warning alerts before force-killing processes.
- **CSV Data Export**: 1-click `EXPORT CSV` button to download filtered process tables.

### 🔒 Security & Logs (`/security`)

- **Listening Ports**: Comprehensive TCP & UDP listening sockets scanning with process ID/name mapping (`ss -tulpn`).
- **Active SSH Sessions**: Real-time user login tracking (`who`).
- **Log Level Syntax Highlighting**: Colorized log viewer for `ERROR` / `DENIED` (Pink), `WARN` (Yellow), and `INFO` (Green).
- **Log Search & Export**: Filter log entries by search keywords or level, and export logs to `.log` text files (`EXPORT LOGS`).

---

## Project Structure

```text
quan_ly_server/
├── .env                                  # Consolidated root environment file (SSH & DB credentials)
├── .gitignore                            # Ignores .env and build artifacts
├── docker-compose.yml                    # Orchestrates backend, frontend & db containers
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
│   │       └── MetricCollectorJob.java   # Scheduled 1-min history data recorder
│   ├── src/test/java/                    # JUnit 5 & Mockito Unit Tests
│   ├── Dockerfile
│   └── pom.xml
│
└── frontend/                             # React + Vite SPA
    ├── src/
    │   ├── App.jsx                       # Root router & dynamic polling engine
    │   ├── components/
    │   │   ├── Layout.jsx                # Sci-Fi Top Header Bar & Sidebar
    │   │   └── SciFiIcons.jsx            # Custom vector SVG icons library
    │   ├── pages/
    │   │   ├── DashboardPage.jsx         # Overview charts, Load Avg card & Fan HUD
    │   │   ├── ProcessesPage.jsx         # Process Explorer & CSV export
    │   │   ├── ServicesPage.jsx          # Services grid & Docker Container Log Viewer
    │   │   └── SecurityPage.jsx         # Ports, SSH sessions, Log highlighter & Web Terminal
    │   └── utils/
    │       ├── parsers.js                # Shell output string parsers
    │       └── parsers.test.js           # Vitest unit tests for parsers
    ├── nginx.conf                        # Reverse proxy config (/api/* → backend:8080)
    ├── vite.config.js                    # Rolldown / ManualChunks vendor code splitting
    └── Dockerfile
```

---

## API Reference

All endpoints return raw shell output wrapped in a JSON envelope (`GET /api/metrics/<endpoint>`):

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/metrics/cpu` | GET | Raw top CPU usage data |
| `/api/metrics/ram` | GET | Memory breakdown via `free -m` |
| `/api/metrics/disk` | GET | Partition usage via `df -h` |
| `/api/metrics/network` | GET | Interface deltas via `/proc/net/dev` |
| `/api/metrics/processes` | GET | Process list via `ps -eo` |
| `/api/metrics/services` | GET | Systemd unit statuses |
| `/api/metrics/timers` | GET | Systemd timer schedules |
| `/api/metrics/runtimes` | GET | Host runtimes and daemons health |
| `/api/metrics/ports` | GET | Listening sockets via `ss -tulpn` |
| `/api/metrics/docker/logs` | GET | Stream/tail Docker container logs (`containerId`, `lines`) |
| `/api/metrics/services/control` | POST | Control systemd service (`action=start\|stop\|restart`) |
| `/api/metrics/docker/control` | POST | Control Docker container (`action=start\|stop\|restart`) |
| `/api/metrics/kill-process` | POST | Kill process by PID (`pid=X`) |
| `/api/metrics/execute-command` | POST | Execute safe command in terminal console |

---

## Local Development Setup

### 1. Root Environment Configuration

Create `.env` in the root folder (`quan_ly_server/.env`):

```dotenv
SSH_HOST=your.target.server.ip
SSH_PORT=22
SSH_USER=ubuntu
SSH_PASSWORD=your_secure_password

POSTGRES_DB=dashboard_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres_password
```

### 2. Run with Docker Compose

```bash
# Build and start all containers
docker compose up -d --build

# View container logs
docker compose logs -f
```

Access the Web UI at **`http://localhost:5173`** (or backend Actuator at `http://localhost:8080/actuator/health`).

---

## License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for details.
