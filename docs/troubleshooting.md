# Troubleshooting Guide

A reference for diagnosing and resolving the most common issues encountered when running Mini Server Dashboard.

---

## Quick Diagnostic Commands

```bash
# Check status and health across all 6 containers
docker compose ps

# Follow logs for all services
docker compose logs -f

# Follow AI Agent logs (Facebook E2EE & Telegram)
docker compose logs -f ai-agent-service --tail=100

# Follow Metrics Service logs
docker compose logs -f metrics-service --tail=100

# Check AI Agent health directly
curl http://localhost:8084/health

# Check Metrics Service health
curl http://localhost:8082/actuator/health
```

---

## Issue Categories

- [Groq 429 Rate Limit & Multi-Key Pool Failover](#groq-429-rate-limit--multi-key-pool-failover)
- [Facebook E2EE: PIN Code Required / Decryption Failure](#facebook-e2ee-pin-code-required--decryption-failure)
- [Facebook Unsend: "Thu hồi" or Confirmation Button Not Found](#facebook-unsend-thu-hoi-or-confirmation-button-not-found)
- [noVNC Console: White Screen / Connection Refused on `:6080`](#novnc-console-white-screen--connection-refused-on-6080)
- [Dashboard shows "ERROR: no data returned from SSH"](#error-no-data-returned-from-ssh)
- [Dashboard shows "ERROR: \<exception message\>"](#error-connection-refused--timeout)
- [Backend container stuck in "starting" health state](#backend-stuck-in-starting)

---

## Groq 429 Rate Limit & Multi-Key Pool Failover

**Symptom:** AI Agent encounters rate limits when processing long queries.

**Mechanism & Fix:**
1. **Multi-Key Rotation:** Provide multiple keys (`GROQ_API_KEY`, `GROQ_API_KEY_2`, `GROQ_API_KEY_3`, ...) in `.env`.
2. **Smart 60s Cooldown:** The engine automatically marks rate-limited keys as cooling down and rotates to the next available key.
3. **OpenRouter Fallback:** If all Groq keys are exhausted, the system transparently routes requests to the `OPENROUTER_API_KEY` pool.

---

## Facebook E2EE: PIN Code Required / Decryption Failure

**Symptom:** Facebook Messenger sidebar is blank or shows "Nhập mã PIN để khôi phục đoạn chat".

**Diagnosis & Resolution:**
1. Ensure `FB_PIN` is set in `.env` matching your 6-digit Facebook E2EE PIN.
2. The AI Agent automatically types the PIN into the encrypted keypad.
3. If 2FA checkpoint occurs, open the **noVNC console** at `http://localhost:6080/vnc.html` (or via dashboard `/fb-vnc/`) and solve the checkpoint interactively.

---

## Facebook Unsend: "Thu hồi" or Confirmation Button Not Found

**Symptom:** Log shows `could not find confirm button in dialog` when revoking an away message.

**Resolution:**
1. The Playwright unsend engine uses localized text matching for Vietnamese locale (`Thu hồi` and `Gỡ`).
2. The engine uses full-page button locators (`get_by_text('Gỡ', exact=True)`) bypassing non-standard dialog container wrappers.
3. State is persisted in `facebook_known_threads` (`auto_reply_unsent = TRUE`), preventing duplicate unsend attempts.

---

## Groq 400 Bad Request

**Symptom:** Telegram bot replies: `"Xin lỗi, AI đã tạo câu lệnh không hợp lệ. Vui lòng thử hỏi lại."`

**Cause:** Groq generated nested double quotes (`"`) inside command string or invoked unsupported commands like `history`.

**Fix:**

1. System prompt strictly enforces single quotes (`'`) and bans `history` command.
2. Uses explicit timestamp commands (`stat /var/lib/apt/periodic/update-success-stamp`).
3. Automatically calls `clearHistory(chatId)` to unblock subsequent queries.

---

## Telegram Bot Polling Freeze

**Symptom:** Telegram bot hangs indefinitely without sending replies or printing logs.

**Cause:** `RestClient` using default `JdkClientHttpRequestFactory` without socket read timeouts, causing threads to park forever on dropped long-polling TCP connections.

**Fix:**

1. Configured `SimpleClientHttpRequestFactory` with 5s connect timeout and 12s/30s read timeouts in `TelegramBotService` and `TelegramNotificationService`.
2. Dedicated `SchedulingConfig` with 5 thread workers prevents single-thread blocking.

---

## Error: No Data Returned from SSH

**Symptom:** Cards display `ERROR: no data returned from SSH`.

**Backend log message:**

```
WARN  SshService - SSH stderr [top -b -n 1 | grep 'Cpu(s)']: ...
```

**Causes and fixes:**

| Cause | Fix |
| --- | --- |
| Shell command not found on remote host (e.g. `sensors`, `lscpu`) | Install the missing package: `sudo apt install lm-sensors util-linux` |
| SSH connected but command produces no stdout | Check the command manually: SSH into the server and run the command |
| Permission denied for the SSH user | Ensure the user has permission to run `ps`, `df`, `sensors`, `who`, etc. |

---

## Error: Connection Refused / Timeout

**Symptom:** Cards display `ERROR: Connection refused` or `ERROR: Connection timed out`.

**Backend log message:**

```
ERROR SshService - SSH thất bại sau 4 lần thử: Connection refused
```

**Causes and fixes:**

| Cause | Fix |
| --- | --- |
| Wrong `SSH_HOST` or `SSH_PORT` in `backend/.env` | Double-check the values; restart the backend after editing |
| Ngrok tunnel has expired or restarted | Update `SSH_HOST` and `SSH_PORT` with the new Ngrok address |
| Firewall blocking port 22 on the target server | Open the SSH port: `sudo ufw allow 22` |
| Target server is offline | Verify the server is reachable: `ping <SSH_HOST>` |
| Wrong credentials | Test manually: `ssh -p <SSH_PORT> <SSH_USER>@<SSH_HOST>` |

After fixing credentials in `backend/.env`, restart the backend:

```bash
docker compose restart backend
```

---

## Backend Stuck in "Starting"

**Symptom:** `docker compose ps` shows the backend with `health: starting` for more than 90 seconds.

**Diagnostic:**

```bash
docker compose logs backend --tail=50
```

**Common log messages and fixes:**

| Log message | Cause | Fix |
| --- | --- | --- |
| `APPLICATION FAILED TO START` | Missing required property (e.g. `SSH_HOST`) | Ensure `backend/.env` exists and all four variables are set |
| `java.net.SocketTimeoutException` | Backend started but SSH connection timed out | Backend will still become healthy; SSH errors don't affect Actuator health |
| `Port 8080 is already in use` | Another process occupies port 8080 on the host | Stop the conflicting process or change the host port in `docker-compose.yml` |

---

## Frontend Does Not Start

**Symptom:** `docker compose up` hangs or only the backend container starts.

**Cause:** `frontend` has `depends_on: backend: condition: service_healthy`. The frontend will not start until the backend returns a `healthy` status.

**Fix:** Wait for the backend to become healthy (up to 90 seconds). If it never becomes healthy, diagnose the backend first.

---

## All Metrics Show 0 / N/A After First Load

**Symptom:** The dashboard renders but all values are `0`, `N/A`, or loading indefinitely.

**Diagnostic steps:**

1. Open browser DevTools → Network tab.
2. Check if requests to `/api/metrics/cpu`, `/api/metrics/ram`, etc. return 200 or an error status.
3. Check the response body for `ERROR:` messages.

**Common causes:**

- SSH credentials in `backend/.env` are wrong → the SSH connection fails silently.
- The target server is offline.
- The Ngrok tunnel has a new address → update `.env`.

---

## Temperature and Voltage Show "N/A — sensors not found"

**Symptom:** Temperature and Voltage cards show the "N/A" empty state.

**Cause:** The `lm-sensors` package is not installed on the target Linux server.

**Fix:**

```bash
# On the Debian/Ubuntu target server
sudo apt install lm-sensors

# Run the auto-detect wizard
sudo sensors-detect
# Follow the prompts; load the detected modules
sudo systemctl restart kmod

# Verify
sensors
```

If the machine is a virtual machine or container, hardware sensors may not be exposed at all. The dashboard gracefully falls back to showing "N/A" in this case.

---

## Network Speed Always Shows 0 B/s

**Symptom:** The Network card always shows `0 B/s` for both download and upload.

**Cause:** Network speed is a delta calculation between two consecutive readings. The first reading will always show `0` because there is no previous snapshot. Speed will appear correctly from the second polling cycle (after ~10 seconds).

**If the issue persists beyond the first poll:**

1. Check that `/proc/net/dev` on the target server has active network interfaces beyond `lo`.
2. Look for errors in the browser console: `Lỗi lấy metrics: ...`
3. Verify the SSH connection is stable (transient disconnects cause the delta reference to reset).

---

## Process Table Empty or Stale

**Symptom:** The process table is empty, or data is much older than expected.

**Details:**

- The process table is polled **every 30 seconds** (not 10 s like other metrics).
- On the very first load, the process table may appear empty for up to a few seconds while the first fetch completes.

**If the table stays empty:**

1. Check the browser console for errors from the second `useEffect` (process effect).
2. Verify the SSH user has permission to run `ps -eo pid,user,%cpu,%mem,nlwp,rss,args`.
3. If the user is restricted (e.g. no `ps` access), switch to a privileged user in `.env`.

---

## Docker Build Fails (Maven Package Step)

**Symptom:** `docker compose up --build` fails with a Maven compilation error.

**Diagnostic:**

```bash
docker compose build backend 2>&1 | tail -50
```

**Common causes:**

| Error | Fix |
| --- | --- |
| `Could not resolve dependencies` | No internet access inside the Docker build context; ensure the Docker daemon can reach Maven Central |
| `Java version incompatibility` | The base image is pinned to Java 21; do not downgrade `java.version` in `pom.xml` |
| `Compilation error in source` | Fix the Java compilation error reported in the output |

To build with verbose Maven output:

```bash
docker build --no-cache --progress=plain ./backend
```

---

## Frontend Build Fails (Peer Dependency Error)

**Symptom:** `npm install` fails with a peer dependency conflict.

**Fix:** Always use the `--legacy-peer-deps` flag:

```bash
npm install --legacy-peer-deps
```

This is caused by a known conflict between `@eslint/js` and the `eslint` peer dependency resolution in npm v7+. The `--legacy-peer-deps` flag restores the npm v6 resolution behaviour.

This flag is already baked into the `frontend/Dockerfile`:

```dockerfile
RUN npm install --legacy-peer-deps
```

---

## Data Stops Updating

**Symptom:** The dashboard was working, but metrics stopped updating.

**Causes and fixes:**

| Cause | Diagnostic | Fix |
| --- | --- | --- |
| Browser tab was minimised/hidden | Open browser DevTools console — look for the adaptive interval log message | Simply bring the tab back into focus; polling resumes automatically |
| SSH session disconnected (e.g. Ngrok restart) | Check backend logs for `SSH lỗi (lần ...)` | Backend retries automatically; wait ~2–5 s. If Ngrok address changed, update `.env` |
| Backend container crashed | `docker compose ps` shows backend as "unhealthy" or "exited" | `docker compose restart backend`; check logs |
| Network timeout between browser and server | DevTools → Network tab shows pending/failed requests | Check server network connectivity |

---

## Useful Log Patterns

### SSH Reconnection in Progress

```
WARN  SshService - SSH lỗi (lần 1), thử lại sau 250ms: ...
WARN  SshService - SSH lỗi (lần 2), thử lại sau 500ms: ...
INFO  SshService - SSH: Đang tạo kết nối mới tới user@host:22
INFO  SshService - SSH: Kết nối thành công.
```

This is normal during a Ngrok tunnel restart. The backend recovers automatically.

### All Retries Exhausted

```
ERROR SshService - SSH thất bại sau 4 lần thử: Connection refused
```

The SSH target is unreachable. Check the `.env` credentials and target server status.

### Adaptive Interval Engaged (Frontend Console)

```
[Adaptive] SSH phản hồi 6234ms → chuyển interval sang 20s
```

SSH is responding slowly. The frontend automatically backs off to reduce load. This is normal under high server load or poor Ngrok latency.
