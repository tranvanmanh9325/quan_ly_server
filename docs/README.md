# Mini Server Dashboard — Documentation

Welcome to the complete documentation for Mini Server Dashboard.

---

## Table of Contents

| Document | Description |
| --- | --- |
| [Architecture](./architecture.md) | Microservices design, data flow diagrams, key trade-offs, and SSH session lifecycle |
| [API Reference](./api-reference.md) | All REST endpoints: commands, response shapes, error handling |
| [Frontend Internals](./frontend-internals.md) | React state management, polling architecture, SciFiIcons, responsive layout |
| [Backend Internals](./backend-internals.md) | Spring Boot services, JSch SSH fallback, CORS, Maven dependencies |
| [Telegram AI Agent](./telegram-ai-agent.md) | Autonomous Telegram agent, Groq LLM tool calling, token capping, 429 retries |
| [Database & Auth](./database-and-auth.md) | Authentication service, JWT tokens, PostgreSQL schema, file service |
| [System Automation](./system-automation.md) | Systemd daily APT timers (06:00 AM update / 06:30 AM upgrade), auto-cleanup policy |
| [Deployment Guide](./deployment.md) | Local dev setup, Docker Compose production deployment, CI/CD pipeline, runbooks |
| [Security Guide](./security.md) | Known trade-offs, hardening recommendations, API key & credential management |
| [Troubleshooting](./troubleshooting.md) | Diagnostic commands, common error patterns and their fixes |

---

## Quick Links

- **[README](../README.md)** — Project overview and quick-start
- **[SECURITY.md](../SECURITY.md)** — Vulnerability reporting policy
- **[LICENSE](../LICENSE)** — MIT License

---

## Project Summary

Mini Server Dashboard is a self-hosted, real-time monitoring dashboard and AI-powered server management platform. It connects to a remote Linux server over SSH and visualises live system metrics (CPU, RAM, disk, network, temperature, voltage, and process list) through a modern Cyberpunk dark-themed web interface, while offering an autonomous Telegram AI Agent.

The stack consists of:

- **Metrics Service:** Spring Boot 4.1.0 (Java 21) on Port `8082` — SSH telemetry tunnel, sudo executor, Telegram Long Polling, and Groq AI Agent (`llama-3.1-8b-instant`).
- **Auth Service:** Spring Boot 4.1.0 (Java 21) on Port `8081` — JWT authentication, user credential management, and role-based access control.
- **File Service:** Spring Boot 4.1.0 (Java 21) on Port `8083` — Remote file browsing, log inspection, and file system operations.
- **Frontend:** React 19 + Vite 8 + Recharts on Port `5173` — Custom Sci-Fi UI system, adaptive polling, Visibility API, pure-function parsers.
- **Database:** PostgreSQL 17 Alpine on Port `5432` — Central persistent storage.
- **Serving:** Nginx Alpine — static file server + API reverse proxy.
- **Infrastructure:** Docker Compose, self-hosted GitHub Actions runner, systemd daily APT timers (06:00 AM update / 06:30 AM upgrade + auto cleanup).

No agent software needs to be installed on the monitored server — only standard Linux utilities (`top`, `free`, `df`, `sensors`, `ps`, `who`, `systemctl`, `apt`, etc.) and SSH access are required.
