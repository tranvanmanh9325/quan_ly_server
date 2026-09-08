# Pull Request

## 📋 Description

Provide a clear and concise summary of the changes introduced in this pull request. Explain the context, the problem being solved, and the proposed solution.

---

## 🎯 Type of Change

- [ ] 🐛 **Bug fix** (non-breaking change which fixes an issue)
- [ ] ✨ **New feature** (non-breaking change which adds functionality)
- [ ] ♻️ **Refactor** (code restructuring without behavioral changes)
- [ ] ⚡ **Performance improvement** (latency reduction, memory optimization)
- [ ] 📝 **Documentation** (documentation additions or updates)
- [ ] 🔧 **Chore / Build** (dependency updates, configuration changes)

---

## 📦 Affected Components

- [ ] `services/ai-agent-service` (Python / FastAPI / Playwright / 9Router)
- [ ] `services/auth-service` (Java / Spring Boot / JWT)
- [ ] `services/metrics-service` (Java / Spring Boot / JSch / Telemetry)
- [ ] `services/file-service` (Java / Spring Boot / SFTP)
- [ ] `frontend/` (React 19 / Vite / TailwindCSS / Cyberpunk HUD)
- [ ] `db/` (PostgreSQL schemas & migrations)
- [ ] Documentation / Configuration

---

## 🧪 Verification & Testing

Describe how you tested these changes. Include commands executed and results observed.

- [ ] Python unit tests passed: `python -m unittest discover -s services/ai-agent-service/tests`
- [ ] Java Maven build passed: `mvn clean test-compile`
- [ ] Frontend build passed: `npm run build`
- [ ] Verified in local / staging environment

---

## ✅ Checklist

- [ ] My code follows the project's coding standards and conventions.
- [ ] All in-code comments and Git commit messages are strictly in **English**.
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] New and existing unit tests pass locally with my changes.
- [ ] There are 0 linter errors and 0 static type check warnings.
- [ ] I have updated the relevant documentation (if applicable).
