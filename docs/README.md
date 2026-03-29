# Mini Server Dashboard — Documentation

Welcome to the complete documentation for Mini Server Dashboard.

---

## Table of Contents

| Document | Description |
| --- | --- |
| [Architecture](./architecture.md) | System design, data flow diagrams, key trade-offs, and SSH session lifecycle |
| [API Reference](./api-reference.md) | All REST endpoints: commands, response shapes, error handling |
| [Frontend Internals](./frontend-internals.md) | State management, polling architecture, parser utilities, responsive layout |
| [Backend Internals](./backend-internals.md) | Spring Boot packages, SSH service, CORS, Maven dependencies, Dockerfile |
| [Deployment Guide](./deployment.md) | Local dev setup, Docker Compose production deployment, CI/CD pipeline, runbooks |
| [Security Guide](./security.md) | Known trade-offs, hardening recommendations, credential management |
| [Troubleshooting](./troubleshooting.md) | Diagnostic commands, common error patterns and their fixes |

---

## Quick Links

- **[README](../README.md)** — Project overview and quick-start
- **[SECURITY.md](../SECURITY.md)** — Vulnerability reporting policy
- **[LICENSE](../LICENSE)** — MIT License

---

## Project Summary

Mini Server Dashboard is a self-hosted, real-time monitoring dashboard that connects to a remote Linux server over SSH and visualises live system metrics (CPU, RAM, disk, network, temperature, voltage, and process list) through a modern dark-themed web interface.

The stack consists of:

- **Backend:** Spring Boot 4.0.5 (Java 21) — thin SSH tunnel with persistent connection and exponential-backoff retry
- **Frontend:** React 19 + Vite + Recharts — adaptive polling, Visibility API integration, pure-function parsers
- **Serving:** Nginx Alpine — static file server + API reverse proxy (single origin in production)
- **Infrastructure:** Docker Compose, self-hosted GitHub Actions runner

No agent software needs to be installed on the monitored server — only standard Linux utilities (`top`, `free`, `df`, `sensors`, `ps`, `who`, etc.) are required.
