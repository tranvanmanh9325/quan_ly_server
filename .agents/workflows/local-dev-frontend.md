---
description: run frontend locally with Vite dev server (proxies /api/* to localhost:8080)
---

# Local Dev — Frontend (Vite)

## Prerequisites

- Node.js 20+ — `node -v` must report `20.x` or higher
- The backend must be running on `http://localhost:8080` (see `local-dev-backend.md`
  or `local-dev-fullstack-docker.md`). Vite will proxy all `/api/*` requests to it.

---

## Steps

1. Navigate to the `frontend` directory.

```bash
cd frontend
```

1. Install dependencies.
   The `--legacy-peer-deps` flag is required due to a peer dependency conflict
   between `@eslint/js` and `eslint` in the ESLint 9 flat config ecosystem.

```bash
npm install --legacy-peer-deps
```

> Skip this step if `node_modules/` already exists and `package.json` has not changed.

1. Start the Vite dev server.

```bash
npm run dev
```

1. Open the dashboard in your browser:

```text
http://localhost:5173
```

The Vite proxy (`vite.config.js`) forwards all `/api/*` requests to
`http://localhost:8080`, so no CORS issues occur during development.

---

## Linting

Run ESLint before committing any frontend changes:

```bash
npm run lint
```

There must be zero errors. Warnings should be addressed where possible.

---

## Stopping

Press `Ctrl+C` in the terminal to stop the Vite process.

---

## Notes

- Do NOT set a custom `port` in `vite.config.js`. The default `5173` is the
  value configured in `CorsConfig.java` and the backend CORS whitelist.
- Hot Module Replacement (HMR) is active — changes to `.jsx` and `.css`
  files reflect immediately in the browser without a full reload.
- If you see a blank page, confirm the backend is healthy at
  `http://localhost:8080/actuator/health`.
