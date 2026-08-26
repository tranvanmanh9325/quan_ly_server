# Mini Server Dashboard — Sci-Fi Cyberpunk Edition

[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-4.1.0-6DB33F?style=for-the-badge&logo=springboot&logoColor=white)](https://spring.io/projects/spring-boot)
[![Java](https://img.shields.io/badge/Java-21-ED8B00?style=for-the-badge&logo=openjdk&logoColor=white)](https://www.oracle.com/java/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20V2-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](./LICENSE)

> **A modern, self-hosted, real-time Linux server monitoring & autonomous management ecosystem featuring a futuristic Cyberpunk / Sci-Fi HUD interface.**  
> Connect securely to any remote Linux host over SSH with **zero agent installation** on the target machine. Monitor system metrics, processes, services, containers, files, logs, and interact via an **autonomous AI Assistant ("Tiểu Bảo Bảo")** across Telegram and Facebook Messenger E2EE.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Screenshots / Demo](#-screenshots--demo)
- [Key Features](#-key-features)
  - [Autonomous AI Assistant ("Tiểu Bảo Bảo")](#1-autonomous-ai-assistant-tiểu-bảo-bảo)
  - [System Overview Dashboard (`/`)](#2-system-overview-dashboard-)
  - [3D Interactive Globe Map (`/map`)](#3-3d-interactive-globe-map-map)
  - [Process Explorer (`/processes`)](#4-process-explorer-processes)
  - [Services & Docker Runtime Center (`/services`)](#5-services--docker-runtime-center-services)
  - [Container Management (`/containers`)](#6-container-management-containers)
  - [Remote File Manager (`/files`)](#7-remote-file-manager-files)
  - [Interactive Web SSH Terminal (`/terminal`)](#8-interactive-web-ssh-terminal-terminal)
  - [Security & Network Inspector (`/security`)](#9-security--network-inspector-security)
  - [Control Center & Preferences (`/settings`)](#10-control-center--preferences-settings)
  - [Futuristic Sci-Fi HUD Interaction Layer](#11-futuristic-sci-fi-hud-interaction-layer)
- [System Architecture](#-system-architecture)
- [Microservices & Tech Stack](#-microservices--tech-stack)
- [Project Directory Structure](#-project-directory-structure)
- [API Reference](#-api-reference)
- [Getting Started & Installation](#-getting-started--installation)
  - [Prerequisites](#prerequisites)
  - [1. Clone & Configure Environment](#1-clone--configure-environment)
  - [2. Deploy with Docker Compose (Recommended)](#2-deploy-with-docker-compose-recommended)
  - [3. Local Development (Hot Reload)](#3-local-development-hot-reload)
  - [4. Running Unit Tests](#4-running-unit-tests)
- [Documentation Index](#-documentation-index)
- [Contributing](#-contributing)
- [Security Policy](#-security-policy)
- [License](#-license)

---

## 🌟 Overview

**Mini Server Dashboard** delivers a complete single-pane-of-glass operational suite designed for sysadmins, DevOps engineers, and self-hosters who demand both deep operational control and top-tier aesthetic excellence.

### Core Philosophy

1. **Zero Target Footprint (Agentless):** No daemon, agent, or extra process needs to be installed on target Linux servers. The backend connects via SSH (`JSch` / `AsyncSSH`) and collects real-time telemetry through standard Linux utilities (`top`, `free`, `df`, `sensors`, `ps`, `systemctl`, `docker`, `ss`, `journalctl`).
2. **Autonomous Hybrid AI Agent ("Tiểu Bảo Bảo"):** Powered by a Multi-Provider LLM Pool (Groq + OpenRouter) that operates 24/7. It diagnoses server alerts, executes sysadmin tasks over SSH via tool calling, and bridges notifications/conversations through Telegram and Facebook Messenger End-to-End Encrypted (E2EE) chats.
3. **Immersive Cyberpunk Sci-Fi HUD:** Replaces mundane flat dashboards with a dynamic, neon-lit HUD interface featuring SVG crosshair cursors, audio-synthesized tactile feedback, canvas shockwaves, and a 3D orthographic globe.

---

## 📸 Screenshots / Demo

### 1. System Overview Dashboard (`/`)
Real-time KPI metric cards, CPU & RAM donut gauges, multi-core temperature sensors, disk partition usage, and fan HUD.
![Dashboard Overview](./docs/assets/dashboard-overview.png)

### 2. Process Explorer (`/processes`)
Live Linux process monitor with column sorting, CPU/Memory threshold filters, process termination modal, and 1-click CSV export.
![Process Explorer](./docs/assets/dashboard-processes.png)

### 3. Services & Docker Runtime Center (`/services`)
Start/stop/restart systemd units, inspect Docker containers, view live streaming container logs, and monitor scheduled system timers.
![Services & Docker](./docs/assets/dashboard-services.png)

### 4. Interactive Web SSH Terminal Console (`/terminal`)
Embedded web terminal with command history, security sandbox, and 1-click Quick Command Macro Chips.
![Terminal Console](./docs/assets/dashboard-terminal.png)

### 5. Control Center & Settings (`/settings`)
Configure critical alert threshold sliders, global refresh speeds, Telegram/Facebook AI agent preferences, and Sci-Fi visual effects.
![Settings](./docs/assets/dashboard-settings.png)

---

## 🚀 Key Features

### 1. Autonomous AI Assistant ("Tiểu Bảo Bảo")

- **Pyramid Principle / BLUF Thinking Architecture:**
  - **Bottom Line Up Front (BLUF):** The very first line always delivers a direct, decisive conclusion (Executive Summary).
  - **Structured Verified Breakdown:** Organizes evidence into high-contrast Visual Cards (`📌`, `🕒`, `✅`, `🔍`).
  - **Actionable Insights:** Provides clear, concise root-cause explanations and practical next steps.
- **Telegram Native Formatter Engine (`TelegramFormatter`):**
  - **Markdown Table-to-Card Transformer:** Converts raw Markdown pipe tables (`|---|---|`) into elegant, responsive cards for mobile and desktop screens.
  - **HTML Sanitization & Tag Balancing:** Converts Markdown to safe Telegram HTML (`<b>`, `<i>`, `<code>`, `<pre><code>`, `<blockquote>`, `<s>`) while automatically balancing tags.
  - **Vietnamese Typography & Spelling Auto-Normalizer:** Automatically fixes common LLM slips, normalizes timestamps (`06:00`), converts Unicode non-breaking hyphens, and filters stray multilingual tokens.
- **Anti-Loop Circuit Breaker & Context Compactor:**
  - **Active Turn Context Compactor:** Dynamically compacts older tool outputs in multi-step chains, capping payload under 3,500 characters (~900 tokens) and **eliminating Groq `HTTP 413 Payload Too Large` errors**.
  - **Loop Detection & Synthesis Circuit Breaker:** Detects duplicate command calls and forces `tool_choice="none"` at iteration $\ge 4$ to guarantee a prompt, structured answer.
  - **Graceful Final Synthesis Fallback:** Triggers a synthesis pass instead of failing with robotic error messages.
- **Ground Truth Physical Location Metadata:**
  - Explicitly configured on-premise physical location: **Định Công, Hoàng Mai, Hà Nội, Việt Nam** (FPT Telecom, LAN: `192.168.0.100`).
  - Distinguishes physical hardware location from ISP BGP dynamic IP GeoIP routing.
- **9Router Multi-Provider Key Pool Engine:**
  - **Tier 1 (Groq Pool):** Round-robin rotation across multiple keys (`openai/gpt-oss-120b`, `llama-3.1-8b-instant`) with automatic 60s cooldown on 429 rate limits.
  - **Tier 2 (OpenRouter Pool):** Automatic zero-downtime failover (`nvidia/nemotron-3-super-120b-a12b:free`).
  - **Real-Time Token Compressor (RTK):** Compacts logs/JSON payloads before LLM ingestion, saving 40–85% token volume with PostgreSQL stats persistence.
  - **OpenAI-Compatible Gateway:** Exposes `/v1/chat/completions` and `/v1/models` for external integrations.
- **Facebook Messenger E2EE Automation:**
  - Headless Chromium (Playwright) running in an isolated container with persistent session storage (`browser_data`).
  - **Automated 6-Digit PIN Recovery:** Automatically unlocks E2EE security challenge screens to decrypt chats.
  - **Absence Auto-Responder & Intelligent Unsend:** Sends absence notices when the owner is away, and automatically revokes/unsends ("Thu hồi với mọi người") the message once the owner replies.
  - **noVNC Visual Console (Port 6080):** Embedded GUI stream for live browser inspection and manual intervention.
- **TikTok Automation & Long-Term Memory:**
  - **Daily Streak Keeper:** Automated check-ins and DM responses.
  - **Self-Learning Brain (`AgentMemoryService`):** Long-term memory storage in PostgreSQL (`ai_chat_memories`, `ai_agent_lessons`, `ai_agent_preferences`, `ai_scheduled_tasks`).

### 2. System Overview Dashboard (`/`)
- **Live KPI Telemetry:** CPU utilization, RAM breakdown, disk partitions, Network TX/RX throughput, Load Average (1m / 5m / 15m).
- **Hardware Health:** Multi-sensor CPU temperature readings, system voltages, fan speeds.
- **CRITICAL ALERT Warning System:** Pulsing visual alerts and notification triggers on threshold breach.

### 3. 3D Interactive Globe Map (`/map`)
- **Orthographic 3D Globe:** Rendered using D3-geo and TopoJSON with smooth drag-to-rotate interaction.
- **Server Geolocation:** Pinpoints server location with glowing neon pins and animated sonar pulse waves.

### 4. Process Explorer (`/processes`)
- Real-time Linux process table with dynamic sorting by CPU%, Memory MB, PID, and Command Name.
- Quick filter tabs: `ALL`, `HIGH CPU (>20%)`, `HIGH MEM (>100MB)`.
- Safe process termination modal with PID verification and instant CSV export.

### 5. Services & Docker Runtime Center (`/services`)
- **Systemd Service Manager:** Live status badges with 1-click Start / Stop / Restart actions.
- **Systemd Timers:** Tracks scheduled maintenance jobs (`apt-daily.timer`, `apt-daily-upgrade.timer`).
- **Installed Runtimes:** Auto-detects Docker, Node.js, Java, Python, Nginx, PostgreSQL, Redis, UFW.

### 6. Container Management (`/containers`)
- Complete Docker container overview with live container states and port mappings.
- Container lifecycle controls: start, stop, restart, and inspect.
- Real-time container log streaming modal (`docker logs --tail`).

### 7. Remote File Manager (`/files`)
- Full-featured SSH filesystem browser (navigate directories, inspect files, create, rename, delete items).
- Built-in syntax-highlighted code and configuration file viewer.

### 8. Interactive Web SSH Terminal (`/terminal`)
- Browser-based terminal emulator (`root@server:~#`) with command history.
- Quick command macro chips (`uname -a`, `df -h`, `docker ps`, `ss -tulpn`).
- Server-side security sandbox preventing destructive commands (`rm -rf /`, `mkfs`, `reboot`).

### 9. Security & Network Inspector (`/security`)
- **Listening Ports:** Comprehensive TCP / UDP socket scan mapped to process names and PIDs (`ss -tulpn`).
- **Active SSH Sessions:** Real-time user login monitoring via `who`.
- **Colorized System Log Viewer:** Automatic severity parsing (`ERROR`/`DENIED` → Red, `WARN` → Yellow, `INFO` → Green).

### 10. Control Center & Preferences (`/settings`)
- Custom threshold sliders for CPU, Memory, and Disk alert triggers.
- Per-session polling frequency adjustments and Sci-Fi visual toggles.
- Telegram & Facebook AI integration controls.

---

## 🏗 System Architecture

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       Docker Network (bridge)                                         │
│                                                                                                       │
│   ┌───────────────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                                       Frontend (Nginx)                                        │   │
│   │                                         React 19 SPA                                          │   │
│   │                                    Host Port: 5173 (Nginx :80)                                │   │
│   └───────▲──────────────────────▲──────────────────────▲──────────────────────▲──────────────────┘   │
│           │                      │                      │                      │                      │
│           │ /api/auth/*          │ /api/metrics/*       │ /api/files/*         │ /api/facebook/*      │
│           │ (JWT Login / Verify) │ (Telemetry / Stream) │ (SFTP File Ops)      │ /api/tiktok/*        │
│           │                      │                      │                      │ /api/ai/* , /v1/*    │
│           │                      │                      │                      │ /fb-vnc/* (WebSocket)│
│           │ (REST Request/Reply) │ (REST Request/Reply) │ (REST Request/Reply) │ (Duplex Stream/REST) │
│           ▼                      ▼                      ▼                      ▼                      │
│   ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────────────────┐   │
│   │ Auth Service │       │Metrics Service       │ File Service │       │     AI Agent Service     │   │
│   │ Spring Boot  │       │ Spring Boot  │       │ Spring Boot  │       │      FastAPI (8084)      │   │
│   │ (Port 8081)  │       │ (Port 8082)  │       │ (Port 8083)  │       │    noVNC GUI (Port 6080) │   │
│   └───────▲──────┘       └───────▲──────┘       └───────▲──────┘       └───────▲──────────▲───────┘   │
│           │                      │                      │                      │          │           │
│           │ (User / Auth R/W)    │ (Configs / Logs R/W) │ (SFTP Navigation)    │ (State)  │           │
│           ▼                      ▼                      │                      ▼          │           │
│   ┌─────────────────────────────────────┐               │              ┌───────────────┐  │           │
│   │            PostgreSQL 17            │               │              │ Playwright    │  │           │
│   │        (Database Container)         │               │              │ Chromium Head │  │           │
│   │     Port 5432/tcp (Bi-directional)  │               │              │ (E2EE Session)│  │           │
│   └─────────────────────────────────────┘               │              └───────▲───────┘  │           │
│                                                         │                      │          │           │
└─────────────────────────────────────────────────────────┼──────────────────────┼──────────┼───────────┘
         ▲                                                ▲                      │          ▲
         │ (JSch SSH Persistent Session)                  │ (JSch SFTP Channel)  │          │ (AsyncSSH)
         │ [Commands ──▶ / ◀── Metrics Telemetry]        │ [Read/Write Stream]  │          │ [SSH Tools]
         ▼                                                ▼                      │          ▼
  ┌───────────────────────────────────────────────────────────────────┐          │ ┌────────────────────┐
  │                        Remote Linux Server                        │          │ │  LLM Key Pools     │
  │                       (Managed Target Host)                       │          │ │ ────────────────── │
  │    Standard Linux CLI: top, free, df, sensors, ps, systemctl,     │          │ │ 1. Groq API Pool   │
  │    docker, ss, journalctl, ufw (Zero target agent footprint)      │          │ │ 2. OpenRouter Pool │
  │                   Port 22/tcp (Full Duplex)                       │          │ └─────────▲──────────┘
  └───────────────────────────────────────────────────────────────────┘          │           │
                                                                                 │           │ (Prompt Context ──▶)
                                                                                 │           │ (◀── Inference Stream)
                                                                                 ▼           ▼
                                      ┌─────────────────────────────────────────────────────────────────┐
                                      │             External Messaging Integrations (2-Way)             │
                                      │ ─────────────────────────────────────────────────────────────── │
                                      │ • Telegram Bot API (Inbound Polling ◄──► Outbound AI Responses) │
                                      │ • Facebook Messenger E2EE (Scan Inbox ◄──► Auto-Reply & Unsend) │
                                      │ • TikTok Automation (DM Scan ◄──► Streak Keeper Auto-Reply)     │
                                      └─────────────────────────────────────────────────────────────────┘
```

---

## 🛠 Microservices & Tech Stack

| Component | Framework / Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Frontend** | React + Vite + Tailwind/CSS | React 19 / Vite 8 | Cyberpunk Sci-Fi SPA & Visualization |
| **Auth Service** | Spring Boot + Spring Security | 4.1.0 (Java 21) | JWT Authentication, User Verification |
| **Metrics Service** | Spring Boot + JSch SSH | 4.1.0 (Java 21) | Real-time SSH Telemetry, System Control |
| **File Service** | Spring Boot + JSch SFTP | 4.1.0 (Java 21) | Remote File Navigation & Operations |
| **AI Agent Service** | FastAPI + Playwright + AsyncSSH | Python 3.11 | Telegram Bot & Facebook E2EE AI Agent |
| **Database** | PostgreSQL Alpine | 17 | User Auth, Configs & E2EE Thread State |
| **Visual Bridge** | Xvfb + x11vnc + noVNC | — | Web-based GUI stream for Headless Browser |
| **Reverse Proxy** | Nginx Alpine | latest | Static Asset Serving & `/api/*` Routing |

---

## 📁 Project Directory Structure

```text
quan_ly_server/
├── .agents/                              # AI Agent workflows & operational guides
├── .env.example                          # Safe environment configuration template
├── docker-compose.yml                    # Multi-container orchestration specification
├── docs/                                 # Complete technical documentation suite
│   ├── README.md                         # Documentation index
│   ├── architecture.md                   # System topology & communication patterns
│   ├── api-reference.md                  # REST API & Gateway specifications
│   ├── backend-internals.md              # Spring Boot & FastAPI architectural details
│   ├── database-and-auth.md              # PostgreSQL 17 schema & JWT auth lifecycle
│   ├── deployment.md                     # Production deployment & hardening guide
│   ├── frontend-internals.md             # React 19, D3 Globe & Sci-Fi HUD engine
│   ├── security.md                       # Security model, sandboxing & credential policies
│   ├── system-automation.md              # Background schedulers, scanners & timers
│   ├── telegram-ai-agent.md              # Autonomous AI Agent, 9Router & E2EE guide
│   └── troubleshooting.md                # Diagnostic runbooks & recovery handbook
├── frontend/                             # React 19 + Vite 8 SPA
│   ├── src/pages/                        # Dashboard, Processes, Services, Containers, Files, etc.
│   ├── src/components/                   # SciFi HUD components, SciFiIcons, Terminal, etc.
│   └── nginx.conf                        # Nginx reverse proxy configuration
├── services/
│   ├── auth-service/                     # Spring Boot JWT authentication microservice
│   ├── metrics-service/                  # Spring Boot JSch telemetry microservice
│   ├── file-service/                     # Spring Boot SFTP file operations microservice
│   └── ai-agent-service/                 # FastAPI Python AI Agent & 9Router service
│       ├── app/core/                     # LLM Router (RTK), Telegram Formatter, SSH client
│       ├── app/routers/                  # Health, Facebook, TikTok, OpenAI Gateway
│       └── app/services/                 # AiAgent, TelegramBot, FacebookService, TikTokService, Memory
└── db/                                   # Database migration scripts & PostgreSQL config
```

---

## 🚀 Getting Started & Installation

### Prerequisites

- **Docker & Docker Compose V2** (Installed on production host)
- **Target Linux Server** with SSH access (OpenSSH server enabled)
- Optional: **Groq API Key** / **OpenRouter API Key** (for AI Agent features)
- Optional: **Telegram Bot Token** (for Telegram Bot automation)

### 1. Clone & Configure Environment

```bash
git clone https://github.com/tranvanmanh9325/quan_ly_server.git
cd quan_ly_server

# Copy environment template
cp .env.example .env

# Edit environment variables
nano .env
```

Key environment settings:
```dotenv
SSH_HOST=192.168.0.100
SSH_PORT=22
SSH_USER=kirito
SSH_PASSWORD=your_ssh_password

# Ground truth physical server metadata
SERVER_PHYSICAL_LOCATION="Định Công, Hoàng Mai, Hà Nội, Việt Nam"
SERVER_ISP="FPT Telecom"
SERVER_OWNER="Trần Văn Mạnh (kirito)"

# Telegram & AI Agent Key Pool
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
GROQ_API_KEY=gsk_your_groq_key
OPENROUTER_API_KEY=sk-or-v1-your_openrouter_key
```

### 2. Deploy with Docker Compose (Recommended)

```bash
# Build and start all 6 containers in detached mode
docker compose up -d --build

# Check status of all microservices
docker compose ps
```

Once running, access the dashboard at:
- **Web Dashboard:** `http://<server-ip>:5173`
- **noVNC Visual Console:** `http://<server-ip>:6080/vnc.html`

### 3. Local Development (Hot Reload)

```bash
# Frontend (Vite hot-reload)
cd frontend && npm install && npm run dev

# AI Agent Service (Python FastAPI)
cd services/ai-agent-service
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8084 --reload
```

### 4. Running Unit Tests

```bash
# Run AI Agent & Telegram Formatter unit tests inside container
docker exec dashboard_ai_agent python -m unittest discover -v -s /app/tests

# Run frontend tests
cd frontend && npm test
```

---

## 📚 Documentation Index

| Topic | Document |
| --- | --- |
| **System Architecture** | [docs/architecture.md](./docs/architecture.md) |
| **Complete API Reference** | [docs/api-reference.md](./docs/api-reference.md) |
| **AI Agent & 9Router Ecosystem** | [docs/telegram-ai-agent.md](./docs/telegram-ai-agent.md) |
| **Backend Microservices Internals** | [docs/backend-internals.md](./docs/backend-internals.md) |
| **Database & JWT Authentication** | [docs/database-and-auth.md](./docs/database-and-auth.md) |
| **Frontend & HUD Engine** | [docs/frontend-internals.md](./docs/frontend-internals.md) |
| **System Automation & Schedulers** | [docs/system-automation.md](./docs/system-automation.md) |
| **Production Deployment Guide** | [docs/deployment.md](./docs/deployment.md) |
| **Security Hardening & Sandboxing** | [docs/security.md](./docs/security.md) |
| **Troubleshooting & Diagnostics** | [docs/troubleshooting.md](./docs/troubleshooting.md) |

---

## 🛡 Security Policy

Please review [SECURITY.md](./SECURITY.md) for vulnerability disclosure procedures and security guarantees.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](./LICENSE) for details.
