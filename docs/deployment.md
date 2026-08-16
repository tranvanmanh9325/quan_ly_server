# Deployment Guide

A step-by-step guide covering local development setup, production Docker deployment, CI/CD pipeline configuration, and operational runbooks.

---

## Prerequisites by Mode

### Local Development

| Tool | Minimum Version | Purpose |
| --- | --- | --- |
| Java (JDK) | 21 | Run/compile the Spring Boot backend |
| Maven | 3.9 | Build the backend |
| Node.js | 20 LTS | Build/run the React frontend |
| npm | 10+ | Install frontend dependencies |

### Production Server

| Tool | Minimum Version | Purpose |
| --- | --- | --- |
| Docker Engine | 24 | Build and run containers |
| Docker Compose | V2 (CLI plugin) | Orchestrate backend + frontend |
| Git | 2.x | Clone the repository and receive CI/CD updates |

---

## 1. Local Development

### 1.1 Clone the Repository

```bash
git clone https://github.com/<YOUR_USERNAME>/quan_ly_server.git
cd quan_ly_server
```

### 1.2 Configure SSH Credentials

```bash
cp backend/.env.example backend/.env
```

Edit `.env` in the project root directory:

```dotenv
# Primary SSH Target Credentials (LAN)
SSH_HOST=your_target_server_ip
SSH_PORT=22
SSH_USER=your_ssh_user
SSH_PASSWORD=your_ssh_password

# SSH Fallback via Ngrok
SSH_FALLBACK_HOST=your_fallback_ngrok_host
SSH_FALLBACK_PORT=12345

# Database Configuration
POSTGRES_DB=quan_ly_server
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password

# Auth & JWT Security
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=your_bcrypt_hashed_password
JWT_SECRET=your_secret_jwt_key_at_least_32_characters_long
JWT_EXPIRATION_HOURS=24

# Telegram & Groq Multi-Key Pool (Primary)
GROQ_API_KEY=gsk_primary_key
GROQ_API_KEY_2=gsk_second_key
GROQ_MODEL=openai/gpt-oss-120b

# OpenRouter Multi-Key Pool (Tier-2 Fallback)
OPENROUTER_API_KEY=sk-or-v1-primary_key
OPENROUTER_API_KEY_2=sk-or-v1-second_key
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free

# Facebook Messenger E2EE (Playwright)
FB_PIN=your_6_digit_pin
```

> ⚠️ `.env` is listed in `.gitignore`. Never commit it.

### 1.3 Production Deployment (Docker Compose)

```bash
# Build and launch the entire 6-container stack in detached mode
docker compose up -d --build

# Monitor health status across all services
docker compose ps
```

The stack orchestrates 6 containers:
- `dashboard_db` (PostgreSQL 17 on `:5432`)
- `dashboard_auth_service` (Spring Boot on `:8081`)
- `dashboard_metrics_service` (Spring Boot on `:8082`)
- `dashboard_file_service` (Spring Boot on `:8083`)
- `dashboard_ai_agent` (FastAPI + Playwright on `:8084` & noVNC `:6080`)
- `dashboard_frontend` (React 19 + Nginx on `:5173`)

1. Builds the backend image (Maven → JRE Alpine, multi-stage).
2. Builds the frontend image (Node → Nginx Alpine, multi-stage).
3. Starts both containers on the `dashboard-network` bridge network.
4. The frontend container waits until the backend reports `healthy` before starting.

### 2.4 Verify Container Health

```bash
docker compose ps
```

Both containers should show `healthy` status within ~2 minutes. If the backend container stays in `starting` for more than 90 seconds, check its logs:

```bash
docker compose logs backend --tail=50
```

### 2.5 Accessing Microservices & Endpoints

| Service | Container Name | Port | Healthcheck / URL |
| --- | --- | --- | --- |
| **Frontend UI** | `dashboard_frontend` | `5173` | `http://<server-ip>:5173` |
| **Metrics Service** | `dashboard_metrics_service` | `8082` | `http://<server-ip>:8082/actuator/health` |
| **Auth Service** | `dashboard_auth_service` | `8081` | `http://<server-ip>:8081/actuator/health` |
| **File Service** | `dashboard_file_service` | `8083` | `http://<server-ip>:8083/actuator/health` |
| **Database** | `dashboard_db` | `5432` | `5432/tcp` (PostgreSQL 17) |

---

## 3. Server Systemd Automation & APT Daily Timers

To ensure the production host remains patched and clean without manual intervention:

1. **`apt-daily.timer`:** Triggered daily at **06:00:00 AM** (`sudo systemctl status apt-daily.timer`). Runs `apt update` to refresh package indices.
2. **`apt-daily-upgrade.timer`:** Triggered daily at **06:30:00 AM** (`sudo systemctl status apt-daily-upgrade.timer`). Upgrades installed packages.
3. **Auto Cleanup Policy (`/etc/apt/apt.conf.d/99auto-cleanup`):**

   ```apt
   APT::Periodic::AutocleanInterval "1";
   Unattended-Upgrade::Remove-Unused-Dependencies "true";
   Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
   ```

   Automatically executes `autoremove` and `autoclean` after daily upgrades to purge obsolete `.deb` archives and orphan kernels.

---

## 4. Container Resource Limits

Defined in `docker-compose.yml` under the `deploy.resources` key.

| Container | CPU Limit | Memory Limit | Memory Reservation |
| --- | --- | --- | --- |
| `dashboard_metrics_service` | 1.5 cores | 1 GB | 512 MB |
| `dashboard_auth_service` | 1.0 cores | 512 MB | 256 MB |
| `dashboard_file_service` | 1.0 cores | 512 MB | 256 MB |
| `dashboard_db` | 1.0 cores | 512 MB | 256 MB |
| `dashboard_frontend` | 0.5 cores | 256 MB | 64 MB |

**Rationale:**

- The backend budget accounts for Spring Boot's base memory (~300 MB JVM heap), SSH cryptographic operations, and concurrent HTTP thread pools.
- Nginx static file serving is extremely lightweight — the low frontend limits are intentional.

---

## 4. Health Checks

### Backend

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/actuator/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 90s
```

- Polls `/actuator/health` every 30 seconds.
- 90-second `start_period` allows Spring Boot to complete its startup sequence before failures are counted.
- Uses `wget` because `curl` is not available in the `eclipse-temurin:21-jre-alpine` base image.

### Frontend

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:80"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

Confirms Nginx is serving the React bundle on port 80.

---

## 5. CI/CD Pipeline

### Overview

The project uses a **self-hosted GitHub Actions runner** that runs directly on the production server. This means:

- No SSH secrets need to be stored in GitHub.
- The `backend/.env` file already exists on-disk and is not touched by the workflow.
- Every push to `main` triggers a zero-touch rebuild.

**Workflow file:** `.github/workflows/deploy.yml`

```yaml
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - run: |
          cd ~/quan_ly_server
          git reset --hard          # discard any accidental local edits
          git pull origin main      # fetch latest code
          docker compose up -d --build   # rolling rebuild
```

### 5.1 Setting Up the Self-Hosted Runner

#### Step 1 — Create the runner in GitHub

Navigate to: **Repository → Settings → Actions → Runners → New self-hosted runner**

Select **Linux / x64** and copy the commands that GitHub generates (they include a unique registration token).

#### Step 2 — Install the runner agent on the server

```bash
mkdir ~/actions-runner && cd ~/actions-runner

# Download — use the exact URL and filename from the GitHub UI
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-X.X.X.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz

# Register — use the token from the GitHub UI
./config.sh --url https://github.com/<YOUR_USERNAME>/quan_ly_server --token <YOUR_TOKEN>
```

#### Step 3 — Run as a systemd service (survives reboots)

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

#### Step 4 — Verify

Navigate to **Repository → Settings → Actions → Runners**. The runner should appear with a green **Idle** status.

From this point, every `git push origin main` triggers an automated rebuild. Progress is visible in the **Actions** tab on GitHub.

---

## 6. Operational Runbooks

### View Logs

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Frontend (Nginx access log)
docker compose logs -f frontend
```

### Restart a Service Without Rebuilding

```bash
docker compose restart backend
docker compose restart frontend
```

### Force a Full Rebuild

```bash
docker compose down
docker compose up -d --build
```

### Update SSH Credentials

1. Edit `backend/.env` with the new credentials.
2. Restart only the backend container:

   ```bash
   docker compose restart backend
   ```

   No rebuild is required — the `.env` file is read at container startup.

### View Resource Usage

```bash
docker stats dashboard_backend dashboard_frontend
```

### Stop All Services

```bash
docker compose down
```

To also remove volumes and networks:

```bash
docker compose down -v --remove-orphans
```

---

## 7. Environment Variables Reference

All variables are configured in the root `.env` file and passed into the microservice containers via Docker Compose `env_file`.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SSH_HOST` | ✅ Yes | — | Primary LAN IP or hostname of the target Linux server (e.g. `your_target_server_ip`). |
| `SSH_PORT` | ✅ Yes | `22` | SSH port on the target server. |
| `SSH_USER` | ✅ Yes | — | SSH username on the target server. |
| `SSH_PASSWORD` | ✅ Yes | — | SSH password used for authentication and `sudo -S` elevation. |
| `SSH_FALLBACK_HOST` | ⚠️ Optional | — | Ephemeral Ngrok TCP tunnel address (e.g. `your_fallback_ngrok_host`) used if LAN is unreachable. |
| `SSH_FALLBACK_PORT` | ⚠️ Optional | — | Ephemeral Ngrok TCP port. |
| `POSTGRES_DB` | ✅ Yes | `quan_ly_server` | Database name for central PostgreSQL 17 instance. |
| `POSTGRES_USER` | ✅ Yes | `postgres` | Database superuser username. |
| `POSTGRES_PASSWORD` | ✅ Yes | — | Database superuser password. |
| `APP_AUTH_USERNAME` | ✅ Yes | `admin` | Login username for Auth Service. |
| `APP_AUTH_PASSWORD` | ✅ Yes | — | BCrypt-hashed login password string. |
| `JWT_SECRET` | ✅ Yes | — | HMAC-SHA256 secret key for signing JWTs (must be ≥ 32 characters). |
| `TELEGRAM_BOT_TOKEN` | ⚠️ Optional | — | Telegram Bot API token for status alerts and AI updates. |
| `TELEGRAM_CHAT_ID` | ⚠️ Optional | — | Allowed Telegram Chat ID for security verification. |
| `TELEGRAM_POLLING_ENABLED` | ⚠️ Optional | `true` | Enables/disables long polling worker loop in `metrics-service`. |
| `GROQ_API_KEY` | ⚠️ Optional | — | API key for Groq Cloud LLM function calling (`llama-3.1-8b-instant`). |

---

## 8. Updating

### Routine Update (via CI/CD)

Simply push to `main`. The self-hosted runner handles everything.

```bash
git push origin main
```

### Manual Update on Server

```bash
cd ~/quan_ly_server
git pull origin main
docker compose up -d --build
```

### Updating Dependencies

Dependabot opens weekly PRs for:

- **npm packages** (frontend)
- **Maven dependencies** (backend, including Spring Boot BOM)
- **Docker base images**
- **GitHub Actions versions**

Review and merge these PRs to keep dependencies current.
