# Security Policy

## Scope

This is a **personal mini-server dashboard** — a self-hosted web application that connects to a single managed server via SSH to display system metrics (CPU, RAM, disk, network, temperature, processes).

The scope of this security policy covers:

- The Spring Boot backend (`/api/**` endpoints)
- The React frontend served via Nginx
- SSH credential management
- Docker container configuration

## Supported Versions

| Version | Supported |
| ------- | --------- |
| `main` branch (latest) | ✅ Yes |
| Any tagged release | ✅ Yes |
| Older commits | ❌ No |

This project follows a rolling-release model on the `main` branch. Only the latest commit is actively maintained.

## Known Security Trade-offs

| Area | Trade-off | Reason |
| ---- | --------- | ------ |
| `StrictHostKeyChecking=no` | Disables SSH host verification | Required when using Ngrok tunnels, where the host key changes on every reconnect. **Do not use in production.** |
| SSH over Ngrok | Credentials transmitted through a third-party tunnel | Acceptable for a personal/development setup. Use a VPN or direct SSH for production. |
| No authentication on API endpoints | All `/api/**` routes are public | By design — the dashboard is intended to run behind a private network or firewall. Do **not** expose port `8080` or `5173` to the public internet. |

## Reporting a Vulnerability

This is a personal project, but security reports are welcome.

**Please do NOT open a public GitHub Issue** for security vulnerabilities.

Instead, contact directly via:

- **GitHub**: Open a private [Security Advisory](../../security/advisories/new) using the "Report a vulnerability" button on the Security tab.

I aim to respond within **7 days** and provide a fix within **30 days** for confirmed vulnerabilities.

When reporting, please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept if applicable)
- Affected file(s) or component(s)
- Your suggested fix (optional but appreciated)

## Safe Harbor

Responsible security research conducted in good faith on your **own deployment** of this software is welcome. Do not test against instances you do not own or have explicit permission to test.
