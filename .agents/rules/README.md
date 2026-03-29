# Project Rules — Index

This directory contains the canonical ruleset for the **Mini Server Dashboard** project.
Every contributor (human or AI) must read these rules before touching the codebase.

| File | Scope | TL;DR |
| --- | --- | --- |
| [01-project-overview.md](./01-project-overview.md) | Whole project | Tech stack, architectural laws, deployment model |
| [02-backend-java.md](./02-backend-java.md) | Java / Spring Boot | Package layout, DI, `SshService` contract, controller shapes, Maven rules |
| [03-frontend-react.md](./03-frontend-react.md) | React / JavaScript | Hook contracts, state shapes, `parsers.js` API, polling constants, ESLint |
| [04-docker-nginx-infra.md](./04-docker-nginx-infra.md) | Docker / Nginx | Compose topology, healthchecks, resource limits, Nginx config, secrets |
| [05-security.md](./05-security.md) | Security | Accepted trade-offs, never-change list, hardening roadmap |
| [06-cicd-git-workflow.md](./06-cicd-git-workflow.md) | Git / CI/CD | Branch policy, auto-deploy, Dependabot review, commit format, pre-merge checklist |
| [07-code-quality-style.md](./07-code-quality-style.md) | All layers | Naming, formatting, logging levels, prohibited patterns, new-metric checklist |
| [08-documentation.md](./08-documentation.md) | Documentation | `docs/` structure, markdown lint, update matrix, API reference format |

---

## Quick Reference — Most Frequently Needed Rules

### Do not change without reading the full rule first

- Polling uses `setTimeout` chains, NOT `setInterval` → **Rule 03**
- All parsing belongs in `parsers.js` (never in Java) → **Rule 01, Rule 02**
- `StrictHostKeyChecking=no` is intentional → **Rule 05**
- `backend/.env` must NEVER be committed → **Rule 04, Rule 06**
- CORS config is for local dev only; Nginx handles production → **Rule 01, Rule 02**
- Constructor injection only for new Java code → **Rule 02**
- One shared SSH session (not per-request) → **Rule 02**

### Adding something new

- New metric endpoint → **Rule 07** (full checklist)
- New environment variable → **Rule 04, Rule 08**
- New library → read **Rule 01** tech stack first
- New documentation file → **Rule 08**
