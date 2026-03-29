# Rule 06 — CI/CD & Git Workflow

## Branch Strategy

| Branch | Purpose | Merge target |
| --- | --- | --- |
| `main` | Production-ready code; triggers auto-deploy | — |
| Feature/fix branches | Development work | `main` via PR |

- Push directly to `main` only for **trivial documentation or config changes**.
- All non-trivial code changes must go through a PR with at least a
  self-review checklist completed.
- Never force-push to `main`.

---

## Auto-Deploy Pipeline (`deploy.yml`)

Triggered on: `push` to `main`
Runner: `self-hosted` (the production server itself)

```yaml
steps:
  - cd ~/my-code/quan_ly_server
  - git reset --hard          # discard any accidental local edits on the server
  - git pull origin main
  - docker compose up -d --build
```

### Why self-hosted?

The runner has direct filesystem access to `backend/.env`. No SSH secrets
need to be stored in GitHub — the runner is already on the target machine.

### Runner responsibilities

The self-hosted runner must:

1. Have Git, Docker, and Docker Compose v2 installed.
2. Have the `backend/.env` file in place at `~/my-code/quan_ly_server/backend/.env`.
3. Have permissions to run `docker compose` without `sudo` (user in `docker` group).
4. Be registered and online in the repository's runner list.

---

## Dependabot Configuration

Weekly PRs are opened for:

- `npm` — `/frontend` dependencies
- `maven` — `/backend` dependencies
- `docker` — all Dockerfile base images
- `github-actions` — Actions workflow dependencies

**Review policy for Dependabot PRs:**

1. Check the changelog for breaking changes.
2. For `spring-boot-starter-parent` version bumps, verify the new version
   is a GA release (not milestone/RC).
3. For `jsch` bumps, verify no regression in the SSH session lifecycle.
4. For `node` / `nginx` base image bumps in Dockerfiles, rebuild and smoke-test
   locally before merging.
5. Never auto-merge Dependabot PRs — always review manually.

---

## Commit Message Convention

Use the following format (Conventional Commits — simplified):

```text
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

Types:

| Type | When to use |
| --- | --- |
| `feat` | New feature or new API endpoint |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behaviour change |
| `perf` | Performance improvement |
| `docs` | Documentation only |
| `chore` | Tooling, CI, dependencies, config |
| `style` | Formatting only (no logic change) |

Scopes: `backend`, `frontend`, `docker`, `ci`, `docs`, `security`

Examples:

```text
feat(backend): add /api/metrics/uptime endpoint
fix(frontend): prevent negative rxSpeed when kernel counter wraps
chore(ci): bump node base image to 20.18-alpine
docs(security): document StrictHostKeyChecking trade-off
```

All commit messages must be in **English**.

---

## Pre-Merge Checklist

Before merging any PR to `main`, verify:

- [ ] `backend/.env` is NOT in the diff (check `git diff --name-only HEAD~1`)
- [ ] No hardcoded credentials, IPs, or hostnames added to source code
- [ ] `backend/.env.example` updated if new `SSH_*` vars were added
- [ ] `docker compose build` runs without errors locally or in CI
- [ ] `npm run lint` passes with no errors in `frontend/`
- [ ] The `SECURITY.md` file updated if a security trade-off was changed
- [ ] The relevant `docs/` file updated if an architectural decision changed

---

## Local Development Workflow

### Full stack (Docker)

```bash
# Build and start everything
docker compose up -d --build

# View backend logs
docker compose logs -f backend

# View frontend logs
docker compose logs -f frontend

# Rebuild only one service after a code change
docker compose up -d --build backend
```

### Backend only (local Spring Boot)

```bash
cd backend
# Requires backend/.env to be sourced or export vars manually
export $(cat .env | xargs)
./mvnw spring-boot:run
```

### Frontend only (Vite dev server)

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
# Proxies /api/* to http://localhost:8080
# Open http://localhost:5173
```

> **Note:** For the frontend dev server to work, the backend must be running
> on port 8080 (either locally or via Docker).
