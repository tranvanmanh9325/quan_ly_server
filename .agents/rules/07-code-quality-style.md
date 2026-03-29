# Rule 07 — Code Quality & Style

## General Principles

- **DRY (Don't Repeat Yourself):** Before adding any helper, check if an
  equivalent already exists in `parsers.js` (frontend) or as a private
  method in the relevant Java class (backend).
- **No dead code:** Remove unused imports, commented-out blocks, and
  unreachable branches before merging.
- **No magic numbers / strings:** Define named constants for all thresholds,
  intervals, port numbers, and repeated string literals. See existing examples:
  `METRICS_INTERVAL_NORMAL`, `ADAPTIVE_THRESHOLD_MS` (frontend),
  `retryDelaysMs` (backend).
- **Fail loudly in dev, fail gracefully in production:** Guard against
  `null` at the boundary (SSH output → parser, parser → component),
  but do not suppress exceptions silently in application logic.

---

## Java Style

### Java Naming

| Construct | Convention | Example |
| --- | --- | --- |
| Class | `PascalCase` | `SshService`, `MetricsController` |
| Method | `camelCase`, verb prefix | `executeCommand`, `getOrCreateSession` |
| Field (instance) | `camelCase` | `sharedSession`, `host` |
| Constant | `UPPER_SNAKE_CASE` | `retryDelaysMs` (array — treat as constant) |
| Package | `lowercase.dotted` | `com.miniserver.dashboard.service` |

### Java Formatting

- Indentation: **2 spaces** (matching `pom.xml` and existing Java files).
- Line length: aim for ≤ 120 characters; hard wrap shell command strings
  with string concatenation as shown in `getSysInfo()`.
- Opening braces on the same line as the declaration.

### Java Comments

- Write comments in **Vietnamese** (project convention, consistent with
  the existing codebase).
- Only explain **WHY** — never explain what self-evident code does.
- Javadoc on public methods: brief `@param` and `@return` when the signature
  alone is not self-documenting.

### Java Logging Levels

| Situation | Level |
| --- | --- |
| Successful SSH connection | `INFO` |
| SSH stderr output from a command | `WARN` |
| Retry attempt | `WARN` |
| All retries exhausted | `ERROR` |
| Normal application flow | `DEBUG` (use sparingly) |

Never `INFO` inside a per-request hot path (e.g. inside `executeCommand`
per successful invocation) — that would flood logs during normal operation.

---

## JavaScript / JSX Style

### JS Naming

| Construct | Convention | Example |
| --- | --- | --- |
| Component | `PascalCase` | `App` |
| State variable | `camelCase` | `networkData`, `cpuHistory` |
| Ref | `camelCase` + `Ref` suffix | `lastNetRef`, `searchDebounceRef` |
| Event handler | `handle` prefix + `camelCase` | `handleSearchChange`, `handleRefresh` |
| Parser function | `parse` prefix or `get` prefix | `parseCpu`, `getMaxTemperature` |
| Module-level constant | `UPPER_SNAKE_CASE` | `METRICS_INTERVAL_NORMAL` |

### JS Formatting

- Indentation: **2 spaces**.
- Prefer **arrow functions** for anonymous callbacks.
- Prefer **optional chaining** (`?.`) over explicit null checks when
  reading nested response data.
- Avoid inline ternary chains longer than 2 levels — extract to a variable.

### JS Comments

- Write comments in **Vietnamese** (matching the existing codebase).
- Only explain WHY, not what.

---

## CSS Style

- Design tokens (CSS custom properties) are defined in `index.css`:
  `--accent-cyan`, `--accent-pink`, `--accent-purple`, `--glass-bg`,
  `--glass-border`, `--text-secondary`, etc.
- **Never hardcode colour hex/rgb values directly in JSX `style` props**
  if an equivalent token exists. Use `var(--accent-cyan)` etc.
- Exception: the brand colours used in Recharts `fill`/`stroke` props
  (e.g. `#00f0ff`) are acceptable because Recharts does not support CSS
  variables in SVG attributes.
- `App.css` holds component-scoped selectors. `index.css` holds global
  resets, tokens, and shared utility classes.
- Do not use `!important`. If specificity is a problem, restructure the selector.

---

## Adding a New Metric (full checklist)

When a new metric endpoint is needed:

**Backend:**

- [ ] Add a `GET` mapping in `MetricsController` (use `safeData()` for all
      string-output endpoints).
- [ ] Add the shell command string. If it requires a fallback, follow the
      `temperature` endpoint pattern (if/else shell conditional).
- [ ] Update `docs/api-reference.md` with the new endpoint.

**Frontend:**

- [ ] Add the `axios.get` call to the appropriate `Promise.all` (Effect 1
      for lightweight, Effect 2 for heavy).
- [ ] Add the parser to `parsers.js` as a pure function with full JSDoc.
- [ ] Add the new state variable and its initial value.
- [ ] Wire the parser output to state inside the effect.
- [ ] Add the UI card to `App.jsx`.
- [ ] Add the parser to the parsers table in Rule 03.
- [ ] Update `docs/api-reference.md` and `docs/frontend-internals.md`.

---

## Prohibited Patterns

| Pattern | Reason |
| --- | --- |
| `console.log` in production code | Use SLF4J (Java) or restrict to `console.error` (JS) |
| `setInterval` for polling | Cannot adapt interval dynamically; use `setTimeout` chains |
| Inline `fetch()` calls (bypassing Axios) | Breaks the consistent error-handling layer |
| `JSON.parse` on SSH output in Java | Parsing belongs in `parsers.js` |
| `@Autowired` on new fields in new classes | Use constructor injection |
| Storing state in a `ref` that should trigger re-render | Use `useState` |
| Using a state variable that should NOT trigger re-render | Use `useRef` |
| `window.location.reload()` for refresh | Use the `refreshTick` pattern |
