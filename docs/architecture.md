# Architecture & System Design

A detailed walkthrough of how the Mini Server Dashboard is structured, how data flows through the system, and the rationale behind key design decisions.

---

## 1. High-Level Microservices Topology

```mermaid
flowchart TD
    subgraph ClientZone["Client & Ingress Layer"]
        WebUser["Web Browser\n(React 19 SPA :5173)"]
        TGUser["Telegram Client\n(Owner Inbound/Outbound)"]
        FBClient["Facebook Messenger\n(E2EE Encrypted Threads)"]
        TTClient["TikTok Mobile\n(DMs & Streaks)"]
    end

    subgraph ReverseProxyZone["Reverse Proxy Layer"]
        Nginx["Nginx Reverse Proxy\nHost Port: 5173 (Internal :80)"]
    end

    subgraph ServiceMesh["Docker Bridge Network (dashboard-network)"]
        direction TB

        AuthService["Auth Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8081\n• JWT Token Issuance\n• BCrypt Credentials\n• Session Interceptor"]

        MetricsService["Metrics Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8082\n• JSch SSH Session Pool\n• Linux Telemetry\n• Sudo Actions Engine"]

        FileService["File Service\n(Spring Boot 4.1.0 / Java 21)\nPort: 8083\n• JSch SFTP Client\n• Directory Navigation\n• File Read / Write Ops"]

        AgentService["AI Agent Service\n(FastAPI / Python 3.11)\nPort: 8084 & noVNC: 6080\n• 9Router Key Pool & RTK\n• BLUF Reasoning Engine\n• Playwright Chromium\n• AgentMemoryService"]

        PostgresDB[("PostgreSQL 17 Alpine\nPort: 5432\n• users & refresh tokens\n• telegram_configs\n• facebook_known_threads\n• tiktok_streaks\n• ai_chat_memories\n• rtk_stats")]
    end

    subgraph TargetHostZone["Target Infrastructure"]
        TargetServer["Remote Linux Server (kirito-server)\nPort 22 SSH (Agentless Target)\nPhysical Location: Định Công, Hoàng Mai, Hà Nội\n• top, free, df, sensors, ps, systemctl, docker"]

        GroqCloud["Tier 1: Groq AI Cloud\n(openai/gpt-oss-120b)"]
        OpenRouterCloud["Tier 2: OpenRouter Cloud\n(nvidia/nemotron-3-super-120b)"]
    end

    WebUser -->|HTTP Requests| Nginx
    Nginx -->|/api/auth/*| AuthService
    Nginx -->|/api/metrics/*| MetricsService
    Nginx -->|/api/files/*| FileService
    Nginx -->|/api/facebook/*, /api/tiktok/*, /v1/*| AgentService
    Nginx -->|/fb-vnc/* WebSocket| AgentService

    TGUser <-->|Telegram Bot API Long-Polling| AgentService
    FBClient <-->|Playwright E2EE Automation| AgentService
    TTClient <-->|Playwright DM & Streak Loop| AgentService

    AuthService <--> PostgresDB
    MetricsService <--> PostgresDB
    AgentService <--> PostgresDB

    MetricsService ==>|Shared JSch SSH Session| TargetServer
    FileService ==>|JSch SFTP Channel| TargetServer
    AgentService ==>|AsyncSSH Tool Calls| TargetServer

    AgentService <-->|Primary Route & RTK| GroqCloud
    AgentService -.->|Automatic Failover| OpenRouterCloud
```

---

## 2. End-to-End Data Flow Sequence

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 User (Web Browser)
    participant UI as ⚛️ React 19 Frontend
    participant Nginx as 🛡️ Nginx Proxy
    participant Metrics as ☕ Metrics Service (:8082)
    participant JSch as 🔒 JSch Session Pool
    participant Host as 🖥️ Target Linux Host (:22)

    Note over User,UI: Adaptive Polling Loop (10s active / Suspended in background)
    UI->>Nginx: Promise.all([ GET /api/metrics/cpu, GET /api/metrics/ram, ... ])
    Nginx->>Metrics: Proxy pass with Bearer JWT
    Metrics->>Metrics: Validate JWT signature & claims

    Metrics->>JSch: getOrCreateSession()
    alt Session Connected & Valid
        JSch->>Host: Open ChannelExec("top -b -n 1 | grep 'Cpu(s)'")
    else Session Stale / Broken
        JSch->>Host: Reconnect with Exponential Backoff [250ms, 500ms, 1000ms]
        JSch->>Host: Open ChannelExec(...)
    end

    Host-->>JSch: Raw command stdout stream
    JSch-->>Metrics: String buffer: "%Cpu(s): 3.4 us, 1.2 sy..."
    Metrics-->>Nginx: HTTP 200 JSON { "data": "%Cpu(s): 3.4 us..." }
    Nginx-->>UI: Deliver payload
    UI->>UI: parsers.js: parseCpu() -> 4.6% Float
    UI-->>User: Render Cyberpunk Animated Gauge & Neon KPI Card
```

---

## 3. JSch SSH Session Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Uninitialized

    Uninitialized --> Connecting: First API Request / Startup

    state Connecting {
        [*] --> TCPHandshake
        TCPHandshake --> KeyExchange
        KeyExchange --> AuthenticatePasswordOrKey
        AuthenticatePasswordOrKey --> [*]
    }

    Connecting --> Connected: Success (<800ms)
    Connecting --> RetryBackoff: Failure / Network Glitch

    RetryBackoff --> Connecting: Delay (250ms -> 500ms -> 1000ms)
    RetryBackoff --> ErrorState: Exceeded 3 Retries

    state Connected {
        [*] --> IdleSession
        IdleSession --> ChannelExecOpened: executeCommand(cmd)
        ChannelExecOpened --> StreamReading: Read stdout/stderr UTF-8
        StreamReading --> IdleSession: Channel Closed (<10ms)
    }

    Connected --> Disconnected: ServerAliveInterval Timeout / Broken Pipe
    Disconnected --> Connecting: Auto Reconnection Triggered

    Connected --> Closed: Application Shutdown (@PreDestroy)
    Closed --> [*]
```

---

## 4. SSH & Automation Engine Comparison

```mermaid
flowchart LR
    subgraph JSchEngine["☕ JSch SSH Engine (Java / Spring Boot)"]
        J1["Persistent Single Session Pool"]
        J2["Low latency (<10ms execution)"]
        J3["Lightweight channel multiplexing"]
        J4["High-frequency metrics polling"]
    end

    subgraph AsyncSSHEngine["🐍 AsyncSSH Client (Python / FastAPI)"]
        A1["AsyncIO Non-blocking Event Loop"]
        A2["Independent Command Sandboxing"]
        A3["Strict 15s Per-Command Timeouts"]
        A4["AI Agent Autonomous Tool Calls"]
    end

    subgraph PlaywrightEngine["🎭 Playwright Engine (Python / Chromium)"]
        P1["Persistent Profile (browser_data)"]
        P2["Automated 6-Digit E2EE PIN Recovery"]
        P3["DOM Message Action Hover & Unsend"]
        P4["noVNC Xvfb Visual Stream (:6080)"]
    end

    JSchEngine -.->|Metrics & Files| TargetHost["Target Linux Host"]
    AsyncSSHEngine -.->|AI Diagnostics| TargetHost
    PlaywrightEngine -.->|Social Automation| SocialPlatforms["Facebook E2EE & TikTok"]
```

---

## 5. Key Architectural Trade-offs

| Decision | Choice | Rationale |
| --- | --- | --- |
| **Telemetry Parsing Location** | Frontend (`parsers.js`) | Eliminates backend rebuilds when CLI formats change; isolated unit testing. |
| **SSH Connection Model** | Persistent Shared Session | Eliminates per-request handshake penalty (~200–800ms $\rightarrow$ <10ms). |
| **Multi-Provider AI Routing** | 9Router Key Pool | Guarantees zero downtime via automatic round-robin and Tier-2 failover. |
| **E2EE Decryption Strategy** | Headless Playwright | Interacts natively with client-side encrypted IndexedDB keys and DOM. |
| **Context Management** | Active Turn Compactor | Prevents Groq `HTTP 413 Payload Too Large` in multi-step AI reasoning turns. |
| **Physical Server Geolocation** | Explicit Ground Truth Metadata | Accurately identifies **Định Công, Hà Nội** despite dynamic ISP GeoIP shifts. |
