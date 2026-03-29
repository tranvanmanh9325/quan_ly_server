# Rule 08 — Documentation Standards

## Documentation Files

All project documentation lives under `docs/`. The current structure must
be maintained:

| File | Contents |
| --- | --- |
| `docs/README.md` | Index — links to all other docs files |
| `docs/architecture.md` | System topology, data flow, design trade-offs |
| `docs/api-reference.md` | All REST endpoints, request/response shapes, curl examples |
| `docs/backend-internals.md` | `SshService` lifecycle, retry strategy, shell command design |
| `docs/frontend-internals.md` | Component structure, parser contracts, polling mechanics |
| `docs/deployment.md` | Prerequisites, `.env` setup, Docker deploy, CI/CD runner setup |
| `docs/security.md` | Threat model, trade-offs, hardening roadmap |
| `docs/troubleshooting.md` | Common errors, diagnostic commands, known edge cases |

---

## Markdown Lint Rules

The project uses `.markdownlint.json` under `docs/`. Active overrides:

```json
{
  "MD013": false,   // line length — not enforced
  "MD033": false,   // inline HTML — allowed for ASCII diagrams
  "MD041": false    // first line heading — docs with preamble
}
```

Run `npx markdownlint-cli2 'docs/**/*.md'` before committing documentation
changes. The `.markdownlintignore` at the project root excludes
`node_modules` and `target` directories.

---

## What Requires a Documentation Update

| Change | Files to update |
| --- | --- |
| New API endpoint | `docs/api-reference.md`, `docs/backend-internals.md` |
| New parser function | `docs/frontend-internals.md`, Rule 03 parsers table |
| New Docker service or port | `docs/architecture.md`, `docs/deployment.md` |
| New SSH configuration option | `docs/backend-internals.md`, `docs/security.md` |
| New environment variable | `backend/.env.example`, `docs/deployment.md` |
| Security trade-off change | `docs/security.md`, `SECURITY.md` (root) |
| CI/CD workflow change | `docs/deployment.md` |
| Architectural decision | `docs/architecture.md` (add to trade-offs table) |

---

## API Reference Format

Each endpoint entry in `docs/api-reference.md` must follow this structure:

```markdown
### GET /api/metrics/<name>

**Description:** One sentence about what this measures.

**Shell command executed:**
\`\`\`bash
# exact command string from MetricsController
\`\`\`

**Response:**
\`\`\`json
{ "data": "<raw SSH output as a string>" }
\`\`\`

**cURL example:**
\`\`\`bash
curl http://localhost:8080/api/metrics/<name>
\`\`\`

**Notes:** Any parsing caveats, fallback behaviour, or known limitations.
```

---

## README.md (root)

The root `README.md` is the project's public face. It must contain:

1. A one-paragraph project description.
2. A high-level feature list.
3. Tech stack table (keep in sync with Rule 01).
4. A prerequisites section.
5. A quick-start section (`.env` setup → `docker compose up`).
6. Architecture overview diagram (text-based).
7. Links to the `docs/` directory for deeper reading.
8. Badges (build status, license).

Do not add tutorials, blog-post-style explanations, or FAQ content to
`README.md` — those belong in the appropriate `docs/` file.

---

## Code Comment Language

Code comments (inline, block, Javadoc JSDoc) are written in **Vietnamese**.

Documentation files (`docs/*.md`, root `README.md`, `SECURITY.md`) are
written in **English**.

This split is intentional: code comments are for the primary developer
(Vietnamese); documentation is for international contributors and tools
that index the repository.
