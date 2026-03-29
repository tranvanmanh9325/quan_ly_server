# Rule 02 — Backend Java Conventions

## Package Structure

```text
com.miniserver.dashboard
├── DashboardApplication.java   ← @SpringBootApplication entry point
├── config/
│   └── CorsConfig.java         ← WebMvcConfigurer (dev-only CORS)
├── controller/
│   └── MetricsController.java  ← @RestController, HTTP → command mapping
└── service/
    └── SshService.java         ← SSH session management + command execution
```

New classes go into the appropriate existing package.
**Do not create new top-level packages** without a documented reason.

---

## Spring Boot Conventions

### Dependency Injection

Always use **constructor injection** for non-optional dependencies.
`@Autowired` on fields (as seen in the legacy `MetricsController`) is
acceptable for existing code but must not be used in new code.

```java
// ✅ Correct — new code
@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

    private final SshService sshService;

    public MetricsController(SshService sshService) {
        this.sshService = sshService;
    }
}

// ❌ Avoid — do not add new @Autowired field injection
@Autowired
private SshService sshService;
```

### `@Value` Injection

SSH credentials are injected via `@Value("${ssh.*}")` properties.
These map to the `backend/.env` file through Spring Boot's auto-loading
of environment variables. **Never hardcode** credentials or host names.

---

## `SshService` Rules

### Session lifecycle

- One `JSch` session lives for the entire Spring Boot process lifetime.
- `getOrCreateSession()` is `synchronized` — do not remove the lock.
- `@PreDestroy cleanup()` disconnects on shutdown — always keep this method.

### Error handling & retry

- `executeCommand` retries up to **3 times** with exponential backoff
  `[250 ms, 500 ms, 1 000 ms]`.
- On any exception, the shared session is **discarded** and recreated on
  the next attempt — never reuse a zombie session.
- Return `"ERROR: <message>"` (not `null`) on total failure; the
  `safeData()` guard in the controller will wrap it safely.

### Logging

- Use SLF4J (`LoggerFactory.getLogger`) — never `System.out` or
  `System.err`.
- Capture SSH `stderr` into a `ByteArrayOutputStream` and log via
  `log.warn(...)`. This ensures Docker container logs work correctly.

```java
// ✅ Correct
private static final Logger log = LoggerFactory.getLogger(SshService.class);

// ❌ Forbidden
System.err.println("error");
```

---

## `MetricsController` Rules

### Null / blank guard

Every endpoint that returns raw SSH output **must** go through `safeData()`:

```java
private Map<String, String> safeData(String result) {
    Map<String, String> map = new HashMap<>();
    if (result == null || result.isBlank()) {
        map.put("data", "ERROR: no data returned from SSH");
    } else {
        map.put("data", result.trim());
    }
    return map;
}
```

Do not inline null-checks into individual endpoints — use `safeData()`.

### Response envelope

- Simple string endpoints → `Map<String, String>` with key `"data"`.
- Structured endpoints (e.g. `/connections`, `/sysinfo`) may return
  `Map<String, Object>` or `Map<String, String>` with multiple keys.
- **Never return a plain `String`** from an endpoint — always wrap in a map
  so the frontend has a consistent shape to `?.data` against.

### Shell command hygiene

- Prefer **compound commands** (`&&`, `printf`) to batch multiple queries
  into one SSH round-trip (see `/sysinfo` as the canonical example).
- Add `2>/dev/null` fallbacks when a command might not exist on the
  remote host (`sensors`, `lscpu`, `lshw`...).
- Include a `fallback` path (e.g. `/sys/class/thermal/...`) when a
  standard tool may not be installed.

---

## `CorsConfig` Rules

- Allowed origins: `http://localhost:5173` and `http://127.0.0.1:5173` only.
- **Do not add wildcard origins** (`*`) — this would break `allowCredentials(true)`.
- Allowed headers must be explicit. Never revert to `allowedHeaders("*")`.
- `maxAge(3600)` must remain — it reduces preflight OPTIONS request noise.

If a new development port is needed, add it explicitly and document why.

---

## Maven / `pom.xml` Rules

- Spring Boot BOM version is `4.0.x`. All Spring-managed dependencies
  (Lombok, Actuator, Test, Web) **must not declare an explicit version** —
  let the BOM manage it.
- Only `jsch` (external, not BOM-managed) declares an explicit version.
- Lombok is excluded from the final JAR via the `spring-boot-maven-plugin`
  exclude block — this exclusion must never be removed.
- `spring-boot-devtools` scope must remain `runtime` + `optional=true`.

---

## JVM / Docker

- Base image for builder stage: `maven:3.9.6-eclipse-temurin-21`
- Base image for runtime stage: `eclipse-temurin:21-jre-alpine`
- `wget` must be installed in the runtime image (`apk add --no-cache wget`)
  because docker-compose's healthcheck uses `wget --spider`, not `curl`.
- Always use **multi-stage builds** — never ship Maven or source code in
  the final image.
- The JAR artifact name is `dashboard-0.0.1-SNAPSHOT.jar`. If you change
  `pom.xml` artifact or version, update the `COPY` line in `Dockerfile`.
