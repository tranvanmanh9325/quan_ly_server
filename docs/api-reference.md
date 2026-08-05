# API Reference

Complete reference for all REST endpoints exposed by the backend.

**Base URLs:**

- Metrics Service: `http://<host>:8082/api/metrics`
- Auth Service: `http://<host>:8081/api/auth`
- File Service: `http://<host>:8083/api/files`

**Protocol:** HTTP/1.1
**Methods:** `GET`, `POST`, `PUT`, `DELETE`
**Authentication:** JWT Bearer Token (issued by Auth Service)
**Response format:** `application/json`

---

## Design Philosophy

The backend intentionally acts as a **thin SSH tunnel** — it executes a shell command and returns the raw stdout wrapped in a JSON envelope. All parsing is delegated to the frontend's `parsers.js`. This keeps the Java layer dependency-free of parsing logic and makes parsers independently unit-testable.

```json
// Standard response envelope
{ "data": "<raw shell output string>" }

// Structured response (sysinfo, connections only)
{ "key1": "value1", "key2": "value2" }
```

---

## Endpoints

### GET `/api/metrics/cpu`

Returns the CPU usage line from `top`.

**Shell command:** `top -b -n 1 | grep 'Cpu(s)'`

**Response:**

```json
{ "data": "%Cpu(s):  3.4 us,  1.2 sy,  0.0 ni, 94.8 id,  0.2 wa,  0.0 hi,  0.4 si,  0.0 st" }
```

**Frontend parser:** `parseCpu(raw)` → extracts the `id` (idle) percentage, returns `100 - idle` as a float clamped to `[0, 100]`.

**Error response:**

```json
{ "data": "ERROR: <exception message>" }
```

---

### GET `/api/metrics/ram`

Returns full memory statistics from `free`.

**Shell command:** `free -m`

**Response:**

```json
{ "data": "              total        used        free      shared  buff/cache   available\nMem:           7834        3201        1023         432        3610        4189\nSwap:          2047           0        2047" }
```

**Frontend parser:** `parseRam(raw)` → returns `{ total, used, free, cached, percent, swapTotal, swapUsed }` (all values in MB).

---

### GET `/api/metrics/disk`

Returns disk usage for all real block devices (excludes tmpfs and devtmpfs).

**Shell command:** `df -h -x tmpfs -x devtmpfs`

**Response:**

```json
{ "data": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        50G   18G   30G  37% /\n/dev/sda2       100G   45G   50G  48% /data" }
```

**Frontend parser:** `parseDisks(raw)` → returns `Array<{ totalStr, usedStr, percent, mountPoint }>`. Lines not starting with `/dev/` are skipped.

---

### GET `/api/metrics/network`

Returns raw interface statistics from the kernel proc filesystem.

**Shell command:** `cat /proc/net/dev`

**Response:**

```json
{ "data": "Inter-|   Receive                                                |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n   lo:  123456      1000    0    0    0     0          0         0   123456    1000    0    0    0     0       0          0\n eth0: 987654321  654321    0    0    0     0          0      1234  112233445   98765    0    0    0     0       0          0" }
```

**Frontend parser:** `parseNetwork(raw, lastRef)` → calculates `rxSpeed` / `txSpeed` (bytes/s) from the delta between the current reading and `lastRef` (stored in a `useRef`). Returns `{ rxSpeed, txSpeed, totalRx, totalTx, interfaceName }`. The loopback interface (`lo`) is excluded. Speed values are clamped to `≥ 0` to handle kernel counter wrap-around.

---

### GET `/api/metrics/processes`

Returns the full process list sorted by CPU usage descending.

**Shell command:** `ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu`

**Response:**

```json
{ "data": "    PID USER     %CPU %MEM NLWP    RSS ARGS\n   1234 root      5.2  0.8   10  81920 /usr/bin/java -jar app.jar\n   5678 www-data  0.1  0.3    2  12288 nginx: worker process" }
```

**Frontend parser:** `parseProcesses(raw)` → returns `Array<{ id, user, cpu, memPercent, threads, mem, name, args }>`. Memory (RSS) is converted from KB to MB. Updated every 30 seconds (separate polling loop from lightweight metrics).

---

### GET `/api/metrics/temperature`

Returns CPU/sensor temperature readings. Falls back to thermal zone sysfs entries if `sensors` is not installed.

**Shell command:**

```bash
if hash sensors 2>/dev/null; then
  sensors 2>/dev/null;
else
  for f in /sys/class/thermal/thermal_zone*/temp; do
    zone=$(echo $f | grep -oP 'thermal_zone\d+');
    val=$(cat $f 2>/dev/null);
    [ -n "$val" ] && echo "${zone}: ${val}";
  done;
fi
```

**Response (sensors installed):**

```json
{ "data": "coretemp-isa-0000\nAdapter: ISA adapter\nCore 0:        +44.0°C  (high = +80.0°C, crit = +100.0°C)\nCore 1:        +42.0°C  (high = +80.0°C, crit = +100.0°C)\nPackage id 0:  +46.0°C  (high = +80.0°C, crit = +100.0°C)" }
```

**Response (thermal_zone fallback):**

```json
{ "data": "thermal_zone0: 44000\nthermal_zone1: 42000" }
```

**Frontend parser:** `parseTemperature(raw)` → returns `Array<{ label, value, status }>`.

- `status`: `'ok'` (<70 °C) | `'warn'` (≥70 °C) | `'crit'` (≥85 °C)
- Virtual ACPI sensors stuck at 25 °C or 26.8 °C are filtered out.
- Fan, voltage, and power lines are excluded.

**If sensors not available:** returns `{ "data": "N/A" }`.

---

### GET `/api/metrics/voltage`

Returns voltage rail readings from `sensors`.

**Shell command:** `if hash sensors 2>/dev/null; then sensors 2>/dev/null; else echo 'N/A'; fi`

**Response:**

```json
{ "data": "it8728-isa-0228\nAdapter: ISA adapter\n+3.3V:         +3.328 V  (min =  +3.14 V, max =  +3.47 V)\n+5V:           +5.040 V  (min =  +4.75 V, max =  +5.25 V)\n+12V:         +12.168 V  (min = +11.40 V, max = +12.60 V)\nVcore:         +0.872 V  (min =  +0.68 V, max =  +1.60 V)" }
```

**Frontend parser:** `parseVoltage(raw)` → returns `Array<{ label, value, status }>`.

- Deviation thresholds from the nominal value: `>5%` → `'warn'`, `>10%` → `'crit'`.
- Nominal values are guessed from the rail label (e.g. `+12V` → 12 V) or measured value range.
- Temperature, fan, and power lines are excluded.

---

### GET `/api/metrics/system`

Returns the current uptime and load average.

**Shell command:** `uptime`

**Response:**

```json
{ "data": " 10:42:15 up 3 days,  4:17,  2 users,  load average: 0.18, 0.22, 0.15" }
```

**Frontend parser:** Parsed inline in `App.jsx` by the `formattedSystem` memo — splits on `load average:` and extracts the human-readable uptime duration.

---

### GET `/api/metrics/connections`

Returns a structured list of active SSH sessions.

**Shell command:** `who`

**Response:**

```json
{
  "data": [
    { "user": "alice", "terminal": "pts/0", "loginTime": "Mar 29 09:14", "ip": "192.168.1.42" },
    { "user": "bob",   "terminal": "pts/1", "loginTime": "Mar 29 10:01", "ip": "192.168.1.99" }
  ]
}
```

> **Note:** This is the only endpoint where parsing is performed in the backend (`MetricsController`). The `who` output has a predictable columnar format and a structured response is more ergonomic for the frontend.

---

### GET `/api/metrics/sysinfo`

Returns system identity fields, batched into a single SSH round-trip.

**Shell command (batched):**

```bash
printf 'KERNEL:%s\n' "$(uname -r)" && \
printf 'HOSTNAME:%s\n' "$(hostname)" && \
printf 'OS:%s\n' "$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')" && \
printf 'CPU_MODEL:%s\n' "$(lscpu 2>/dev/null | grep 'Model name' | sed 's/Model name[[:space:]]*:[[:space:]]//')"
```

**Response:**

```json
{
  "kernel":   "6.1.0-21-amd64",
  "hostname": "my-server",
  "os":       "Debian GNU/Linux 12 (bookworm)",
  "cpuModel": "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz"
}
```

> **Design note:** Batching four commands into one SSH call (`&&`-chained `printf`) reduces the number of SSH channel opens from 4 to 1, saving ~40–120 ms of channel setup latency per refresh cycle.

---

## Health Check

**Endpoint:** `GET /actuator/health`

Exposed by Spring Boot Actuator. Returns a simple health status without implementation details.

```json
{ "status": "UP" }
```

Used by Docker Compose's `healthcheck` to determine when the backend container is ready before the frontend starts.

---

## Error Handling

All endpoints follow a consistent error model:

| Scenario | Response |
| --- | --- |
| SSH connection fails (all retries exhausted) | `{ "data": "ERROR: <exception message>" }` |
| SSH command produces empty output | `{ "data": "ERROR: no data returned from SSH" }` |
| Sensors command not found | `{ "data": "N/A" }` (temperature, voltage) |
| Connections endpoint with no active sessions | `{ "data": [] }` |

The backend logs all SSH errors via SLF4J → Logback at `WARN` level (transient failures) or `ERROR` level (all retries exhausted). Stderr captured from remote commands is also logged at `WARN`. Logs are visible via `docker compose logs backend`.
