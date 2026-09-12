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
> Connect securely to any remote Linux host over SSH with **zero agent installation** on the target machine. Monitor system metrics, processes, services, containers, files, logs, and interact via an **autonomous Neuromorphic AI Assistant ("Tiểu Bảo Bảo")** featuring biological neurochemistry, multimodal video/audio analysis, regional Vietnamese dialect understanding, and 32GB Virtual Memory Swap across Telegram and Facebook Messenger E2EE.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [System Topology & High-Level Architecture](#-system-topology--high-level-architecture)
- [Screenshots / Demo](#-screenshots--demo)
- [Key Features & Visual Workflows](#-key-features--visual-workflows)
- [End-to-End Operational Lifecycle](#-end-to-end-operational-lifecycle)
- [Microservices & Tech Stack](#-microservices--tech-stack)
- [Project Directory Structure](#-project-directory-structure)
- [Getting Started & Installation](#-getting-started--installation)
  - [Prerequisites](#prerequisites)
  - [1. Clone & Configure Environment](#1-clone--configure-environment)
  - [2. Deploy with Docker Compose](#2-deploy-with-docker-compose-recommended)
  - [3. Local Development (Hot Reload)](#3-local-development-hot-reload)
  - [4. Running Unit Tests](#4-running-unit-tests)
- [Documentation Index](#-documentation-index)
- [Author & Core Architecture](#-author--core-architecture)
- [Contributors & Community](#-contributors--community)
- [License](#-license)

---

## 🌟 Overview

**Mini Server Dashboard** delivers a complete single-pane-of-glass operational suite designed for sysadmins, DevOps engineers, and self-hosters who demand both deep operational control and top-tier aesthetic excellence.

### Core Philosophy

1. **Zero Target Footprint (Agentless):** No daemon, agent, or extra process needs to be installed on target Linux servers. The backend connects via SSH (`JSch` / `AsyncSSH`) and collects real-time telemetry through standard Linux utilities (`top`, `free`, `df`, `sensors`, `ps`, `systemctl`, `docker`, `ss`, `journalctl`).
2. **Autonomous Neuromorphic AI Agent ("Tiểu Bảo Bảo"):** Powered by an artificial cognitive architecture simulating 6 biological neurochemicals, Karl Friston Active Inference, 10,000-bit Hyperdimensional Computing on 32GB Virtual Swap, multimodal video analysis, and dual-tier LLM routing (Groq + OpenRouter) that operates 24/7 over Telegram and Facebook Messenger E2EE.
3. **Immersive Cyberpunk Sci-Fi HUD:** Replaces mundane flat dashboards with a dynamic, neon-lit HUD interface featuring interactive 3D connectome visualizers, SVG crosshair cursors, audio-synthesized tactile feedback, canvas shockwaves, and a 3D orthographic globe.

---

## 🏗 System Topology & High-Level Architecture

```mermaid
flowchart TD
    subgraph ClientLayer["🖥️ Client & Messaging Interfaces"]
        Browser["Web Browser (Cyberpunk HUD SPA) :5173"]
        TelegramUser["Telegram App (Owner Chat)"]
        FBUser["Facebook Messenger (Encrypted E2EE Chats)"]
        TikTokUser["TikTok App (DMs & Streaks)"]
    end

    subgraph DockerBridge["🐳 Docker Network Bridge (dashboard-network)"]
        Nginx["Nginx Reverse Proxy (:80 -> :5173)"]

        subgraph BackendServices["⚙️ Backend Microservices Ecosystem"]
            AuthSvc["Auth Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8081\n[JWT / BCrypt / Sessions]"]
            MetricsSvc["Metrics Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8082\n[JSch SSH Telemetry Pool]"]
            FileSvc["File Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8083\n[JSch SFTP File Operations]"]
            AgentSvc["AI Agent Service\n(FastAPI / Python 3.11)\nPort: 8084 & noVNC: 6080\n[9Router / Brain Core / Video Pipeline]"]
        end

        Database[("PostgreSQL 17 Alpine\nPort: 5432\n[Users, Configs, E2EE State, Memories, RTK Stats]")]
        SwapCortex[("🧬 32GB Virtual Memory Swap\n[10,000-bit HDC Associative Cortex]")]
    end

    subgraph Infrastructure["🌐 External AI & Managed Infrastructure"]
        GroqPool["Tier 1: Groq Multi-Key Pool\n(openai/gpt-oss-120b & whisper-turbo)"]
        OpenRouterPool["Tier 2: OpenRouter Pool\n(nvidia/nemotron-3-super-120b & gemma-vl)"]
        TargetServer["🖥️ Target Linux Host (kirito-server)\n[Zero-Agent Target / Port 22 SSH]\nPhysical Location: Định Công, Hoàng Mai, Hà Nội"]
    end

    Browser -->|HTTP / WebSocket| Nginx
    Nginx -->|/api/auth/*| AuthSvc
    Nginx -->|/api/metrics/*| MetricsSvc
    Nginx -->|/api/files/*| FileSvc
    Nginx -->|/api/facebook/*, /api/tiktok/*, /api/ai/*, /v1/*| AgentSvc
    Nginx -->|/fb-vnc/* WebSocket| AgentSvc

    TelegramUser <-->|Text, Video & Audio Long Polling| AgentSvc
    FBUser <-->|Playwright Headless Chromium + PIN Recovery| AgentSvc
    TikTokUser <-->|Playwright Automated DMs & Streaks| AgentSvc

    AuthSvc <--> Database
    MetricsSvc <--> Database
    AgentSvc <--> Database
    AgentSvc <--> SwapCortex

    MetricsSvc ==>|Persistent JSch SSH Tunnel| TargetServer
    FileSvc ==>|JSch SFTP Channel| TargetServer
    AgentSvc ==>|AsyncSSH Tool Execution| TargetServer

    AgentSvc <-->|Round-Robin & RTK Compression| GroqPool
    AgentSvc -.->|Zero-Downtime Auto Failover| OpenRouterPool
```

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

### 6. Neuromorphic Brain Core Inspection Deck (`/brain-core`)

Live Cyberpunk inspection deck visualizing 6 biological neurochemicals, 2D Russell Circumplex radar, Karl Friston Active Inference Free Energy, Global Workspace spotlight, and 3D Neural Connectome visualizer.

![Brain Core Inspection Deck](./docs/assets/dashboard-brain-core.png)

---

## 🚀 Key Features & Visual Workflows

### 1. Autonomous AI Assistant ("Tiểu Bảo Bảo")

```mermaid
flowchart LR
    UserQuery["User Message (Telegram / Messenger)"] --> BLUF["Pyramid Principle (BLUF Engine)\nLine 1: Direct Executive Summary"]
    BLUF --> ContextCompactor["Active Turn Context Compactor\nCaps payload < 3,500 chars (Anti-HTTP 413)"]
    ContextCompactor --> Router["9Router Multi-Provider Key Pool\nGroq Pool -> Auto Failover -> OpenRouter"]
    Router --> Tools{"Tool Calling Required?"}
    Tools -- Yes --> SSHExec["AsyncSSH Tool Exec\n(Linux / Docker / Systemd)"]
    SSHExec --> LoopBreaker{"Loop / Iteration >= 4?"}
    LoopBreaker -- Yes --> Synthesize["Force tool_choice='none'\nGraceful Final Synthesis"]
    LoopBreaker -- No --> ContextCompactor
    Tools -- No --> Formatter["TelegramFormatter Engine\nTables -> Cards | Balanced HTML | Spelling Fix"]
    Synthesize --> Formatter
    Formatter --> Dispatch["Deliver High-Contrast Telegram Card Response"]
```

- **Pyramid Principle / BLUF Thinking Architecture:** Direct answer on line 1, verified card breakdown in the body, concise technical insights at the end.
- **Telegram Native Formatter Engine v2.0 (`TelegramFormatter`):** Converts Markdown tables into mobile-friendly bullet cards, whitelists valid Telegram HTML tags (`<b>`, `<i>`, `<code>`, `<pre>`, `<blockquote>`, `<a>`), and auto-balances unclosed tags.
- **Anti-Loop Circuit Breaker & Context Compactor:** Dynamically compacts older tool outputs, keeping payload under 3,500 characters (~900 tokens) while allocating up to 8,000 characters for media attachments to eliminate Groq `HTTP 413 Payload Too Large` errors.
- **Neuromorphic Cognitive Brain Core (`BrainCore`):** Implements homeostatic regulation of 6 biological neurochemicals (Dopamine, Noradrenaline, Serotonin, Cortisol, Oxytocin, Endorphins), Karl Friston Active Inference (FEP), 2D Russell Circumplex emotional radar, and two-stage SWS/REM sleep memory consolidation.
- **32GB Virtual Memory Hyperdimensional Cortex (HDC):** 10,000-bit binary hypervectors mapped directly to 32GB Linux swap space via zero-copy `mmap` for instant associative concept recall in <5ms without physical RAM exhaustion.
- **Multimodal Video & Audio Intelligence Pipeline:** Dual-track parallel processing of Telegram video uploads combining mono audio extraction (Whisper STT with visual-informed vocabulary biasing) and 5-keyframe uniform sampling (Qwen-VL / Gemma-VL OCR) with Cross-Modal Discrepancy Resolution.
- **Vietnamese Regional Dialect Normalizer:** Fluent comprehension of Central Vietnam dialects (Nghệ An, Hà Tĩnh, Quảng Bình) and teencode, guarded by structured envelope bypass filters.
- **High-Speed Multi-Tier Archive Cracker:** 4-tier autonomous password recovery engine (Flash check, Context clues, PIN sweep, Dictionary) running under low-priority `nice -n 19`.
- **Ground Truth Physical Location Metadata:** Configured on-premise location: **Định Công, Hoàng Mai, Hà Nội, Việt Nam** (FPT Telecom, LAN: `192.168.0.100`).
- **Facebook Messenger E2EE Automation:** Playwright Chromium automation with automated 6-digit PIN decryption, absence auto-reply, and automatic message unsend when the owner replies.
- **TikTok Automation & Long-Term Memory:** Automated daily streak keeper, proactive appointment reminders, and PostgreSQL-backed self-learning brain (`AgentMemoryService`).

---

## 🔄 End-to-End Operational Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Owner as 👤 Anh Mạnh (Owner)
    participant TG as 📱 Telegram Bot
    participant Agent as 🤖 AI Agent (Tiểu Bảo Bảo)
    participant Router as 🔀 9Router & RTK
    participant Server as 🖥️ kirito-server (Target Host)
    participant DB as 🗄️ PostgreSQL 17

    Owner->>TG: "sáng nay đã chạy lệnh sudo apt update chưa"
    TG->>Agent: Inbound chat event
    Agent->>Router: Compress prompt & route to active Groq key
    Router-->>Agent: Returns Tool Call: run_command("systemctl list-timers apt-daily*")
    Agent->>Server: AsyncSSH: systemctl list-timers apt-daily* --no-pager
    Server-->>Agent: Raw stdout (Timer active, last run 06:00:12)
    Agent->>Router: Compacted turn context + tool output
    Router-->>Agent: Returns Final Answer (BLUF)
    Agent->>Agent: TelegramFormatter: Transform to Card layout & clean Vietnamese typography
    Agent->>DB: Save interaction & self-learning lessons
    Agent-->>TG: 🎯 KẾT QUẢ KIỂM TRA: Lệnh sudo apt update ĐÃ ĐƯỢC CHẠY sáng nay (06:00 ICT)...
    TG-->>Owner: High-contrast Card message delivered in <2.5s
```

---

## 🛠 Microservices & Tech Stack

| Component | Framework / Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Frontend** | React + Vite + Three.js + Tailwind | React 19 / Vite 8 | Cyberpunk Sci-Fi SPA, Brain Core HUD & 3D Connectome |
| **Auth Service** | Spring Boot + Spring Security | 4.1.0 (Java 21) | JWT Authentication, User Verification |
| **Metrics Service** | Spring Boot + JSch SSH | 4.1.0 (Java 21) | Real-time SSH Telemetry, System Control |
| **File Service** | Spring Boot + JSch SFTP | 4.1.0 (Java 21) | Remote File Navigation & Operations |
| **AI Agent Service** | FastAPI + Playwright + AsyncSSH | Python 3.11 | Neuromorphic AI Agent ("Tiểu Bảo Bảo"), Brain Core, Multimodal Video Pipeline |
| **Database** | PostgreSQL Alpine | 17 | User Auth, Configs, E2EE Thread State & Brain Memory |
| **Virtual Memory Swap** | Linux NVMe Swap via `mmap` | 32 GB | 10,000-bit HDC Associative Virtual Cortex Storage |
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
│   ├── neuromorphic-brain.md             # Neuromorphic Brain Core, 6 Neurotransmitters, 32GB HDC
│   ├── multimodal-video-pipeline.md      # Dual-track video/audio pipeline & cross-modal resolution
│   ├── api-reference.md                  # REST API & Gateway specifications (Brain, Metrics, Auth)
│   ├── backend-internals.md              # Spring Boot & FastAPI architectural details & tool delegation
│   ├── database-and-auth.md              # PostgreSQL 17 schema & JWT auth lifecycle
│   ├── deployment.md                     # Production deployment & hardening guide
│   ├── frontend-internals.md             # React 19, Brain Core HUD, D3 Globe & Sci-Fi HUD engine
│   ├── security.md                       # Security model, sandboxing & credential policies
│   ├── system-automation.md              # Background schedulers, cognitive heartbeat & dream engine
│   ├── telegram-ai-agent.md              # Autonomous AI Agent, 9Router, Dialect normalizer, E2EE
│   └── troubleshooting.md                # Diagnostic runbooks & recovery handbook
├── frontend/                             # React 19 + Vite 8 SPA
│   ├── src/pages/                        # Dashboard, BrainCore, Processes, Services, Terminal, etc.
│   ├── src/components/brain/             # 3D Neural Connectome, Neurotransmitter Gauges, Russell Radar
│   ├── src/components/agents/            # TikTokAgentTab, AiAgentVncModal, AgentUiControls
│   ├── src/components/                   # SciFi HUD components, SciFiIcons, Terminal, etc.
│   └── nginx.conf                        # Nginx reverse proxy configuration
├── services/
│   ├── auth-service/                     # Spring Boot JWT authentication microservice
│   ├── metrics-service/                  # Spring Boot JSch telemetry microservice
│   ├── file-service/                     # Spring Boot SFTP file operations microservice
│   └── ai-agent-service/                 # FastAPI Python AI Agent & 9Router service
│       ├── app/core/                     # Brain Core (HDC/FEP), Vietnamese Dialect, Telegram Formatter, SSH client
│       ├── app/routers/                  # Brain, Facebook, TikTok, OpenAI Gateway, Health
│       └── app/services/                 # AiAgent, AiAgentTools, VideoPipeline, MediaProcessor, ArchiveRecovery, DreamEngine
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
| **Neuromorphic Brain Core (6 Neurotransmitters & 32GB HDC)** | [docs/neuromorphic-brain.md](./docs/neuromorphic-brain.md) |
| **Multimodal Video & Audio Intelligence Pipeline** | [docs/multimodal-video-pipeline.md](./docs/multimodal-video-pipeline.md) |
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

## 👨‍💻 Author & Core Architecture

The **Kirito Server Dashboard & Autonomous AI Agent Ecosystem** was conceptualized, designed, and developed by **Trần Văn Mạnh (Kirito)**.

<div align="center">

<a href="https://github.com/tranvanmanh9325">
  <img src="https://github.com/tranvanmanh9325.png" width="120" height="120" style="border-radius: 50%; border: 3px solid #00ffcc; box-shadow: 0 0 20px rgba(0, 255, 204, 0.4);" alt="Trần Văn Mạnh (Kirito)" />
</a>

### **Trần Văn Mạnh (Kirito)**
*Project Founder, Core Maintainer & Lead Software Architect*

[![GitHub](https://img.shields.io/badge/GitHub-@tranvanmanh9325-181717?style=for-the-badge&logo=github)](https://github.com/tranvanmanh9325)
[![Email](https://img.shields.io/badge/Email-manhtrana1k45tl@gmail.com-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](mailto:manhtrana1k45tl@gmail.com)
[![HUST](https://img.shields.io/badge/Alma_Mater-Hanoi_University_of_Science_%26_Technology-B31B1B?style=for-the-badge&logo=renaissance&logoColor=white)](https://hust.edu.vn)
[![Location](https://img.shields.io/badge/Location-Hanoi_%7C_Nghe_An,_Vietnam-0099FF?style=for-the-badge&logo=google-maps&logoColor=white)](https://maps.google.com)

</div>

---

## 👥 Contributors & Community

We believe in open collaboration and recognize all community contributions following the **[All-Contributors](https://allcontributors.org/)** specification.

See the complete list of contributors, emoji keys, and recognition badges in [**`CONTRIBUTORS.md`**](./CONTRIBUTORS.md).

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="20%"><a href="https://github.com/tranvanmanh9325"><img src="https://github.com/tranvanmanh9325.png" width="90px;" alt="Trần Văn Mạnh"/><br /><sub><b>Trần Văn Mạnh (Kirito)</b></sub></a><br /><a href="#creator-tranvanmanh9325" title="Project Creator">👑</a> <a href="https://github.com/tranvanmanh9325/quan_ly_server/commits?author=tranvanmanh9325" title="Code">💻</a> <a href="#architecture-tranvanmanh9325" title="Architecture & System Design">🏗️</a> <a href="#maintenance-tranvanmanh9325" title="Maintenance & Operations">🚧</a> <a href="#ideas-tranvanmanh9325" title="Ideas & Conception">💡</a> <a href="#security-tranvanmanh9325" title="Security & Hardening">🛡️</a> <a href="https://github.com/tranvanmanh9325/quan_ly_server/commits?author=tranvanmanh9325" title="Documentation">📖</a> <a href="#design-tranvanmanh9325" title="Cyberpunk UI/UX Design">🎨</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

Interested in contributing? Check out our [**Contributing Guide (CONTRIBUTING.md)**](./CONTRIBUTING.md) to get started!

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](./LICENSE) for details.
