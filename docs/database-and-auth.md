# Database & Authentication

Complete guide to the PostgreSQL 17 relational schema, JWT authentication lifecycle, BCrypt credential security, and state persistence.

---

## 1. Database Overview

The system utilizes **PostgreSQL 17 Alpine** (container `dashboard_db`) running on internal port `5432`.

### Schema Map

```text
PostgreSQL (quan_ly_server)
├── users                        # Dashboard administrative user accounts
├── user_refresh_tokens          # Active JWT refresh tokens
├── telegram_configs             # Telegram bot credentials & notification thresholds
├── facebook_config              # Facebook E2EE automation settings & PIN
├── facebook_known_threads       # Tracked Messenger conversations & unsend state
├── facebook_messages            # Cached conversation history
├── facebook_appointments        # Appointments extracted from Messenger chats
├── tiktok_config                # TikTok DM & streak keeper settings
├── tiktok_streaks               # Tracked TikTok streaks & interaction logs
├── rtk_stats                    # 9Router Real-Time Token Compressor statistics
├── ai_chat_memories             # Long-term AI conversational memories
├── ai_agent_lessons             # Self-learned rules & corrections
├── ai_agent_preferences         # User preferences learned by AI
└── ai_scheduled_tasks           # AI background tasks and reminders
```

---

## 2. Table Specifications

### User & Authentication
- `users (id, username, password_hash, role, created_at, updated_at)`
- `user_refresh_tokens (id, user_id, token, expires_at, created_at)`

### Facebook & TikTok Automation
- `facebook_config (id, enabled, auto_reply_text, scan_interval_minutes, away_mode_enabled, pin_code, updated_at)`
- `facebook_known_threads (thread_id, thread_name, last_interaction, auto_reply_text, auto_reply_unsent, is_e2ee, is_group)`
- `facebook_appointments (id, thread_id, person_name, appointment_time, description, status, reminded_1h)`
- `tiktok_config (id, enabled, streak_enabled, auto_reply_text, scan_interval_minutes, updated_at)`
- `tiktok_streaks (user_id, username, streak_count, last_sent_time, last_received_time, status)`

### 9Router & AI Memory
- `rtk_stats (id, total_compressions, chars_saved, estimated_tokens_saved, updated_at)`
- `ai_chat_memories (id, chat_id, key, value, created_at, updated_at)`
- `ai_agent_lessons (id, category, lesson, context, confidence, created_at)`
- `ai_agent_preferences (id, user_id, preference_key, preference_value, updated_at)`
- `ai_scheduled_tasks (id, task_type, payload, run_at, status)`

---

## 3. JWT Authentication Lifecycle

```text
Client                          auth-service                       Protected Services
  │                                  │                                     │
  ├── 1. POST /api/auth/login ──────▶│                                     │
  │      {"username", "password"}    │ (BCrypt check cost 12)              │
  │                                  │ (Generate Access + Refresh Tokens)  │
  │◀── 2. Return Tokens ─────────────┤                                     │
  │      {accessToken, refreshToken} │                                     │
  │                                                                        │
  ├── 3. GET /api/metrics/cpu (Bearer accessToken) ───────────────────────▶│
  │                                                                        │ (Verify JWT Secret)
  │◀── 4. Telemetry Response ──────────────────────────────────────────────┤
```

- **Access Token:** Short-lived (15 minutes), signed with HS256 / HS384.
- **Refresh Token:** Long-lived (7 days), stored in `user_refresh_tokens`.
