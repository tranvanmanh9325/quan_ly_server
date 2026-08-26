# Frontend Internals

A technical reference for the React frontend: state management, polling architecture, component structure, and the parser utility layer.

---

## Tech Stack

| Concern | Library | Version |
| --- | --- | --- |
| UI framework | React | 19 |
| Build tool | Vite | 8 |
| HTTP client | Axios | 1 |
| Charts | Recharts | 3 |
| 3D Globe | D3-geo + TopoJSON | 3 / 3 |
| Icons | Custom Sci-Fi SVG system (`SciFiIcons.jsx`) + Lucide React | latest |
| Audio & FX | Web Audio API + HTML5 Canvas | Native browser APIs |
| Production server | Nginx Alpine | latest |

---

## File Structure

```text
frontend/src/
├── main.jsx                       ← React DOM entry point — mounts <App /> into #root
├── App.jsx                        ← Root layout, routing outlet, global state & context
├── App.css                        ← Component-level styles (layout, cards, table, modal, responsive)
├── index.css                      ← Global CSS variables (design tokens), resets, base styles
├── components/
│   ├── SciFiIcons.jsx             ← Custom SVG vector icon library (SciFiShield, SciFiLightning, etc.)
│   ├── SpaceInteractionLayer.jsx  ← Global rotating crosshair, canvas shockwaves & Web Audio laser FX
│   └── modals/                    ← Process termination, Docker log viewer modals
├── pages/
│   ├── OverviewPage.jsx           ← Real-time telemetry overview, KPI cards & multi-sensor Fan HUD
│   ├── ProcessesPage.jsx          ← Live process monitor, CPU/Mem filters & CSV export
│   ├── ServicesPage.jsx           ← Systemd units, container states, timers & host runtimes
│   ├── ContainersPage.jsx         ← Dedicated Docker container manager & live log streaming
│   ├── TerminalPage.jsx           ← Web SSH Terminal with macro chips & command sandbox
│   ├── MapPage.jsx                ← 3D Interactive Orthographic Globe & active SSH node tracer
│   ├── SecurityPage.jsx           ← Listening ports (ss), active sessions (who), colorized logs
│   ├── FilesPage.jsx              ← Remote SFTP file browser & syntax-highlighted viewer
│   ├── FacebookPage.jsx           ← Facebook E2EE threads, appointment manager & embedded noVNC viewer
│   ├── TikTokPage.jsx             ← TikTok streak keeper, automated DM logs & configuration
│   └── SettingsPage.jsx           ← Alert threshold sliders, polling speed & AI bot controls
└── utils/
    ├── parsers.js                 ← Pure functions: raw SSH text → typed JavaScript objects
    ├── audioFx.js                 ← Synthesized Web Audio laser chirps & sub-bass feedback
    └── api.js                     ← Axios instance with JWT interceptors & error handlers
```

---

## Global Design System (`index.css`)

All colour and spacing values are defined as CSS custom properties to ensure consistency across components without a CSS-in-JS library.

| Variable | Purpose |
| --- | --- |
| `--bg-dark` | Main dark background colour |
| `--glass-bg` | Glassmorphism panel background (semi-transparent) |
| `--glass-border` | Panel border colour |
| `--glass-highlight` | Highlight surface inside glass panels |
| `--accent-cyan` | Primary accent colour — CPU charts, links, highlights |
| `--accent-pink` | Secondary accent — critical alerts, upload speed |
| `--accent-purple` | Tertiary accent — disk usage bars, memory labels |
| `--text-primary` | Main readable text |
| `--text-secondary` | Muted labels and captions |
| `--transition-speed` | Shared animation duration for hover effects |

---

## State Management

All state lives in the single `App` component (no external state library). The state is divided by concern:

### Metric State

| State | Type | Description |
| --- | --- | --- |
| `cpuHistory` | `Array<{name, value}>` | Rolling 15-point window for the area chart |
| `ramData` | `{ total, used, free, cached, percent, swapTotal, swapUsed }` | Memory breakdown (MB) |
| `diskData` | `Array<{ totalStr, usedStr, percent, mountPoint }>` | Per-partition disk info |
| `networkData` | `{ rxSpeed, txSpeed, totalRx, totalTx, interfaceName }` | Speeds in bytes/s |
| `temperatureData` | `Array<{ label, value, status }>` | Per-sensor readings |
| `voltageData` | `Array<{ label, value, status }>` | Per-rail voltage readings |
| `processes` | `Array<{ id, user, cpu, memPercent, threads, mem, name, args }>` | Process list |
| `system` | `string` | Raw `uptime` output |
| `sysInfo` | `{ kernel, hostname, os, cpuModel }` | System identity |
| `connections` | `Array<{ user, terminal, loginTime, ip }>` | Active SSH sessions |

### UI State

| State | Type | Description |
| --- | --- | --- |
| `isServerModalOpen` | `boolean` | Controls the Server Info detail modal |
| `selectedConnection` | `object \| null` | Controls the Connection detail modal |
| `searchInput` | `string` | Immediate value bound to the search input |
| `searchTerm` | `string` | Debounced (300 ms) value used for filtering |
| `refreshTick` | `number` | Incrementing counter used as `useEffect` dependency to trigger a manual refresh |

### Refs

| Ref | Purpose |
| --- | --- |
| `lastNetRef` | Stores the last network counter snapshot `{ rx, tx, time }` for speed delta calculation — a `ref` instead of state because updating it must not trigger a re-render |
| `searchDebounceRef` | Stores the `setTimeout` ID for search debounce cancellation |
| `refreshCounterRef` | Source of truth for `refreshTick` (avoids stale closure issues) |

---

## Polling Architecture

### Effect 1 — Lightweight Metrics (every 10 s, adaptive)

Fetches all lightweight endpoints in a single `Promise.all`:

```
system, cpu, ram, disk, network, connections, temperature, voltage, sysinfo
```

**Key behaviours:**

- Uses `setTimeout` chains (not `setInterval`) so the next fetch only schedules after the previous one completes. This prevents request pile-up if SSH is slow.
- **Adaptive backoff:** Measures wall-clock time of the `Promise.all`. If response time exceeds `ADAPTIVE_THRESHOLD_MS` (5 000 ms), the interval doubles from 10 s to 20 s.

```javascript
const METRICS_INTERVAL_NORMAL = 10_000;  // default
const METRICS_INTERVAL_SLOW   = 20_000;  // auto-applied when SSH > 5 s
const ADAPTIVE_THRESHOLD_MS   = 5_000;   // trigger threshold
```

- **Visibility API:** When `document.visibilityState === 'hidden'`, the next `schedule()` call sleeps for 1 s and checks again — no SSH calls are made. Resumes immediately on `visibilitychange` to `'visible'`.
- **No concurrent fetches:** An `isFetching` guard ensures a second call is skipped if the previous one hasn't finished.
- **`refreshTick` dependency:** The effect re-runs whenever the user clicks **Refresh**, resetting all timers and fetching immediately.

### Effect 2 — Process List (every 30 s, isolated)

The `ps` command with full `args` output is heavier than the other commands. It runs in a separate effect with its own `setTimeout` chain at a 30 s interval. The two effects are independent so a slow process fetch does not delay metric updates.

---

## Parser Utilities (`parsers.js`)

All functions are **pure** (no side effects, no global state). They accept a raw string and return a typed value.

### `parseCpu(raw: string): number`

**Input:** One line from `top -bn1` containing `Cpu(s)`.
**Output:** CPU usage percentage `(0–100)`.

**Algorithm:** Extracts the `id` (idle) field via regex `(\d+\.\d+)\s+id`, computes `100 - idle`, clamps to ≥ 0.

---

### `parseRam(raw: string): object`

**Input:** Full output of `free -m`.
**Output:** `{ total, used, free, cached, percent, swapTotal, swapUsed }` (all in MB).

**Algorithm:** Splits on newlines. Line index 1 → Mem row columns `[total, used, free, _, _, cached]`. Line index 2 → Swap row if it starts with `Swap:`.

---

### `parseDisks(raw: string): Array`

**Input:** Output of `df -h -x tmpfs -x devtmpfs`.
**Output:** `Array<{ totalStr, usedStr, percent, mountPoint }>`.

**Algorithm:** Skips header (index 0) and any lines not starting with `/dev/`. Uses fixed column indices from `df -h`'s consistent format: `[0]=Filesystem [1]=Size [2]=Used [3]=Avail [4]=Use% [5+]=Mounted`.

---

### `parseNetwork(raw: string, lastRef: object): object`

**Input:** Output of `cat /proc/net/dev` + previous snapshot `{ rx, tx, time }`.
**Output:** `{ rxSpeed, txSpeed, totalRx, totalTx, interfaceName }`.

**Algorithm:**

1. Skip the two header lines and the loopback interface (`lo:`).
2. Sum all interface RX (column 0) and TX (column 8) bytes.
3. Identify the interface with the highest RX as the "primary" interface name.
4. Speed = `(current - last) / timeDiffSeconds`.
5. Clamp to ≥ 0 to guard against kernel counter wrap or container restart.

---

### `parseProcesses(raw: string): Array`

**Input:** Output of `ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu`.
**Output:** `Array<{ id, user, cpu, memPercent, threads, mem, name, args }>`.

**Algorithm:** Skips header, splits each line on whitespace. Converts RSS (KB) to MB. Falls back gracefully if a line has fewer than 7 fields.

---

### `parseTemperature(raw: string): Array`

**Input:** Either `sensors` text output or `thermal_zone: millidegrees` lines.
**Output:** `Array<{ label, value, status }>` — sorted by sensor output order.

**Algorithm:**

- Primary regex: matches `sensors` format `Label: +XX.X°C (...)`.
- Fallback regex: matches `thermal_zoneN: NNNNN` (millidegrees → divide by 1000).
- Filters: excludes fan/rpm/volt/power lines; excludes values ≤ 0 or > 120 °C; excludes ACPI virtual sensors stuck at 25 °C / 26.8 °C.
- Status thresholds: `ok` < 70 °C, `warn` ≥ 70 °C, `crit` ≥ 85 °C.

---

### `getMaxTemperature(temps: Array): string | null`

Selects the most representative temperature from a `parseTemperature` result.

**Priority:**

1. First entry matching `/package|tdie|tctl|cpu thermal/i` (chip-package sensor).
2. Fallback: numerically highest value in the array.

Used to display a single inline temperature reading on the CPU card and in the Server Info modal.

---

### `parseVoltage(raw: string): Array`

**Input:** `sensors` text output.
**Output:** `Array<{ label, value, status }>`.

**Algorithm:**

- Regex: matches lines with a voltage unit `Label: +X.XXX V`.
- Filters: excludes temp/fan/rpm/power/watt/curr lines.
- Status: `guessNominalVoltage(label, measuredV)` infers the expected rail voltage from the label name or measured value range, then flags `warn` (>5% deviation) or `crit` (>10% deviation).

---

## Responsive Layout

The UI uses a CSS Grid layout with three responsive breakpoints:

| Breakpoint | Layout |
| --- | --- |
| `> 1200 px` | Two-column grid: main area (2fr) + right sidebar (1fr) |
| `≤ 1200 px` (tablet) | Single column; right sidebar switches to `auto-fit` grid of panels |
| `≤ 768 px` (mobile) | Reduced padding; KPI cards in a 150 px minimum grid |
| `≤ 480 px` (small mobile) | All grids collapse to single column; modals use 95% width |

The `min-height: 0` rule on `.dashboard-grid` is critical — without it, a flex child with `overflow-y: auto` cannot shrink below its content height, causing the page to grow beyond the viewport.

---

## Key UI Components

### KPI Cards (`kpi-card glass-panel`)

Each metric (CPU, RAM, Disk, Network, Voltage, Temperature) is rendered as a card with:

- A title label and a current value badge
- An inline chart (Recharts `AreaChart` for CPU, `PieChart` for RAM) or a custom bar/list for others
- Hover lift effect via CSS `translateY(-2px)` transition

### Process Table (`glass-table`)

- Sticky `thead` with a white background and box shadow for scroll context
- Filtered by the debounced `searchTerm` across PID, name, and user columns
- Max height 400 px with vertical scroll

### Modals

Two modals are rendered inline in `App.jsx`:

- **Connection Detail Modal** — triggered by clicking an active connection item
- **Server Info Modal** — triggered by clicking the Server Info card; shows all live metrics in a structured detail view

Both use a `modal-overlay` backdrop with `backdrop-filter: blur(5px)` and a `modalFadeIn` entry animation.
