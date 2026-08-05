# Database & Authentication Architecture

A deep-dive technical reference into authentication mechanisms, JWT security, microservice boundary management, and PostgreSQL database schema.

---

## Overview

The Mini Server Dashboard platform isolates authentication and file management concerns into dedicated Spring Boot microservices backed by a central PostgreSQL database.

```text
┌────────────────────────┐         JWT Token           ┌────────────────────────┐
│     Client Browser     │ ───────────────────── ─────▶│      Auth Service      │
│  (React 19 Dashboard)  │                             │  Port 8081 / JPA ORM   │
└───────────┬────────────┘                             └───────────┬────────────┘
            │                                                      │
            │ Bearer Token                                         │ Reads/Writes
            ▼                                                      ▼
┌────────────────────────┐                             ┌────────────────────────┐
│    Metrics / File      │                             │     PostgreSQL DB      │
│    Microservices       │                             │  Port 5432 / Table DB  │
└────────────────────────┘                             └────────────────────────┘
```

---

## 1. Auth Service (`auth-service`) — Port 8081

### Authentication Flow

1. **User Login (`POST /api/auth/login`):** Client submits username and password.
2. **Password Verification:** Passwords are hashed and verified against `users` table records using BCrypt.
3. **JWT Generation:** Upon successful authentication, `auth-service` signs and returns a compact JSON Web Token (JWT) containing user claims, role (`ROLE_ADMIN` / `ROLE_USER`), and expiration timestamp (24 hours default).
4. **Token Refresh (`POST /api/auth/refresh`):** Reissues valid JWTs before expiration.

### Key Dependencies

- `io.jsonwebtoken:jjwt-api:0.12.6`
- `io.jsonwebtoken:jjwt-impl:0.12.6`
- `io.jsonwebtoken:jjwt-jackson:0.12.6`

---

## 2. Database Schema (PostgreSQL 17)

The central database container (`dashboard_db`) runs PostgreSQL 17 Alpine on port `5432`.

### Core Tables

#### `users`

Stores user credentials and profile metadata.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | PRIMARY KEY | Unique user identifier |
| `username` | `VARCHAR(50)` | UNIQUE, NOT NULL | Login username |
| `password` | `VARCHAR(255)` | NOT NULL | BCrypt hashed password string |
| `role` | `VARCHAR(20)` | NOT NULL | Authorization role (`ROLE_ADMIN`, `ROLE_USER`) |
| `created_at` | `TIMESTAMP` | DEFAULT NOW() | Account creation timestamp |

#### `processed_telegram_updates`

Maintained by `metrics-service` to track processed Telegram update IDs and prevent duplicate command execution.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `update_id` | `BIGINT` | PRIMARY KEY | Unique Telegram Update ID |
| `processed_at` | `TIMESTAMP` | DEFAULT NOW() | Processing timestamp |

---

## 3. File Service (`file-service`) — Port 8083

Dedicated microservice for remote file inspection and log log viewing.

### Primary Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/files/browse` | List directory contents and file metadata |
| `GET` | `/api/files/read` | Fetch file contents (with line range & byte offset truncation) |
| `GET` | `/api/files/logs` | Tail system log files (`/var/log/syslog`, `/var/log/nginx/access.log`) |

---

## 4. Cross-Origin Resource Sharing (CORS)

Local development origins (`http://localhost:5173`, `http://127.0.0.1:5173`) are whitelisted across all microservices (`CorsConfig.java`). In production, Nginx proxies all requests under unified subpaths (`/api/auth/*`, `/api/metrics/*`, `/api/files/*`), enforcing single-origin security.
