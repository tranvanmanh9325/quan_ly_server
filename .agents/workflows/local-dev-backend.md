---
description: run backend locally with Spring Boot dev server (no Docker)
---

## Prerequisites

Before starting, ensure the following are available on your machine:
- Java 21 (LTS) — `java -version` must report `21.x`
- Maven 3.9+ — `mvn -version`
- `backend/.env` file exists and contains valid `SSH_*` values

---

## Steps

1. Navigate to the `backend` directory.

```bash
cd backend
```

2. Load the environment variables from `.env` into your current shell session.
   Spring Boot reads these via OS environment, not a file at runtime.

```bash
# PowerShell (Windows)
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
    [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
  }
}

# Bash / Zsh (Linux / macOS / WSL)
export $(grep -v '^#' .env | xargs)
```

3. Start the Spring Boot dev server with Maven.

```bash
mvn spring-boot:run
```

4. Verify the backend is ready by checking the Actuator health endpoint.

```bash
# Expect: {"status":"UP"}
curl http://localhost:8080/actuator/health
```

5. The backend is now running on `http://localhost:8080`.
   You can now start the frontend dev server (see `local-dev-frontend.md`).

---

## Stopping

Press `Ctrl+C` in the terminal to stop the Spring Boot process.

---

## Notes

- `spring-boot-devtools` is on the classpath — class changes will trigger
  automatic restarts without needing to re-run `mvn spring-boot:run`.
- Do NOT commit `backend/.env`. Verify with `git status` before any push.
- If you changed `pom.xml` dependencies, run `mvn clean spring-boot:run`
  to force a fresh dependency resolution.
