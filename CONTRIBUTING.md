# Contributing to Kirito Server Dashboard & AI Agent Ecosystem

Thank you for your interest in contributing to **quan_ly_server**! We welcome contributions from developers of all skill levels. Whether you are fixing bugs, improving documentation, designing cyberpunk UI elements, or proposing architectural enhancements for our autonomous AI Agent, your contributions are highly valued.

This document provides a comprehensive guide to our development workflow, coding conventions, and contribution lifecycle.

---

## 🧭 Table of Contents

1. [Project Leadership & Creator](#-project-leadership--creator)
2. [Contributors & Community Hall of Fame](#-contributors--community-hall-of-fame)
3. [Code of Conduct](#code-of-conduct)
4. [Architecture Overview](#architecture-overview)
5. [Prerequisites](#prerequisites)
6. [Local Development Setup](#local-development-setup)
7. [Branching & Git Workflow](#branching--git-workflow)
8. [Commit Message Conventions](#commit-message-conventions)
9. [Coding Standards](#coding-standards)
   - [Python (ai-agent-service)](#python-ai-agent-service)
   - [Java (Spring Boot Microservices)](#java-spring-boot-microservices)
   - [Frontend (React 19 + Vite)](#frontend-react-19--vite)
10. [Testing & Quality Assurance](#testing--quality-assurance)
11. [Submitting a Pull Request](#submitting-a-pull-request)
12. [Reporting Issues & Feature Requests](#reporting-issues--feature-requests)

---

## 👑 Project Leadership & Creator

The **Kirito Server Dashboard & Autonomous AI Agent Ecosystem** was originally designed, architected, and is maintained by **Trần Văn Mạnh (Kirito)**.

<div align="center">

<a href="https://github.com/tranvanmanh9325">
  <img src="https://github.com/tranvanmanh9325.png" width="110" height="110" style="border-radius: 50%; border: 3px solid #00ffcc; box-shadow: 0 0 16px rgba(0, 255, 204, 0.4);" alt="Trần Văn Mạnh (Kirito)" />
</a>

### **Trần Văn Mạnh (Kirito)**
*Project Founder, Core Maintainer & Lead Software Architect*

[![GitHub](https://img.shields.io/badge/GitHub-@tranvanmanh9325-181717?style=flat-square&logo=github)](https://github.com/tranvanmanh9325)
[![Email](https://img.shields.io/badge/Email-manhtrana1k45tl@gmail.com-EA4335?style=flat-square&logo=gmail&logoColor=white)](mailto:manhtrana1k45tl@gmail.com)
[![HUST](https://img.shields.io/badge/Alma_Mater-HUST-B31B1B?style=flat-square&logo=renaissance&logoColor=white)](https://hust.edu.vn)
[![Location](https://img.shields.io/badge/Location-Hanoi_%7C_Nghe_An,_Vietnam-0099FF?style=flat-square&logo=google-maps&logoColor=white)](https://maps.google.com)

</div>

As the lead maintainer and project creator, Trần Văn Mạnh oversees the architectural roadmap, code reviews, security hardening, and releases across all backend microservices, AI agents, and frontend modules.

---

## 👥 Contributors & Community Hall of Fame

This project strictly adheres to the **[All-Contributors](https://allcontributors.org/)** specification. All contributions of any kind (code, bug reports, documentation, architecture, security, design) are recognized and celebrated.

See the complete list of contributors and contribution badges in [**`CONTRIBUTORS.md`**](./CONTRIBUTORS.md).

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="20%"><a href="https://github.com/tranvanmanh9325"><img src="https://github.com/tranvanmanh9325.png" width="90px;" alt="Trần Văn Mạnh"/><br /><sub><b>Trần Văn Mạnh (Kirito)</b></sub></a><br /><a href="#creator-tranvanmanh9325" title="Project Creator">👑</a> <a href="https://github.com/tranvanmanh9325/quan_ly_server/commits?author=tranvanmanh9325" title="Code">💻</a> <a href="#architecture-tranvanmanh9325" title="Architecture & System Design">🏗️</a> <a href="#maintenance-tranvanmanh9325" title="Maintenance & Operations">🚧</a> <a href="#ideas-tranvanmanh9325" title="Ideas & Conception">💡</a> <a href="#security-tranvanmanh9325" title="Security & Hardening">🛡️</a> <a href="https://github.com/tranvanmanh9325/quan_ly_server/commits?author=tranvanmanh9325" title="Documentation">📖</a> <a href="#design-tranvanmanh9325" title="Cyberpunk UI/UX Design">🎨</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](./CODE_OF_CONDUCT.md). Please read it to understand our community standards and expectations.

---

## Architecture Overview

The system is organized into a modular multi-service architecture:

| Component | Technology Stack | Description |
| :--- | :--- | :--- |
| **`services/auth-service`** | Java 21, Spring Boot 4.1.x, JWT | Authentication, user credential validation & token lifecycle |
| **`services/metrics-service`** | Java 21, Spring Boot 4.1.x, JSch | Real-time system telemetry via SSH & non-blocking WebSockets |
| **`services/file-service`** | Java 21, Spring Boot 4.1.x, SFTP | Remote file system operations, uploads, downloads & searching |
| **`services/ai-agent-service`** | Python 3.12+, FastAPI, Playwright | Autonomous AI Agent (Tiểu Bảo Bảo), 9Router pool & social bots |
| **`frontend/`** | React 19, Vite, TailwindCSS, Lucide | Cyberpunk Sci-Fi operations dashboard & noVNC remote interface |
| **`db/`** | PostgreSQL 17, Flyway-style SQL | Relational database migrations, time-series metrics & agent memory |

---

## Prerequisites

Ensure you have the following installed locally:

- **Git** (v2.40+)
- **Docker & Docker Compose V2** (v2.20+)
- **Java Development Kit (JDK)**: OpenJDK 21 LTS
- **Apache Maven**: v3.9+
- **Python**: v3.12+ (Python 3.14 recommended)
- **Node.js**: v20+ LTS & **npm** v10+

---

## Local Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/tranvanmanh9325/quan_ly_server.git
   cd quan_ly_server
   ```

2. **Configure environment variables:**

   ```bash
   cp .env.example .env
   # Edit .env with your local credentials and API keys
   ```

3. **Start infrastructure dependencies with Docker Compose:**

   ```bash
   docker compose up -d db
   ```

4. **Run Python AI Agent Service locally:**

   ```bash
   cd services/ai-agent-service
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --host 0.0.0.0 --port 8084 --reload
   ```

5. **Run Java Spring Boot Microservices locally:**

   ```bash
   mvn test-compile -f services/auth-service/pom.xml
   mvn spring-boot:run -f services/auth-service/pom.xml
   ```

6. **Run React Frontend locally:**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

## Branching & Git Workflow

We follow the GitHub Flow model. Always branch off the latest `main`:

```bash
git checkout main
git pull origin main
git checkout -b <type>/<short-description>
```

### Branch Naming Convention

- `feat/<feature-name>`: New features or capabilities (e.g. `feat/tiktok-auto-streak`)
- `fix/<bug-name>`: Bug fixes and issue resolutions (e.g. `fix/playwright-locator-property`)
- `refactor/<target>`: Code restructuring without feature change (e.g. `refactor/vnc-manager-pooling`)
- `perf/<target>`: Performance optimizations (e.g. `perf/postgres-brin-indexes`)
- `docs/<topic>`: Documentation enhancements (e.g. `docs/api-guide`)
- `chore/<task>`: Dependency updates, CI/CD, or maintenance (e.g. `chore/bump-spring-boot-4.1.1`)

---

## Commit Message Conventions

We strictly enforce **Conventional Commits**. All commit messages **MUST be written in English**:

```text
<type>(<scope>): <short description in imperative mood>

[optional body explaining rationale]

[optional footer(s)]
```

### Allowed Types

- `feat`: A new feature
- `fix`: A bug fix
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `docs`: Documentation only changes
- `build`: Changes affecting build system or external dependencies
- `ci`: Changes to CI/CD workflows
- `chore`: Other changes that do not modify src or test files

### Examples

- `feat(ai-agent): implement multi-key ngrok tunnel rotation pool`
- `fix(facebook): access locator.first as property instead of function call`
- `build(deps): bump spring-boot-starter-parent from 4.1.0 to 4.1.1`

---

## Coding Standards

### Python (ai-agent-service)

- Follow **PEP 8** style guidelines and **PEP 484** type annotations.
- Avoid loose typing (`Any`). Use descriptive generic types and `Optional`.
- Do **NOT** silence type errors with `# type: ignore` or `# pyright: ignore` unless strictly required for third-party C-extensions.
- Ensure all static type checks pass with **Pyright**:

  ```bash
  npx pyright services/ai-agent-service
  ```

- Write all in-code comments and docstrings in English. Explain *why* a decision was made rather than *what* the code does.

### Java (Spring Boot Microservices)

- Follow standard Spring Boot and Java idioms.
- Use constructor injection via Lombok `@RequiredArgsConstructor`.
- Adhere to the **DRY (Don't Repeat Yourself)** principle.
- Use Java NIO (`java.nio.file`) for high-throughput file streaming operations.
- Ensure Maven builds succeed without warnings or errors:

  ```bash
  mvn clean test-compile -f services/auth-service/pom.xml
  mvn clean test-compile -f services/file-service/pom.xml
  mvn clean test-compile -f services/metrics-service/pom.xml
  ```

### Frontend (React 19 + Vite)

- Maintain the unified **Cyberpunk Sci-Fi HUD design language** (dark theme, cyan/emerald glowing accents, sharp border chamfers).
- Prefer **Custom Vector SVG Icons** over generic Unicode emojis or heavy third-party icon fonts.
- Avoid horizontal scrollbars (`overflow-x: hidden`) on card widgets across responsive viewport widths.
- Ensure Vite build succeeds cleanly:

  ```bash
  cd frontend && npm run build
  ```

---

## Testing & Quality Assurance

Every contribution must be accompanied by relevant unit or integration tests:

1. **Python AI Agent Tests:**

   ```bash
   python -m unittest discover -s services/ai-agent-service/tests
   ```

2. **Java Microservices Tests:**

   ```bash
   mvn test -f services/auth-service/pom.xml
   mvn test -f services/file-service/pom.xml
   mvn test -f services/metrics-service/pom.xml
   ```

3. **Frontend Linting & Tests:**

   ```bash
   cd frontend
   npm run lint
   npm test
   ```

---

## Submitting a Pull Request

1. **Sync with `main`:**

   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Verify all checks pass:** Unit tests, linting, and build steps must succeed locally.
3. **Push your branch:**

   ```bash
   git push origin <type>/<short-description>
   ```

4. **Open a Pull Request:** Use our provided PR template, fill in all sections clearly, and describe the changes made.
5. **Code Review:** Address any reviewer feedback promptly. Once approved, your PR will be squash-merged into `main`.

---

## Reporting Issues & Feature Requests

- **Bugs:** Check existing issues before submitting a new one. Include environment details (OS, Docker version, browser), exact error logs, and reproduction steps.
- **Security Issues:** Please follow our [Security Policy](./SECURITY.md) to report vulnerabilities privately.
- **Feature Requests:** Detail the use case, proposed solution, and architectural impact.

Thank you for helping make **quan_ly_server** better! 🚀
