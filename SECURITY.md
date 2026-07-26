# Security Policy

## Scope

This is a **personal self-hosted server dashboard** — a web application that connects to a managed Linux server via SSH to display and control system metrics, processes, services, Docker containers, and files.

The scope of this security policy covers:

- The Spring Boot backend (`/api/**` REST endpoints)
- The React frontend served via Nginx
- SSH credential management and command execution sandbox
- Docker container configuration and runtime environment

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` branch (latest) | ✅ Yes |
| Any tagged release | ✅ Yes |
| Older commits / forks | ❌ No |

This project follows a rolling-release model on the `main` branch. Only the latest commit on `main` is actively maintained.

---

## Known Security Trade-offs

| Area | Trade-off | Reason |
|------|-----------|--------|
| `StrictHostKeyChecking=no` | Disables SSH host key verification | Required when using Ngrok tunnels where the host key changes on every reconnect. **Do not use in production environments.** |
| SSH over Ngrok TCP | Credentials transmitted through a third-party tunnel | Acceptable for personal/development use. Use a VPN or direct SSH connection in production. |
| No authentication on API endpoints | All `/api/**` routes are publicly accessible | By design — intended to run behind a private network or firewall. **Do NOT expose port `8080` or `5173` to the public internet.** |
| Command execution sandbox | Only an allowlist of safe commands is permitted via the terminal endpoint | Destructive commands (`rm -rf`, `mkfs`, `reboot`, `shutdown`, `dd`, `format`) are blocked server-side. |
| SSH credentials in `.env` | Plaintext credentials in environment file | Standard Docker Compose pattern. Ensure `.env` is in `.gitignore` and never committed to version control. |

---

## Reporting a Vulnerability

This is a personal project, but security reports are welcome and appreciated.

**Please do NOT open a public GitHub Issue** for security vulnerabilities, as this may expose the details before a fix is available.

Instead, report privately via:

- **GitHub Security Advisories**: Use the ["Report a vulnerability"](../../security/advisories/new) button on the **Security** tab of this repository.

**Response timeline:**

- Initial acknowledgement: within **7 days**
- Fix or mitigation: within **30 days** for confirmed vulnerabilities

**When reporting, please include:**

1. A clear description of the vulnerability and its potential impact
2. Steps to reproduce (proof-of-concept if applicable)
3. Affected file(s), component(s), or endpoint(s)
4. Suggested fix or mitigation (optional but appreciated)

---

## Safe Harbor

Responsible security research conducted in good faith on your **own deployment** of this software is welcome and appreciated. Please do not test against instances you do not own or have explicit written permission to test.
