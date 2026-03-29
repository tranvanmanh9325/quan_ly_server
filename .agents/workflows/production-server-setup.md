---
description: configure and verify a clean production server, then trigger the first deployment
---

# Production Server Setup

## Prerequisites

- A Linux server (the machine that will host the dashboard)
- Git, Docker, and Docker Compose v2 installed on the server
- The server user added to the `docker` group (no `sudo` needed for `docker compose`)
- A GitHub repository with the self-hosted runner already registered

---

## Step 1 — Verify Docker Is Ready

SSH into the production server, then:

```bash
docker --version          # Must be 20.x or higher
docker compose version    # Must be v2.x
docker info               # Must not error (daemon is running)
```

If the user is not in the `docker` group:

```bash
sudo usermod -aG docker $USER
# Log out and back in for the group change to take effect
```

---

## Step 2 — Clone the Repository

```bash
cd ~
mkdir -p my-code && cd my-code
git clone https://github.com/<your-org>/quan_ly_server.git
cd quan_ly_server
```

---

## Step 3 — Create `backend/.env`

This file is NEVER committed. You must create it manually on the server.

```bash
cp backend/.env.example backend/.env
nano backend/.env   # or vim, or any editor you prefer
```

Fill in the real SSH connection values:

```env
SSH_HOST=your.actual.host.or.ngrok.address
SSH_PORT=22
SSH_USER=your_actual_username
SSH_PASSWORD=your_actual_password
```

Verify it is not committed (`.gitignore` must cover it):

```bash
git check-ignore -v backend/.env
# Expected: backend/.env is listed as ignored
```

---

## Step 4 — Register the GitHub Actions Self-Hosted Runner

On GitHub: **Settings → Actions → Runners → New self-hosted runner**

Follow the platform-specific instructions provided by GitHub.
The runner should be registered for this specific repository.

After installation, start the runner as a service:

```bash
# Use the GitHub-provided script, typically:
sudo ./svc.sh install
sudo ./svc.sh start
```

Verify the runner is **Online** in the GitHub Actions runner list.

---

## Step 5 — Perform the First Manual Deploy

Before trusting the auto-deploy pipeline, verify everything works manually:

```bash
cd ~/my-code/quan_ly_server
docker compose up -d --build
```

Monitor the startup:

```bash
docker compose ps
docker compose logs -f
```

Wait for both services to show `healthy`:

```text
NAME                STATUS
dashboard_backend   Up X minutes (healthy)
dashboard_frontend  Up X minutes (healthy)
```

Open the dashboard in your browser at `http://<server-ip>:5173`.

---

## Step 6 — Verify the Auto-Deploy Pipeline

Push a trivial documentation change to `main`:

```bash
# On your development machine:
git checkout main
# Make a trivial change, e.g. fix a typo in README.md
git commit -m "docs: verify auto-deploy pipeline"
git push origin main
```

On GitHub, navigate to **Actions** and confirm the `Auto Deploy to Ngrok Server`
workflow runs and completes successfully.

---

## Step 7 — Firewall Hardening (Recommended)

After confirming the stack works, restrict the backend port from public access:

```bash
# Example using ufw (Ubuntu):
sudo ufw allow 5173/tcp    # Dashboard — expose to clients
sudo ufw deny 8080/tcp     # Backend API — internal only (Nginx proxies it)
sudo ufw enable
```

> ⚠️ Port 8080 being publicly accessible is a known risk. See `SECURITY.md`
> and `.agents/rules/05-security.md` for full context and hardening steps.

---

## Step 8 — Confirm Runner Stays Online After Reboot

```bash
sudo reboot
# SSH back in after reboot
docker compose -f ~/my-code/quan_ly_server/docker-compose.yml ps
# Both services should auto-start due to: restart: unless-stopped
```

Verify the GitHub self-hosted runner also comes back online automatically.
