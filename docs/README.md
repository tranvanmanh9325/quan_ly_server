# Mini Server Dashboard — Technical Documentation

Welcome to the comprehensive technical documentation for the **Mini Server Dashboard — Sci-Fi Cyberpunk Edition**.

---

## 📑 Table of Contents

| Document | Description |
| --- | --- |
| 📖 [Architecture](./architecture.md) | High-level microservices topology, 2-way data flow diagrams, trade-offs, and SSH lifecycle |
| 🔌 [API Reference](./api-reference.md) | Complete REST API endpoint reference for all 4 microservices (`metrics`, `auth`, `files`, `ai-agent`) |
| ⚛️ [Frontend Internals](./frontend-internals.md) | React 19 architecture, D3-geo 3D Globe, Sci-Fi HUD canvas layer, and pure-function parsers |
| ☕ [Backend Internals](./backend-internals.md) | Spring Boot 4.1.0 microservices, JSch SSH session pooling, and FastAPI AI Agent internals |
| 🤖 [AI Agent & Multi-Provider Ecosystem](./telegram-ai-agent.md) | Autonomous AI ("Tiểu Bảo Bảo"), Groq + OpenRouter key pools, Telegram bot, and Facebook E2EE automation |
| 🗄 [Database & Auth](./database-and-auth.md) | PostgreSQL 17 schema, JWT token lifecycle, BCrypt auth, and thread persistence |
| ⏱ [System Automation](./system-automation.md) | Daily system maintenance timers, memory optimization, and periodic scanner background tasks |
| 🚢 [Deployment Guide](./deployment.md) | Production Docker Compose hardening, environment variables, local hot-reload, and CI/CD |
| 🛡 [Security Hardening](./security.md) | Threat modeling, terminal command sandboxing, E2EE security, and secret management |
| 🔧 [Troubleshooting Handbook](./troubleshooting.md) | Diagnostic runbooks, SSH recovery, E2EE PIN issues, and rate-limit mitigation |

---

## 🔗 Quick Links

- **[Project Root README](../README.md)** — Project overview, features showcase, and quick-start guide
- **[SECURITY.md](../SECURITY.md)** — Vulnerability reporting policy and responsible disclosure
- **[LICENSE](../LICENSE)** — MIT License

---

## 🏛 System Architecture Summary

Mini Server Dashboard is a self-hosted, real-time Linux server monitoring, management, and autonomous AI operational ecosystem. It connects to target Linux servers over SSH with **zero target agent footprint** and renders live telemetry through a futuristic Cyberpunk HUD interface while deploying an autonomous AI assistant ("Tiểu Bảo Bảo") across Telegram and Facebook Messenger E2EE.

### Core Ecosystem Components:

1. **Metrics Service (`metrics-service`):** Spring Boot 4.1.0 (Java 21) on Port `8082` — JSch SSH persistent telemetry tunnel, sudo command executor, and hardware health engine.
2. **Auth Service (`auth-service`):** Spring Boot 4.1.0 (Java 21) on Port `8081` — User credentials, BCrypt password hashing, and JWT token issuance/verification.
3. **File Service (`file-service`):** Spring Boot 4.1.0 (Java 21) on Port `8083` — Remote SFTP filesystem browser, log tailing, and file manipulation.
4. **AI Agent Service (`ai-agent-service`):** FastAPI (Python 3.11) on Port `8084` & noVNC `6080` — Telegram Bot assistant, Playwright Facebook E2EE automation (PIN unlock, away messages, and auto-unsend), and Multi-Provider LLM key pool (Groq + OpenRouter).
5. **Frontend:** React 19 + Vite 8 on Port `5173:80` — Cyberpunk HUD SPA, D3-geo 3D Globe, Web Audio API sound synthesizer, Canvas shockwave effects, and Nginx reverse proxy.
6. **Database:** PostgreSQL 17 Alpine on Port `5432` — Central persistent storage for users, Telegram configurations, and Facebook thread states.
