# Architecture

A detailed walkthrough of how the Mini Server Dashboard is structured, how data flows through the system, and the rationale behind key design decisions.

---

## High-Level Overview

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

## Component Breakdown

### 1. Microservices Topology

| Service | Port | Primary Responsibility | Key Technologies |
| --- | --- | --- | --- |
| **Frontend** | `5173:80` | React 19 SPA, Cyberpunk Sci-Fi UI, custom SVG icons (`SciFiIcons.jsx`), Nginx reverse proxy | React 19, Vite 8, Recharts, Nginx Alpine |
| **Metrics Service** | `8082` | System telemetry, JSch SSH persistent tunnel, `executeSudoCommand`, alert threshold engine | Spring Boot 4.1.0, JSch 2.28.5, Spring Data JPA |
| **Auth Service** | `8081` | Authentication, JWT token issuance, user credential validation | Spring Boot 4.1.0, Spring Security, JJWT |
| **File Service** | `8083` | Remote file system browsing, SFTP file inspection & manipulation | Spring Boot 4.1.0, JSch SFTP |
| **AI Agent Service** | `8084` / `6080` | Telegram Bot AI Assistant ("Tiểu Bảo Bảo"), Facebook E2EE Automation, TikTok Automation, 9Router Multi-LLM Pool, noVNC live stream | FastAPI, Python 3.11, Playwright, AsyncSSH, noVNC |
| **Database (DB)** | `5432` | Relational storage for users, configs, Telegram history, Facebook E2EE thread states, RTK stats, AI memories | PostgreSQL 17 Alpine |

---

### 2. Autonomous AI Agent Architecture ("Tiểu Bảo Bảo")

The `ai-agent-service` is an autonomous operational microservice with:
1. **Pyramid Principle / BLUF Reasoning:** Structured responses starting with a direct conclusion on line 1.
2. **Telegram Native Formatter:** Converts Markdown tables to visual cards and auto-balances HTML.
3. **Active Context Compactor & Loop Breaker:** Prevents Groq `HTTP 413 Payload Too Large` and loop deadlocks.
4. **Ground Truth Physical Location:** Configured with physical coordinates at **Định Công, Hoàng Mai, Hà Nội**.
5. **9Router Multi-Provider Key Pool:** Round-robin rotation over Groq + OpenRouter with RTK token compression.

---

### 3. SSH Layer — `SshService` & `AsyncSSH`

The ecosystem uses two distinct, optimized SSH patterns:

1. **Spring Boot `SshService` (Java / JSch):**
   - Maintains **one shared `JSch` session** for the entire Spring Boot process lifetime.
   - Eliminates per-request handshake overhead (~200–800 ms $\rightarrow$ <10 ms per command).
   - Exponential backoff with three delays `[250, 500, 1000]` ms for transient Ngrok/network recovery.
2. **AI Agent `SshClient` (Python / AsyncSSH):**
   - Asynchronous non-blocking SSH command execution for AI tool calls (`run_command`).
   - Timeout enforcement (15 seconds) to prevent hanging commands.

---

### 4. Data Flow — End to End

```text
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

**Visibility API optimisation:** When `document.visibilityState === 'hidden'`, polling is suspended entirely.

---

## Key Design Trade-offs

| Decision | Choice | Rationale |
| --- | --- | --- |
| Parsing location | Frontend (`parsers.js`) | Independently testable; no backend rebuild when output format changes |
| SSH session lifecycle | Persistent + shared | Eliminates per-request handshake overhead (~200–800 ms) |
| StrictHostKeyChecking | Disabled | Required for Ngrok tunnels (host key changes on every reconnect) |
| Multi-Provider AI Routing | 9Router Key Pool | Eliminates single point of failure and bypasses rate limits |
| E2EE Decryption Engine | Headless Playwright | Interacts natively with encrypted DOM and unlocks 6-digit PIN |
| Long-term Memory Storage | PostgreSQL JSONB | Preserves learned rules and preferences across restarts |
| Polling strategy | `setTimeout` chains | Allows dynamic interval adjustment and prevents overlapping fetches |
