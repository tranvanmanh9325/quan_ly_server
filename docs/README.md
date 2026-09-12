# Mini Server Dashboard — Technical Documentation Suite

Welcome to the technical documentation for **Mini Server Dashboard — Sci-Fi Cyberpunk Edition**.

---

## 📑 Table of Contents

| Document | Description |
| --- | --- |
| 📖 [Architecture](./architecture.md) | Microservices topology (5 services + DB), 2-way data flow diagrams, trade-offs, and SSH lifecycles |
| 🧠 [Neuromorphic Brain Core](./neuromorphic-brain.md) | Living AI mind: 6 Neurotransmitters, Karl Friston Active Inference, 32GB HDC Virtual Cortex, Russell 2D Affect, Dream Engine |
| 🎬 [Multimodal Video Pipeline](./multimodal-video-pipeline.md) | Lightweight video intelligence: Dual-Track Audio/Vision, Whisper Biasing, Cross-Modal Resolver, Dialect Normalizer |
| 🔌 [API Reference](./api-reference.md) | Complete REST API and Gateway reference for all microservices (`metrics`, `auth`, `files`, `ai-agent`, `brain`, `facebook`, `tiktok`, `v1`) |
| 🤖 [AI Agent & 9Router Ecosystem](./telegram-ai-agent.md) | Autonomous AI ("Tiểu Bảo Bảo"), BLUF thinking, Telegram Formatter v2, Loop Breaker, 9Router RTK, E2EE Facebook, TikTok |
| ☕ [Backend Internals](./backend-internals.md) | Spring Boot 4.1.0 microservices, JSch SSH session pooling, FastAPI background loops, and Tool Registry delegation |
| 🗄 [Database & Auth](./database-and-auth.md) | PostgreSQL 17 schema, JWT token lifecycle, BCrypt auth, RTK stats, and AI Memory tables |
| ⏱ [System Automation](./system-automation.md) | Periodic schedulers: Social scanners, appointment reminders, cognitive heartbeat, nightly consolidation, dream engine |
| 🚢 [Deployment Guide](./deployment.md) | Production Docker Compose hardening, environment variables with Ground Truth location, local hot-reload |
| 🛡 [Security Hardening](./security.md) | Threat modeling, terminal command sandboxing, E2EE security, and multi-key secret management |
| 🔧 [Troubleshooting Handbook](./troubleshooting.md) | Diagnostic runbooks: Groq 413, STT dialect distortion, HTML leakage, envelope guard, non-ASCII headers, SSH recovery |
| ⚛️ [Frontend Internals](./frontend-internals.md) | React 19 architecture, Brain Core HUD, D3-geo 3D Globe, Sci-Fi HUD canvas layer, and pure-function parsers |

---

## 🔗 Quick Links

- **[Project Root README](../README.md)** — Project overview, features showcase, and quick-start guide
- **[SECURITY.md](../SECURITY.md)** — Vulnerability reporting policy and responsible disclosure
- **[LICENSE](../LICENSE)** — MIT License

---

## 🏛 System Architecture Summary

Mini Server Dashboard is a self-hosted, real-time Linux server monitoring, management, and autonomous AI operational ecosystem. It connects to target Linux servers over SSH with **zero target agent footprint** and renders live telemetry through a futuristic Cyberpunk HUD interface while deploying an autonomous neuromorphic AI assistant ("Tiểu Bảo Bảo") with biological neurochemistry, multimodal video analysis, regional dialect understanding, and 32GB Virtual Memory Swap across Telegram and Facebook Messenger E2EE.

### Core Ecosystem Components

1. **Metrics Service (`metrics-service`):** Spring Boot 4.1.0 (Java 21) on Port `8082` — JSch SSH persistent telemetry tunnel, sudo command executor, and hardware health engine.
2. **Auth Service (`auth-service`):** Spring Boot 4.1.0 (Java 21) on Port `8081` — User credentials, BCrypt password hashing, and JWT token issuance/verification.
3. **File Service (`file-service`):** Spring Boot 4.1.0 (Java 21) on Port `8083` — Remote SFTP filesystem browser, log tailing, and file manipulation.
4. **AI Agent Service (`ai-agent-service`):** FastAPI (Python 3.11) on Port `8084` & noVNC `6080` — Neuromorphic Brain Core (`BrainCore`), Multimodal Video Pipeline (`LightweightVideoPipeline`), Telegram Bot, 9Router LLM Pool, Playwright Facebook E2EE automation, TikTok streak keeper, and 32GB HDC Virtual Cortex.
5. **Frontend:** React 19 + Vite 8 on Port `5173:80` — Cyberpunk HUD SPA, Brain Core 3D Connectome Inspector (`/brain-core`), D3-geo 3D Globe, Web Audio synthesizer, and Nginx reverse proxy.
6. **Database:** PostgreSQL 17 Alpine on Port `5432` — Central persistent storage for users, configs, Telegram history, Facebook threads, RTK stats, and AI memory lessons.
