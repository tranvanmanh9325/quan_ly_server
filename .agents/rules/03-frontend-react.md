# Rule 03 — Frontend React / JavaScript Conventions

## File & Module Structure

```text
frontend/src/
├── App.jsx          ← Single root component (UI assembly + polling effects)
├── App.css          ← Component-scoped styles
├── index.css        ← Global design tokens, resets, shared utilities
├── main.jsx         ← React DOM root mount
└── utils/
    └── parsers.js   ← Pure parse functions for all SSH raw output
```

Do not create sub-directories for components or pages yet.
When `App.jsx` exceeds ~1 000 lines **after** refactoring, split it into
dedicated component files under `src/components/`. Open a PR discussion
before doing so.

---

## React Hooks Rules

### Polling effects

The app has **two separate `useEffect` polling loops** — this split is
intentional and must be preserved:

| Effect | Interval | Data fetched |
| --- | --- | --- |
| Effect 1 (lightweight metrics) | 10 s (adaptive → 20 s) | system, cpu, ram, disk, network, connections, temperature, voltage, sysinfo |
| Effect 2 (process list) | 30 s | processes (`ps` — heavier command) |

Both effects **must** include:

- An `isMounted` flag to prevent state updates after unmount.
- An `isFetching` / `isFetchingProcs` guard to prevent overlapping calls.
- `setTimeout` chain (not `setInterval`) to allow dynamic interval changes.
- Visibility API integration (`document.visibilityState === 'hidden'` skip + `visibilitychange` resume).
- Proper cleanup in the return function: `isMounted = false`,
  `clearTimeout(timerId)`, `removeEventListener`.

**Never replace `setTimeout` with `setInterval`** — the adaptive interval
logic cannot work with fixed intervals.

### State and refs

| Piece of state | Type | Notes |
| --- | --- | --- |
| `cpuHistory` | `Array<{name, value}>` (length 15) | Ring-buffer, never grows beyond 15 |
| `ramData` | object | `{total, used, free, cached, percent, swapTotal, swapUsed}` — all in MB |
| `diskData` | `Array<{percent, usedStr, totalStr, mountPoint}>` | Parsed by `parseDisks` |
| `networkData` | object | `{rxSpeed, txSpeed, totalRx, totalTx, interfaceName}` |
| `lastNetRef` | `useRef` | `{rx, tx, time}` — stores previous poll snapshot for speed calculation |
| `temperatureData` | `Array<{label, value, status}>` | Parsed by `parseTemperature` |
| `voltageData` | `Array<{label, value, status}>` | Parsed by `parseVoltage` |
| `sysInfo` | object | `{kernel, hostname, os, cpuModel}` — all strings, default `'N/A'` |
| `processes` | `Array<{id, user, cpu, memPercent, threads, mem, name, args}>` | Sorted by CPU% descending |

Do not rename or reshape these state items without also updating all
downstream parsers and consumers.

### `useCallback` / `useMemo`

- `handleSearchChange` — `useCallback([], [])`: debounces search input at
  300 ms. Do not replace with an `onChange` inline handler.
- `formattedSystem` — `useMemo([system])`: parses uptime string. Keep it
  memoised to avoid re-parsing on every unrelated render.

---

## `parsers.js` Contract

All functions in `parsers.js` are **pure functions** — they must:

- Take raw string(s) only; never access `window`, `document`, or React state.
- Return the exact shape documented in their JSDoc `@returns`.
- Never throw — guard against `null`, blank, or malformed input.
- Be independently unit-testable with plain string fixtures.

### Existing parsers (do not change signatures)

| Function | Input | Output |
| --- | --- | --- |
| `parseCpu(raw)` | `top -bn1` stdout | `number` (0–100) |
| `parseRam(raw)` | `free -m` stdout | `{total, used, free, cached, percent, swapTotal, swapUsed}` |
| `parseDisks(raw)` | `df -h` stdout | `Array<{percent, usedStr, totalStr, mountPoint}>` |
| `parseNetwork(raw, lastRef)` | `/proc/net/dev` stdout + previous ref | `{rxSpeed, txSpeed, totalRx, totalTx, interfaceName}` |
| `parseProcesses(raw)` | `ps` stdout | `Array<{id, user, cpu, memPercent, threads, mem, name, args}>` |
| `parseTemperature(raw)` | `sensors` or `thermal_zone` stdout | `Array<{label, value, status}>` |
| `getMaxTemperature(temps)` | output of `parseTemperature` | `string \| null` |
| `parseVoltage(raw)` | `sensors` stdout | `Array<{label, value, status}>` |

When adding a new parser: add it to this table in the rule.

---

## API Contract

All API calls target `const API_BASE = '/api/metrics'`.
Endpoints and their expected response shapes:

| Route | Response shape |
| --- | --- |
| `GET /cpu` | `{ data: string }` |
| `GET /ram` | `{ data: string }` |
| `GET /disk` | `{ data: string }` |
| `GET /network` | `{ data: string }` |
| `GET /processes` | `{ data: string }` |
| `GET /temperature` | `{ data: string }` |
| `GET /voltage` | `{ data: string }` |
| `GET /system` | `{ data: string }` |
| `GET /connections` | `{ data: Array<{user, terminal, loginTime, ip}> }` |
| `GET /sysinfo` | `{ kernel, hostname, os, cpuModel }` |

Always access via `response.data?.data` (optional chain) — never assume
the field is always present.

---

## Adaptive Polling Constants

```js
const METRICS_INTERVAL_NORMAL = 10_000; // ms
const METRICS_INTERVAL_SLOW   = 20_000; // ms — triggered when SSH > 5 s
const PROCESS_INTERVAL        = 30_000; // ms
const ADAPTIVE_THRESHOLD_MS   = 5_000;  // ms — threshold to switch to slow
```

Do not change these without a performance analysis of SSH round-trip times.
These constants must live at the module top-level (not inside any function).

---

## Search / Filter

- Process search debounce is **300 ms** (implemented via `useRef` timeout).
- Filters by `p.name`, `p.user`, and `p.id.toString()`.
- Do not change the debounce target or add server-side filtering —
  the full list from the last poll is already in React state.

---

## ESLint Rules

Config: `eslint.config.js` (ESLint 9 flat config format, never `.eslintrc`).

Active rule overrides:

```js
'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }]
```

This allows uppercase constants (e.g., `METRICS_INTERVAL_NORMAL`) to be
declared without ESLint complaints even if used only in certain scopes.
Do not disable `react-hooks/exhaustive-deps` or `react-hooks/rules-of-hooks`.

---

## Vite Config

```js
server: {
  proxy: {
    '/api': { target: 'http://localhost:8080', changeOrigin: true }
  }
}
```

- Do not change the proxy target — it points to the local Spring Boot dev server.
- Do not set `port` in Vite config — the default `5173` aligns with `CorsConfig`.

---

## Frontend Dockerfile Rules

- Builder stage: `node:20-alpine`
- Install with `npm install --legacy-peer-deps` (required due to ESLint 9
  peer dependency chain conflicts).
- Runtime stage: `nginx:alpine` — copy only `dist/` contents to
  `/usr/share/nginx/html`.
- Replace default Nginx config with `nginx.conf` (see Rule 04).
- Expose port 80 only. Never expose the Vite dev port (5173) from Nginx.
