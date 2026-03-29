# Rule 04 — Docker, Nginx & Infrastructure Conventions

## Docker Compose Topology

```yaml
services:
  backend:   # Spring Boot JAR — Alpine JRE 21
  frontend:  # React build — Nginx Alpine

networks:
  dashboard-network:
    driver: bridge
```

Both containers are on the same bridge network. They resolve each other
by service name (`backend`, `frontend`). Never use hardcoded IPs.

---

## Service Dependencies

```yaml
frontend:
  depends_on:
    backend:
      condition: service_healthy
```

The frontend container **must not start before the backend is healthy**.
This is not just a cosmetic ordering — during a cold start, Nginx would
otherwise proxy `/api/*` to a backend that has not yet bound its port.

---

## Healthchecks

### Backend healthcheck

```yaml
test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider",
       "http://localhost:8080/actuator/health"]
interval: 30s
timeout: 10s
retries: 3
start_period: 90s  # Spring Boot + JVM startup can take up to 60–70 s
```

- Uses `wget` (not `curl`) because the Alpine JRE image does not ship `curl`.
  `wget` is explicitly installed via `apk add --no-cache wget` in the backend
  Dockerfile.
- `start_period: 90s` — do not reduce. Spring Boot 4 + SSH crypto initialisation
  needs budget on a low-resource server.
- The `/actuator/health` endpoint does not probe SSH — it reports Spring context
  health only. This is intentional so the dashboard stays reachable even when
  the remote server is temporarily offline.

### Frontend healthcheck

```yaml
test: ["CMD", "curl", "-f", "http://localhost:80"]
interval: 30s
timeout: 5s
retries: 3
start_period: 15s  # Nginx starts in < 2 s; 15 s is ample
```

`curl` is available on `nginx:alpine` by default.

---

## Resource Limits

| Container | CPU limit | RAM limit | RAM reservation |
| --- | --- | --- | --- |
| backend | 1.5 cores | 1 GB | 512 MB |
| frontend | 0.5 cores | 256 MB | 64 MB |

Do not lower the backend reservation below 512 MB. Spring Boot 4 +
JSch cryptographic operations under load can spike to 600–700 MB.

---

## Restart Policy

Both services use `restart: unless-stopped`.
This ensures automatic recovery after the host server reboots without
requiring manual `docker compose up`. Do not change to `always` — that
would conflict with deliberate `docker compose stop` commands.

---

## Nginx Configuration (`frontend/nginx.conf`)

```nginx
server {
    listen 80;
    server_name localhost;

    # React SPA — fallback to index.html for client-side routing
    location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # API reverse proxy — no CORS needed; same origin from the browser's POV
    location /api/ {
        proxy_pass http://backend:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
```

Rules:

- `try_files $uri $uri/ /index.html` is required for React client-side
  routing. Never remove it.
- `proxy_pass http://backend:8080/api/;` — trailing slash matters.
  Without it, Nginx will not strip the `/api/` prefix before forwarding.
- Always forward `X-Real-IP` and `X-Forwarded-For` so the backend can
  log the real client IP even behind the proxy layer.
- Do not add caching headers for `/api/` — metrics data must always be live.

---

## Port Mapping

| Host port | Container port | Service |
| --- | --- | --- |
| 5173 | 80 | Nginx (frontend) |
| 8080 | 8080 | Spring Boot (backend) |

Port 5173 on the host is the **only client-facing port for the dashboard**.
Port 8080 is used for healthchecks and for local development (direct API
access + CORS from Vite dev server). In production, 8080 should be
firewalled from public access.

---

## Secrets Management

| Secret | Location | Committed? |
| --- | --- | --- |
| `SSH_HOST` | `backend/.env` | ❌ Never |
| `SSH_PORT` | `backend/.env` | ❌ Never |
| `SSH_USER` | `backend/.env` | ❌ Never |
| `SSH_PASSWORD` | `backend/.env` | ❌ Never |

`backend/.env.example` contains placeholder values and IS committed.
Update `.env.example` whenever a new variable is added — do not let
the example fall out of sync with production use.

The `env_file: backend/.env` stanza in `docker-compose.yml` maps these
variables to `SSH_*` environment variables inside the backend container.
Spring Boot maps them to `ssh.*` properties via its relaxed binding
(`SSH_HOST` → `ssh.host`).

---

## Multi-Stage Builds

Both services use multi-stage builds. Final images must never contain:

- Maven wrapper or Maven cache (backend)
- `node_modules` or `node` runtime (frontend)
- Source code (`.java`, `.jsx`)
- Test classes

Verify with `docker image inspect` that image sizes remain reasonable:

- Backend target: < 200 MB
- Frontend target: < 50 MB
