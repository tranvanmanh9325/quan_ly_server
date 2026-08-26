# Backend Internals

An in-depth architectural look at the backend microservices architecture: **Spring Boot 4.1.0** (Java 21) services and the **FastAPI** (Python 3.11) AI Agent & 9Router service.

---

## 1. Microservices Separation of Concerns

```text
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│     metrics-service     │  │       auth-service      │  │       file-service      │  │     ai-agent-service    │
│    Spring Boot 4.1.0    │  │    Spring Boot 4.1.0    │  │    Spring Boot 4.1.0    │  │      FastAPI Python     │
│        Port 8082        │  │        Port 8081        │  │        Port 8083        │  │    Port 8084 & 6080     │
│                         │  │                         │  │                         │  │                         │
│ • JSch Persistent SSH   │  │ • Single-User Auth      │  │ • JSch SFTP Browser     │  │ • 9Router Key Pools     │
│ • Telemetry Endpoints   │  │ • BCrypt Hash (Cost 12) │  │ • File Read / Write     │  │ • Telegram Bot Agent    │
│ • Sudo Executor         │  │ • JWT Access & Refresh  │  │ • Directory Operations  │  │ • Playwright E2EE FB    │
│ • Alert Notifications   │  │ • Auth Interceptors     │  │ • Log Stream Viewer     │  │ • TikTok Streak Keeper  │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘
```

---

## 2. Spring Boot Microservices (Java 21)

### JSch SSH Session Pool (`SshService`)
- Manages a persistent SSH session over the application lifetime.
- Commands execute via lightweight `ChannelExec` instances (<10 ms setup).
- Automatic reconnection with exponential backoff (`250ms`, `500ms`, `1000ms`).

### Actuator & Health Monitoring
- All Spring Boot services implement Spring Boot Actuator on `/actuator/health` used by Docker Compose health checks.

### Memory & Garbage Collection Tuning
- Configured with optimized JVM flags:
  `-XX:+UseG1GC -XX:MaxRAMPercentage=60.0 -XX:+ExitOnOutOfMemoryError`

---

## 3. AI Agent & 9Router Service (Python 3.11 FastAPI)

### Autonomous ReAct Agent ("Tiểu Bảo Bảo")
- **Pyramid Principle / BLUF Thinking Engine:** Answers lead with a direct conclusion on line 1.
- **Telegram Native Formatter (`TelegramFormatter`):** Converts Markdown tables into mobile-friendly cards, auto-escapes HTML, balances tags, and normalizes Vietnamese typography.
- **Active Turn Context Compactor (`_build_compact_messages_for_llm`):** Dynamically compacts older tool outputs to ensure total payload stays under 3,500 chars, eliminating Groq `HTTP 413 Payload Too Large` errors.
- **Stagnation Circuit Breaker:** Detects duplicate command calls and forces synthesis when iterations reach limits.
- **Ground Truth Physical Location:** Configured at **Định Công, Hoàng Mai, Hà Nội, Việt Nam**, distinguishing physical hardware location from ISP BGP dynamic GeoIP routing.

### 9Router Engine & RTK
- **Multi-Key Pool Rotation:** Round-robin balancing across Groq and OpenRouter keys with automatic 60s cooldown on 429 rate limits.
- **Real-Time Token Compressor (RTK):** Achieves 40–85% reduction in prompt token volume with background persistence to PostgreSQL (`rtk_stats`).
- **OpenAI-Compatible Gateway:** Fully compliant `/v1/chat/completions` endpoint for external client tooling.

### Facebook & TikTok Automation Services
- **Playwright Headless Chromium:** Runs in an isolated Xvfb display (`:99`) with persistent browser profiles (`browser_data`).
- **Automated 6-Digit PIN Unlock:** Automatically unlocks Facebook E2EE security challenge screens.
- **Intelligent Unsend Engine:** Automatically revokes absence auto-replies when the human owner responds.
- **TikTok Streak Keeper:** Daily automated check-in routines.
- **Long-term Self-Learning Memory Engine:** PostgreSQL-backed memory engine (`AgentMemoryService`).
