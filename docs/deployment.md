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

Edit `backend/.env` and fill in the credentials for the Linux host you want to monitor:

```dotenv
SSH_HOST=your.ssh.host.or.ngrok.address
SSH_PORT=22
SSH_USER=your_ssh_username
SSH_PASSWORD=your_ssh_password
```

> ⚠️ `.env` is listed in `.gitignore`. Never commit it.

### 1.3 Start the Backend

```bash
cd backend
mvn spring-boot:run
```

The API will be available at `http://localhost:8080`.

Test that it's working:

```bash
curl http://localhost:8080/actuator/health
# Expected: {"status":"UP"}
```

### 1.4 Start the Frontend

Open a second terminal:

```bash
cd frontend
npm install --legacy-peer-deps   # required due to eslint peer dependency conflict
npm run dev
```

The dashboard will be available at `http://localhost:5173`.

Vite automatically proxies all `/api/*` requests to `http://localhost:8080` (configured in `vite.config.js`), so no CORS errors occur during development.

### 1.5 Available Scripts (Frontend)

| Script | Command | Purpose |
| --- | --- | --- |
| Dev server | `npm run dev` | Start Vite dev server with HMR |
| Lint | `npm run lint` | Run ESLint |
| Build | `npm run build` | Produce optimised `dist/` output |
| Preview | `npm run preview` | Serve the built `dist/` locally |

---

## 2. Production Deployment (Docker Compose)

### 2.1 Clone on the Server

```bash
git clone https://github.com/<YOUR_USERNAME>/quan_ly_server.git ~/quan_ly_server
cd ~/quan_ly_server
```

### 2.2 Configure the Environment File

```bash
cp backend/.env.example backend/.env
nano backend/.env   # fill in SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD
```

> The `backend/.env` file must be present before running `docker compose up`. It is mounted at container runtime via the `env_file` directive in `docker-compose.yml`.

### 2.3 Build and Start All Services

```bash
docker compose up -d --build
```

This command:

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

### 2.5 Access the Dashboard

| Service | URL |
| --- | --- |
| Dashboard UI | `http://<server-ip>:5173` |
| Backend health | `http://<server-ip>:8080/actuator/health` |

---

## 3. Container Resource Limits

Defined in `docker-compose.yml` under the `deploy.resources` key.

| Container | CPU Limit | Memory Limit | Memory Reservation |
| --- | --- | --- | --- |
| `dashboard_backend` | 1.5 cores | 1 GB | 512 MB |
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

All variables are consumed by the backend only. They are loaded from `backend/.env` by Spring Boot via `spring.config.import=optional:file:.env[.properties]`, meaning they behave like normal Spring properties.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SSH_HOST` | ✅ Yes | — | Hostname or IP of the target Linux server. Can be a Ngrok TCP address (e.g. `0.tcp.ngrok.io`). |
| `SSH_PORT` | ✅ Yes | — | SSH port on the target server. Standard is `22`; Ngrok assigns ephemeral ports. |
| `SSH_USER` | ✅ Yes | — | SSH username on the target server. |
| `SSH_PASSWORD` | ✅ Yes | — | SSH password. For production, consider key-pair authentication instead (see Security Guide). |

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
