# Backend Internals

A technical reference for the backend microservices architecture: Spring Boot services, FastAPI AI Agent service, JSch SSH session pooling, CORS configuration, and runtime properties.

---

## Tech Stack & Microservices

| Service | Framework / Tool | Language / Runtime | Purpose |
| --- | --- | --- | --- |
| **Metrics Service (`:8082`)** | Spring Boot 4.1.0, JSch 2.28.5 | Java 21 / Eclipse Temurin Alpine | System telemetry, JSch persistent SSH tunnel, sudo execution |
| **Auth Service (`:8081`)** | Spring Boot 4.1.0, JJWT 0.12.6, Spring Security | Java 21 / Eclipse Temurin Alpine | JWT authentication, user credentials & BCrypt hashing |
| **File Service (`:8083`)** | Spring Boot 4.1.0, JSch SFTP | Java 21 / Eclipse Temurin Alpine | Remote file browsing, syntax viewing & SFTP manipulation |
| **AI Agent Service (`:8084`)** | FastAPI 0.115+, Playwright, AsyncSSH | Python 3.11 / Debian Slim | Telegram Bot assistant, Playwright Facebook E2EE & Multi-LLM Pool |
| **Database (`:5432`)** | PostgreSQL Alpine | PostgreSQL 17 | Persistent database storage |

---

## 1. Metrics Service Package Structure (`com.miniserver.metrics`)

```text
com.miniserver.metrics
├── MetricsServiceApplication.java     ← Spring Boot entry point (@SpringBootApplication)
├── config/
│   ├── CorsConfig.java                ← WebMvcConfigurer: CORS policy for local development
│   └── SchedulingConfig.java          ← ThreadPoolTaskScheduler (5 worker threads for @Scheduled)
├── controller/
│   └── MetricsController.java         ← @RestController: HTTP telemetry routes → shell commands
└── service/
    └── SshService.java                ← Persistent JSch session (LAN/fallback) + sudo executor
```

---

## 2. AI Agent Service Structure (`services/ai-agent-service`)

```text
ai-agent-service/
├── app/
│   ├── main.py                        ← FastAPI application entry point & router registration
│   ├── config.py                      ← Environment settings & Multi-LLM Pool configuration
│   ├── db/
│   │   └── session.py                 ← Async PostgreSQL connection pool (psycopg3)
│   ├── services/
│   │   ├── ai_agent.py                ← "Tiểu Bảo Bảo" prompt engine & tool execution
│   │   ├── groq_pool.py               ← 9router-style Groq multi-key rotation & cooldown
│   │   ├── openrouter_pool.py         ← OpenRouter fallback pool management
│   │   ├── telegram_service.py        ← Long Polling Telegram receiver & dispatcher
│   │   └── facebook_service.py        ← Playwright Facebook E2EE worker & unsend engine
│   └── routers/
│       ├── facebook_router.py         ← Facebook manual triggers & status endpoints
│       └── ai_router.py               ← OpenAI-compatible AI gateway endpoints
├── Dockerfile                         ← Python 3.11 + Playwright Chromium + Xvfb + noVNC
└── requirements.txt
```

---

## `DashboardApplication.java`

Standard Spring Boot entry point. No custom configuration — Spring auto-configuration handles everything.

```
@SpringBootApplication
public class DashboardApplication {
    public static void main(String[] args) {
        SpringApplication.run(DashboardApplication.class, args);
    }
}
```

---

## `CorsConfig.java`

Implements `WebMvcConfigurer` to configure CORS policy. This is **only exercised during local development** — in production, all traffic flows through Nginx on port 5173 (single origin), so CORS headers are never sent.

| Setting | Value | Reason |
| --- | --- | --- |
| `allowedOrigins` | `http://localhost:5173`, `http://127.0.0.1:5173` | Vite dev server origins only |
| `allowedMethods` | `GET, POST, PUT, DELETE, OPTIONS` | Full REST method support |
| `allowedHeaders` | `Content-Type, Accept, Authorization, X-Requested-With` | Explicit list (not wildcard) to stay within CORS spec |
| `allowCredentials` | `true` | Supports cookie-based auth if added in the future |
| `maxAge` | `3600` (1 hour) | Caches preflight responses to reduce OPTIONS overhead |

> **Why not `allowedHeaders("*")` with `allowCredentials(true)`?**
> The CORS specification prohibits this combination — browsers reflect the full request header list when wildcard is used alongside credentials, which violates the spec and may be blocked. Explicit header enumeration is the correct approach.

---

## `MetricsController.java`

Mapped to `GET /api/metrics/*`. Each endpoint delegates to `SshService.executeCommand(shellCmd)` and wraps the result in a JSON map via `safeData()`.

### `safeData(String result): Map<String, String>`

A null-guard helper that prevents `NullPointerException` propagation when SSH fails:

- `null` or blank result → returns `{ "data": "ERROR: no data returned from SSH" }`
- Valid result → returns `{ "data": result.trim() }`

### Endpoint → Command Mapping

| HTTP Route | Shell Command | Response Type |
| --- | --- | --- |
| `GET /cpu` | `top -b -n 1 \| grep 'Cpu(s)'` | `Map<String, String>` |
| `GET /ram` | `free -m` | `Map<String, String>` |
| `GET /disk` | `df -h -x tmpfs -x devtmpfs` | `Map<String, String>` |
| `GET /network` | `cat /proc/net/dev` | `Map<String, String>` |
| `GET /processes` | `ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu` | `Map<String, String>` |
| `GET /temperature` | `sensors` (fallback: thermal_zone sysfs) | `Map<String, String>` |
| `GET /voltage` | `sensors` (or `echo 'N/A'`) | `Map<String, String>` |
| `GET /system` | `uptime` | `Map<String, String>` |
| `GET /connections` | `who` | `Map<String, Object>` (parsed) |
| `GET /sysinfo` | Batched `printf` + `uname` + `hostname` + `lscpu` | `Map<String, String>` (parsed) |

### `/connections` — Inline Parsing

This is the only endpoint where parsing occurs in the backend. The `who` command output is split into columns and mapped to:

```java
{ "user": parts[0], "terminal": parts[1], "loginTime": parts[2] + " " + parts[3], "ip": parts[4] }
```

IP addresses are extracted by stripping leading `(` and trailing `)` characters.

### `/sysinfo` — Batched SSH Round-Trip

Four system identity commands are joined with `&&` into a single SSH call to reduce channel-open overhead. The backend parses the `KEY:VALUE\n` format using `indexOf(':')` to avoid splitting on colons within values (e.g. IPv6 addresses in future fields).

```
printf 'KERNEL:%s\n'    "$(uname -r)"
printf 'HOSTNAME:%s\n'  "$(hostname)"
printf 'OS:%s\n'        "$(grep PRETTY_NAME /etc/os-release ...)"
printf 'CPU_MODEL:%s\n' "$(lscpu | grep 'Model name' | sed ...)"
```

Each `case` in the `switch` expression (Java 14+ pattern) maps the key to the corresponding result map entry.

---

## `SshService.java`

The most complex class in the project. Manages a persistent SSH session across the entire Spring Boot application lifetime.

### Session Lifecycle

```
Application context created
    │
    └── No session yet (sharedSession = null)

First HTTP request arrives
    │
    └── getOrCreateSession() [synchronized]
            │
            └── Creates JSch session:
                    ├── host/port/user/password from @Value (injected from .env)
                    ├── StrictHostKeyChecking = no
                    ├── ServerAliveInterval  = 30 000 ms
                    ├── ServerAliveCountMax  = 3
                    └── connect(timeout = 15 000 ms)

Subsequent requests
    │
    └── getOrCreateSession() returns cached sharedSession (no re-handshake)

Spring context destroyed (SIGTERM / docker compose down)
    │
    └── @PreDestroy cleanup() → session.disconnect()
```

### `executeSudoCommand(String command): String`

Executes administrative commands requiring superuser privileges. Automatically feeds the SSH password into `sudo -S` via stdin (`password + "\n"`), allowing AI tool calls and system administration scripts to run `sudo` commands without interactive password prompts.

### Dual-Host Connection Strategy (LAN / Ngrok Fallback)

`SshService` implements a dual-target strategy:

1. Primary target: Local LAN IP (`SSH_HOST:22`).
2. Fallback target: Ephemeral Ngrok TCP tunnel (`SSH_FALLBACK_HOST:SSH_FALLBACK_PORT`).
If LAN connection fails or times out (15s), `SshService` automatically switches to the fallback endpoint to guarantee high availability.

---

## `AiChatService.java`

Provides an autonomous AI sysadmin agent powered by Groq's Function Calling REST API (`llama-3.1-8b-instant`).

### Features & Protections

- **Tool Calling Execution:** Exposes `run_command` tool to Groq LLM, translating natural language queries ("Check when system was last updated") into target shell commands.
- **Context Window Management:** Caps history at `MAX_HISTORY_MESSAGES = 6` (3 Q&A pairs) and `MAX_OUTPUT_CHARS = 1000` to ensure prompt tokens stay strictly under Groq's 6,000 TPM limit.
- **Resiliency & Auto-Recovery:** Implements 3 retries with 2.5s backoff on 429 Rate Limit responses. Automatically invokes `clearHistory(chatId)` on 400 Bad Request or 429 Rate Limit errors to purge corrupt state and unblock subsequent chat messages.

---

## `TelegramBotService.java` & `SchedulingConfig.java`

- **Multithreaded Task Scheduler (`SchedulingConfig`):** Configures `ThreadPoolTaskScheduler` with 5 worker threads (`scheduled-task-1`..`5`) so background polling, telemetry refreshes, and Telegram updates execute in parallel.
- **HTTP Client Timeouts:** `TelegramBotService` and `TelegramNotificationService` utilize `SimpleClientHttpRequestFactory` with explicit 5s connect timeout and 12s/30s read timeouts to prevent HTTP socket threads from parking indefinitely on dropped TCP packets.

### Thread Safety

`getOrCreateSession()` and the session invalidation block inside the catch clause are both `synchronized`. Since multiple HTTP request threads may call `executeCommand()` concurrently, this prevents a race where two threads simultaneously observe a `null` session and both attempt to create a new connection.

`executeCommand()` itself is not `synchronized` — multiple threads can run commands concurrently on different channels of the same session, which is the intended JSch multi-channel behaviour.

---

## `application.properties`

```properties
server.port=8080
spring.application.name=mini-server-dashboard

# Loads .env file as additional property source (optional, does not fail if missing)
spring.config.import=optional:file:.env[.properties]

# SSH credentials — injected via @Value in SshService
ssh.host=${SSH_HOST}
ssh.port=${SSH_PORT}
ssh.user=${SSH_USER}
ssh.password=${SSH_PASSWORD}

# Actuator: expose only the health endpoint (no sensitive info leaked)
management.endpoints.web.exposure.include=health
management.endpoint.health.show-details=never
```

`spring.config.import=optional:file:.env[.properties]` tells Spring to attempt loading `backend/.env` as a `.properties`-style file if it exists. The `optional:` prefix prevents a startup failure when the file is absent (e.g. in CI environments where variables are injected differently).

---

## Dockerfile (Backend)

```dockerfile
# Stage 1: Build
FROM maven:3.9.6-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn clean package -DskipTests

# Stage 2: Runtime (minimised image)
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN apk add --no-cache wget         # required by Docker Compose healthcheck
COPY --from=builder /app/target/dashboard-0.0.1-SNAPSHOT.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Why `wget` instead of `curl` in Alpine?** The `healthcheck` in `docker-compose.yml` uses `wget --spider` because `curl` is not included in the `eclipse-temurin:21-jre-alpine` base image. Installing `wget` is lighter than adding `curl`.

**JVM start time:** The Alpine JRE 21 image starts in ~2–3 s, but Spring Boot's auto-configuration and classpath scanning add ~5–15 s. The Docker Compose `start_period: 90s` gives the container time to complete startup before health checks begin counting failures.

---

## Maven Dependencies (`pom.xml`)

| Artifact | Purpose |
| --- | --- |
| `spring-boot-starter-web` | Embedded Tomcat + Spring MVC + Jackson JSON |
| `spring-boot-starter-actuator` | `/actuator/health` endpoint for Docker healthcheck |
| `spring-boot-devtools` | Hot reload during local development (runtime scope, excluded from JAR) |
| `lombok` | Reduces boilerplate (optional; compile-only, excluded from fat JAR) |
| `com.github.mwiede:jsch:2.27.9` | Modern, maintained JSch fork — supports newer SSH algorithms |
| `spring-boot-starter-test` | JUnit 5 + AssertJ + Mockito for testing |

> **Note on the JSch fork:** The original JCraft JSch library is largely unmaintained. The `mwiede` fork (`com.github.mwiede:jsch`) is the de-facto community successor and supports modern key exchange algorithms (e.g. `ecdh-sha2-nistp256`, `curve25519-sha256`) required by recent OpenSSH servers.
