# Troubleshooting Guide

A reference for diagnosing and resolving the most common issues encountered when running Mini Server Dashboard.

---

## Quick Diagnostic Commands

```bash
# Check container status and health
docker compose ps

# Follow live logs for all services
docker compose logs -f

# Follow backend logs only
docker compose logs -f backend --tail=100

# Check backend API directly
curl http://localhost:8080/actuator/health

# Test a specific metric endpoint
curl http://localhost:8080/api/metrics/cpu
```

---

## Issue Categories

- [Dashboard shows "ERROR: no data returned from SSH"](#error-no-data-returned-from-ssh)
- [Dashboard shows "ERROR: \<exception message\>"](#error-connection-refused--timeout)
- [Telegram Bot: "AI đang quá tải" (Groq 429 Rate Limit)](#groq-429-rate-limit)
- [Telegram Bot: "Xin lỗi, AI đã tạo câu lệnh không hợp lệ" (Groq 400 Bad Request)](#groq-400-bad-request)
- [Telegram Bot stops responding / hangs on `updating..`](#telegram-bot-polling-freeze)
- [Backend container stuck in "starting" health state](#backend-stuck-in-starting)
- [Frontend container does not start after backend](#frontend-does-not-start)
- [All metrics show 0 / N/A after first load](#all-metrics-show-0--na-after-first-load)
- [Temperature and Voltage show "N/A — sensors not found"](#temperature-and-voltage-show-na--sensors-not-found)
- [Network speed always shows 0 B/s](#network-speed-always-shows-0-bs)
- [Process table is empty or stale](#process-table-empty-or-stale)
- [Docker build fails during Maven package step](#docker-build-fails-maven-package-step)
- [Frontend build fails with peer dependency errors](#frontend-build-fails-peer-dependency-error)
- [Dashboard loads but data stops updating](#data-stops-updating)

---

## Groq 429 Rate Limit

**Symptom:** Telegram bot replies: `"AI đang quá tải, vui lòng thử lại sau 1 phút."`

**Cause:** Groq free tier limit is 6,000 Tokens Per Minute (TPM). Large command outputs or long conversation histories exceed this limit.

**Fix:**

1. Capped `MAX_HISTORY_MESSAGES = 6` (3 Q&A pairs) and `MAX_OUTPUT_CHARS = 1000` in `AiChatService.java`.
2. Automatic 3-retry backoff with 2.5s delay.
3. Automatically clears conversation history on 429 errors.

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
