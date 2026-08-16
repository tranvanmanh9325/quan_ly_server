# Database & Authentication Architecture

A deep-dive technical reference into authentication mechanisms, JWT security, microservice boundaries, and PostgreSQL database schema.

---

## 🌟 Overview

The Mini Server Dashboard platform isolates authentication and file management concerns into dedicated Spring Boot microservices backed by a central PostgreSQL database.

```text
┌────────────────────────┐         JWT Token           ┌────────────────────────┐
│     Client Browser     │ ───────────────────────────▶│      Auth Service      │
│  (React 19 Dashboard)  │                             │  Port 8081 / JPA ORM   │
│                        │◀─────────────────────────── │                        │
└───────────┬────────────┘         Signed JWT          └───────────┬────────────┘
            │                                                      │
            │ Bearer Token                                         │ Reads/Writes
            ▼                                                      ▼
┌────────────────────────┐                             ┌────────────────────────┐
│ Metrics / File / AI    │                             │     PostgreSQL DB      │
│     Microservices      │ ◄─────────────────────────► │  Port 5432 / Table DB  │
└────────────────────────┘                             └────────────────────────┘
```

---

## 1. Auth Service (`auth-service`) — Port 8081

### Authentication Flow

1. **User Login (`POST /api/auth/login`):** Client submits username and password.
2. **Password Verification:** Passwords are verified against `users` table records using BCrypt hashing (`BCryptPasswordEncoder`).
3. **JWT Generation:** Upon successful authentication, `auth-service` signs and returns a compact JSON Web Token (JWT) containing user claims, role (`ROLE_ADMIN` / `ROLE_USER`), and expiration timestamp (24 hours default).
4. **Token Verification (`GET /api/auth/verify`):** Validates existing JWT tokens.

### Key Dependencies

- `io.jsonwebtoken:jjwt-api:0.12.6`
- `io.jsonwebtoken:jjwt-impl:0.12.6`
- `io.jsonwebtoken:jjwt-jackson:0.12.6`
- `org.springframework.security:spring-security-crypto`

---

## 2. Central Database Schema (PostgreSQL 17)

The central database container (`dashboard_db`) runs PostgreSQL 17 Alpine on port `5432`.

### Core Tables

#### `users`
Stores user credentials and role authorizations.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | PRIMARY KEY | Unique user identifier |
| `username` | `VARCHAR(50)` | UNIQUE, NOT NULL | Login username |
| `password` | `VARCHAR(255)` | NOT NULL | BCrypt hashed password string |
| `role` | `VARCHAR(20)` | NOT NULL | Authorization role (`ROLE_ADMIN`, `ROLE_USER`) |
| `created_at` | `TIMESTAMP` | DEFAULT NOW() | Account creation timestamp |

#### `telegram_config`
Dynamic runtime configuration for the Telegram AI bot.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `id` | `SERIAL` | PRIMARY KEY | Configuration record ID |
| `bot_token` | `TEXT` | NOT NULL | Telegram Bot API token |
| `chat_id` | `TEXT` | NOT NULL | Target Telegram channel/chat ID |
| `enabled` | `BOOLEAN` | DEFAULT TRUE | Master switch for bot polling |
| `updated_at` | `TIMESTAMP` | DEFAULT NOW() | Last configuration modification |

#### `processed_telegram_updates`
Tracks processed Telegram update IDs to prevent duplicate command execution.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `update_id` | `BIGINT` | PRIMARY KEY | Unique Telegram Update ID |
| `processed_at` | `TIMESTAMP` | DEFAULT NOW() | Processing timestamp |

#### `facebook_config`
Configuration parameters for the Playwright Facebook E2EE automation worker.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `id` | `SERIAL` | PRIMARY KEY | Configuration identifier |
| `pin` | `VARCHAR(10)` | NULLABLE | 6-digit E2EE decryption PIN |
| `away_message` | `TEXT` | NULLABLE | Custom auto-reply message text |
| `enabled` | `BOOLEAN` | DEFAULT TRUE | Enable/disable Facebook scanner |
| `updated_at` | `TIMESTAMP` | DEFAULT NOW() | Last update timestamp |

#### `facebook_known_threads`
Maintains persistent state for Facebook conversation threads across container restarts.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `thread_id` | `VARCHAR(100)` | PRIMARY KEY | Facebook user/thread identifier |
| `sender_name` | `VARCHAR(255)` | NULLABLE | Friend or sender display name |
| `last_message_hash` | `VARCHAR(64)` | NULLABLE | MD5/SHA256 hash of latest seen message |
| `auto_reply_sent` | `BOOLEAN` | DEFAULT FALSE | Whether an away message was dispatched |
| `auto_reply_text` | `TEXT` | NULLABLE | Exact text of the auto-reply for revocation |
| `auto_reply_unsent`| `BOOLEAN` | DEFAULT FALSE | Flag indicating if message has been revoked |
| `last_seen_at` | `TIMESTAMP` | DEFAULT NOW() | Last scan timestamp |

---

## 3. Cross-Origin Resource Sharing (CORS)

Local development origins (`http://localhost:5173`, `http://127.0.0.1:5173`) are whitelisted across all microservices (`CorsConfig.java`). In production, Nginx proxies all requests under unified subpaths (`/api/auth/*`, `/api/metrics/*`, `/api/files/*`, `/api/facebook/*`, `/api/ai/*`, `/fb-vnc/*`), enforcing single-origin security.
