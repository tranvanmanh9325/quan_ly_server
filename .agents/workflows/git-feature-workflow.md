---
description: full Git workflow for developing a feature or fix and merging it to main via PR
---

# Git Feature Workflow

## Branch Naming Convention

```text
feat/<short-description>       # New feature
fix/<short-description>        # Bug fix
refactor/<short-description>   # Refactoring without behaviour change
docs/<short-description>       # Documentation only
chore/<short-description>      # Tooling, CI, config, dependency updates
```

Examples: `feat/add-uptime-endpoint`, `fix/network-speed-counter-wrap`, `docs/update-api-reference`

---

## Steps

### 1. Start from a clean, up-to-date main

```bash
git checkout main
git pull origin main
```

### 2. Create and checkout your feature branch

```bash
git checkout -b feat/your-feature-name
```

### 3. Make your changes

Follow the project rules in `.agents/rules/` before writing code.

Key checks while coding:

- Backend changes → follow `.agents/rules/02-backend-java.md`
- Frontend changes → follow `.agents/rules/03-frontend-react.md`
- New metric → follow the "Adding a New Metric" checklist in `.agents/rules/07-code-quality-style.md`

### 4. Run quality gates locally before committing

```bash
# Frontend lint — must be zero errors
cd frontend && npm run lint && cd ..

# Backend compile check (optional but recommended before push)
cd backend && mvn clean package -DskipTests && cd ..

# Docker build check (confirm no breakage)
docker compose build
```

### 5. Stage and commit

Use Conventional Commits format:

```text
<type>(<scope>): <short description, imperative, ≤ 72 chars>

[optional body — explain WHY, not WHAT]
```

**Types:** `feat`, `fix`, `refactor`, `perf`, `docs`, `chore`, `style`  
**Scopes:** `backend`, `frontend`, `docker`, `ci`, `docs`, `security`

```bash
git add <specific files>   # Never use "git add ." blindly — verify git status first
git commit -m "feat(backend): add /api/metrics/uptime endpoint"
```

> ⚠️ **Before every commit:** run `git status` and confirm `backend/.env` is NOT staged.

### 6. Push your branch

```bash
git push origin feat/your-feature-name
```

### 7. Open a Pull Request on GitHub

- Title: same as your commit message convention (`feat(backend): ...`)
- Description: describe WHAT changed and WHY
- Self-review checklist (copy into the PR body):

```markdown
**Pre-Merge Checklist:**
- [ ] `backend/.env` is NOT in the diff
- [ ] No hardcoded credentials, IPs, or hostnames added
- [ ] `backend/.env.example` updated if new `SSH_*` vars were added
- [ ] `docker compose build` runs without errors
- [ ] `npm run lint` passes with zero errors in `frontend/`
- [ ] `SECURITY.md` updated if a security trade-off changed
- [ ] Relevant `docs/` file updated if an architectural decision changed
- [ ] Rule files in `.agents/rules/` updated if a pattern changed
```

### 8. Merge to main

After self-review is complete:

- Merge via **Squash and Merge** for clean history on single-commit features.
- Merge via **Merge Commit** for multi-commit branches where history is meaningful.
- **Never force-push to `main`.**

### 9. Auto-deploy triggers automatically

Once merged to `main`, the GitHub Actions workflow (`.github/workflows/deploy.yml`)
runs the self-hosted runner, which executes:

```bash
cd ~/my-code/quan_ly_server
git reset --hard
git pull origin main
docker compose up -d --build
```

Monitor the Actions tab on GitHub to confirm the deploy succeeds.

---

## Hotfix Flow (urgent production fix)

For critical fixes that cannot wait for a full PR cycle:

```bash
git checkout main
git pull origin main
git checkout -b fix/critical-description

# Make the minimal fix
git add <files>
git commit -m "fix(backend): handle null SSH response in executeCommand"
git push origin fix/critical-description
```

Open a PR, complete the checklist, and merge. The auto-deploy will trigger.

---

## Notes

- Never commit directly to `main` for non-trivial changes.
- For trivial documentation typos, a direct push to `main` is acceptable.
- Never auto-merge Dependabot PRs — always review the changelog manually.
