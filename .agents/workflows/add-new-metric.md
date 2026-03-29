---
description: add a new metric endpoint end-to-end (backend controller → SSH command → frontend parser → UI card)
---

# Add a New Metric

This workflow walks through every layer that must be touched when adding a new
monitoring metric to the dashboard. Follow each step in order to avoid missing
a layer and breaking the established data contract.

---

## Step 1 — Backend: Add the SSH command to `MetricsController`

File: `backend/src/main/java/com/miniserver/dashboard/controller/MetricsController.java`

1. Add a new `@GetMapping` method. Use `safeData()` for all string-output endpoints.
   The Java layer is a **thin tunnel** — execute the command, return the raw string.
   **No parsing in Java.**

```java
// Ví dụ: thêm endpoint /api/metrics/your-metric
@GetMapping("/your-metric")
public Map<String, String> getYourMetric() {
    // Command shell lấy dữ liệu, thêm 2>/dev/null nếu lệnh có thể không tồn tại
    String result = sshService.executeCommand("your-shell-command 2>/dev/null");
    return safeData(result);
}
```

1. If the command requires a fallback (e.g. tool may not be installed on the remote
   server), use a shell conditional — see the `/temperature` endpoint as reference:

```java
String cmd = "if command -v your-tool &>/dev/null; then your-tool; " +
             "else cat /sys/class/fallback/path 2>/dev/null; fi";
```

1. For **compound commands** that batch multiple queries into one SSH round-trip
   (reduces latency), follow the `/sysinfo` endpoint pattern using `printf` separators.

---

## Step 2 — Backend: Update `docs/api-reference.md`

Add the new endpoint to the API reference table with:

- Route
- Method
- Description
- Response shape example

---

## Step 3 — Frontend: Add the parser to `parsers.js`

File: `frontend/src/utils/parsers.js`

1. Write a **pure function** that takes only raw strings and returns a defined shape.
   It must never throw — guard against `null`, blank, or malformed input.

```js
/**
 * Parses raw output of `your-shell-command`.
 * @param {string} raw - Raw stdout from SSH command.
 * @returns {{ value: number, unit: string } | null}
 */
export function parseYourMetric(raw) {
  if (!raw || raw.startsWith('ERROR')) return null;
  // ... parsing logic ...
}
```

1. Add the new function to the parsers table in `.agents/rules/03-frontend-react.md`.

---

## Step 4 — Frontend: Add state and wire the API call in `App.jsx`

File: `frontend/src/App.jsx`

1. Add a new `useState` for the metric:

```jsx
const [yourMetricData, setYourMetricData] = useState(null);
```

1. Add the `axios.get` call inside the correct `Promise.all`:

   - **Effect 1** (every 10–20 s): for lightweight metrics (CPU, RAM, network, etc.)
   - **Effect 2** (every 30 s): for heavy metrics (process list)

```jsx
// Inside the appropriate Promise.all([...]) array:
axios.get(`${API_BASE}/your-metric`),
```

1. In the `.then(([...responses]) => { ... })` destructure, add your response and parse it:

```jsx
const [/* existing */, yourMetricRes] = responses;
setYourMetricData(parseYourMetric(yourMetricRes.data?.data));
```

---

## Step 5 — Frontend: Add the UI card in `App.jsx`

Add the visual card in the JSX return:

- Use existing CSS tokens (`var(--accent-cyan)`, `var(--glass-bg)`, etc.)
- Never hardcode colour values — use CSS custom properties (exception: Recharts SVG attrs).
- Place the card in a logical position relative to related metrics.

```jsx
<div className="card">
  <h3>Your Metric Title</h3>
  {yourMetricData ? (
    <p>{yourMetricData.value} {yourMetricData.unit}</p>
  ) : (
    <p className="text-secondary">Loading...</p>
  )}
</div>
```

---

## Step 6 — Update Documentation

- [ ] `docs/api-reference.md` — new endpoint row (done in Step 2)
- [ ] `docs/frontend-internals.md` — new state variable and parser description
- [ ] `.agents/rules/03-frontend-react.md` — add parser to the parsers table
- [ ] `.agents/rules/07-code-quality-style.md` — mark checklist items done (for reference)

---

## Step 7 — Quality Gates

```bash
# 1. Lint the frontend
cd frontend && npm run lint

# 2. Verify backend compiles
cd backend && mvn clean package -DskipTests

# 3. Full stack integration test
docker compose up -d --build
# Check the new card appears in the dashboard at http://localhost:5173
# Check backend logs for SSH errors
docker compose logs -f backend
```

---

## Commit Message Template

```text
feat(backend): add /api/metrics/your-metric endpoint
feat(frontend): add YourMetric card with parseYourMetric parser
```

Or squash into one commit if the feature is small:

```text
feat: add your-metric monitoring (backend + frontend)
```
