---
description: run the full stack (backend + frontend) locally using Docker Compose with a production-like build
---

# Local Dev — Full Stack (Docker Compose)

## Prerequisites

- Docker Desktop (or Docker Engine) running — `docker info` must succeed.
- Docker Compose v2 — `docker compose version` must report `v2.x`.
- `backend/.env` must exist with valid `SSH_*` values.

---

## Start the Full Stack

Build both images and start all services in detached mode:

```bash
docker compose up -d --build
```

Docker Compose will:

1. Build the backend image (Maven multi-stage) → Spring Boot JAR on Alpine JRE 21.
1. Build the frontend image (Node multi-stage) → static files served by Nginx.
1. Start `backend` first, wait for the `/actuator/health` probe to return `UP`
   (up to 90 s), then start `frontend`.

Open the dashboard:

```text
http://localhost:5173
```

---

## Viewing Logs

```bash
# Stream all service logs
docker compose logs -f

# Stream backend only
docker compose logs -f backend

# Stream frontend (Nginx) only
docker compose logs -f frontend
```

---

## Rebuilding a Single Service

After a code change in the backend only:

```bash
docker compose up -d --build backend
```

After a code change in the frontend only:

```bash
docker compose up -d --build frontend
```

This avoids a full stack rebuild and reduces downtime.

---

## Health Status

```bash
docker compose ps
```

Both `backend` and `frontend` should show `healthy` in the STATUS column.
If `backend` is `starting`, wait for the `start_period: 90s` to elapse.

---

## Stopping

```bash
# Stop and keep containers (fast restart later)
docker compose stop

# Stop and remove containers (clean start next time)
docker compose down
```

---

## Verifying Image Sizes

After a build, verify images remain within expected bounds:

```bash
docker images | grep dashboard
```

| Image | Target max size |
| --- | --- |
| `dashboard_backend` | < 200 MB |
| `dashboard_frontend` | < 50 MB |

If sizes exceed targets, a large file was likely copied into the image unintentionally.
Inspect with `docker image inspect <image-id>`.

---

## Notes

- `backend/.env` is loaded into the `backend` container via the `env_file` stanza
  in `docker-compose.yml`. It is never baked into the image.
- The `frontend` container does NOT need the `.env` file — all API calls go through
  Nginx reverse proxy to the `backend` service on the internal `dashboard-network`.
- Never run `docker compose up` without `-d` on a remote server — it will block
  the terminal and die when you disconnect.
