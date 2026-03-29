---
description: diagnose and fix common runtime issues with the backend, frontend, or Docker stack
---

# Troubleshooting Guide

## Quick Health Check

Always run this first before digging deeper:

```bash
docker compose ps
docker compose logs --tail=50 backend
docker compose logs --tail=50 frontend
```

---

## Issue: Backend container stuck in `starting` / never becomes `healthy`

**Root cause:** Spring Boot or JVM startup exceeded the `start_period: 90s` window,
or the SSH connection on startup failed.

**Diagnosis:**

```bash
docker compose logs -f backend
```

Look for:

- `APPLICATION FAILED TO START` → environment variable missing, check `.env`
- `Connection refused` or `UnknownHostException` → `SSH_HOST` in `.env` is wrong
- `JSchException: Auth fail` → `SSH_USER` or `SSH_PASSWORD` is incorrect
- `OutOfMemoryError` → server has less than 512 MB free RAM for Docker

**Fix:**

```bash
# 1. Verify .env values are loaded correctly
docker compose exec backend env | grep SSH

# 2. If .env was just edited, recreate the container to pick up new values
docker compose up -d --force-recreate backend

# 3. If the server is low on memory, check resource usage
docker stats
```

---

## Issue: Dashboard shows "ERROR: no data returned from SSH"

**Root cause:** The SSH session to the remote Linux server failed or timed out.

**Diagnosis:**

```bash
# Check backend logs for JSchException or connection errors
docker compose logs --tail=100 backend | grep -i "error\|exception\|ssh"
```

**Fix:**

1. Verify network connectivity from the server to the SSH target:

   ```bash
   docker compose exec backend wget --spider --timeout=5 http://${SSH_HOST}:${SSH_PORT}
   ```

1. If using Ngrok, confirm the Ngrok tunnel is active and the address/port in `.env`
   matches the current Ngrok session (Ngrok addresses change on reconnect).

1. Restart the backend to force a new SSH session:

   ```bash
   docker compose restart backend
   ```

---

## Issue: Frontend shows blank page or 502 Bad Gateway

**Root cause 1:** Frontend container started before backend was healthy.

```bash
# Check if backend is healthy first
docker compose ps backend
```

If backend is `unhealthy` or `starting`, fix the backend first (see above).

**Root cause 2:** Nginx config is misconfigured.

```bash
docker compose exec frontend nginx -t
# Expected: syntax is ok / test is successful
```

**Root cause 3:** Backend port 8080 is not reachable from the frontend container.

```bash
docker compose exec frontend wget --spider http://backend:8080/actuator/health
# Expected: "200 OK"
```

---

## Issue: `docker compose up --build` fails (backend build error)

**Root cause:** Maven build failure, typically a missing dependency or network issue.

```bash
docker compose build backend 2>&1 | tail -50
```

Common causes:

- **No internet on build server:** Maven cannot download dependencies.
  Solution: Ensure the server has outbound internet access during build.
- **JAR name mismatch:** `pom.xml` version changed but `Dockerfile` `COPY` line
  was not updated.
  Solution: Align `dashboard-0.0.1-SNAPSHOT.jar` in `Dockerfile` with the actual
  `<version>` in `pom.xml`.
- **Peer dependency conflict (frontend):** The `--legacy-peer-deps` flag is missing.
  Solution: Verify the frontend `Dockerfile` uses `npm install --legacy-peer-deps`.

---

## Issue: `npm run lint` reports errors

```bash
cd frontend
npm run lint
```

Common errors and fixes:

| Error | Fix |
| --- | --- |
| `react-hooks/exhaustive-deps` | Add the missing dependency to the `useEffect` dep array, or use `useRef` if the value should not trigger re-renders |
| `no-unused-vars` | Remove the unused variable, or prefix with `_` if intentionally unused |
| `react-hooks/rules-of-hooks` | Move the hook call to the top level of the component, not inside a condition or loop |

Never disable `react-hooks/exhaustive-deps` or `react-hooks/rules-of-hooks` in eslint config.

---

## Issue: `backend/.env` was accidentally committed

**Stop.** This is a security incident. Act immediately.

```bash
# 1. Remove from tracking (does NOT delete the file from disk)
git rm --cached backend/.env
git commit -m "chore(security): remove accidentally tracked .env file"
git push origin main

# 2. Rotate ALL credentials that were exposed:
#    - Change SSH_PASSWORD on the remote server
#    - Update backend/.env on the production server with the new password
#    - If Ngrok credentials were exposed, revoke them in the Ngrok dashboard

# 3. Consider the git history compromised — use BFG Repo-Cleaner or
#    git-filter-repo to scrub the secret from all historical commits
#    if the repository is public.
```

---

## Issue: Self-hosted GitHub Actions runner is offline

```bash
# SSH into the production server
# Check runner service status (name varies by installation)
sudo systemctl status actions.runner.*

# Restart if stopped
sudo systemctl restart actions.runner.*

# Check runner logs
journalctl -u actions.runner.* -n 50
```

If the runner cannot reconnect, re-register it from GitHub:
**Settings → Actions → Runners → Remove → New self-hosted runner**

---

## Issue: High memory usage / OOM (Out of Memory)

**Diagnosis:**

```bash
docker stats --no-stream
```

Expected:

- `dashboard_backend`: < 1 GB (limit is 1 GB, reservation 512 MB)
- `dashboard_frontend`: < 256 MB

If backend memory exceeds 700 MB under normal load, check for:

- SSH session leaks (sessions not being cleaned up after `@PreDestroy`)
- Unusually large SSH output buffers

---

## Useful One-Liners

```bash
# Full restart of the stack (hard reset)
docker compose down && docker compose up -d --build

# Remove dangling images after many builds
docker image prune -f

# Inspect backend environment variables (confirm .env is loaded)
docker compose exec backend env | sort

# Check which port is bound on the host
netstat -tlnp | grep -E '5173|8080'

# Follow all logs with timestamps
docker compose logs -f -t
```
