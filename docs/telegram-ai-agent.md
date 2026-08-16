# Autonomous AI Agent ("Tiểu Bảo Bảo") & Multi-Provider Ecosystem

A comprehensive technical reference for the autonomous AI sysadmin assistant ("Tiểu Bảo Bảo"), the Multi-Provider LLM Pool (Groq + OpenRouter), Telegram Bot tool execution, and Facebook Messenger End-to-End Encrypted (E2EE) automation engine.

---

## 🌟 Overview

The **AI Agent Service (`ai-agent-service`)** is an autonomous operational microservice written in Python 3.11 (FastAPI). It runs 24/7 as a dedicated background worker to provide natural language server administration, system diagnostics, alert notifications, and multi-platform communications across **Telegram** and **Facebook Messenger E2EE**.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    AI Agent Service (:8084)                                     │
│                                                                                                 │
│   ┌───────────────────────────┐         ┌───────────────────────────────────────────────────┐   │
│   │   Telegram Bot Poller     │         │       Facebook Messenger E2EE Automation          │   │
│   │  (Long Polling Receiver)  │         │   (Playwright Headless Chromium + noVNC :6080)    │   │
│   └─────────────┬─────────────┘         └─────────────────────────┬─────────────────────────┘   │
│                 │                                                 │                             │
│                 │ Inbound Message / Command                       │ Inbound Messages / Decrypt  │
│                 ▼                                                 ▼                             │
│   ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                         Autonomous Agent Engine ("Tiểu Bảo Bảo")                        │   │
│   │               • Natural Language Understanding & Context Window Manager                 │   │
│   │               • Sysadmin Tool Calling Engine (run_command, sudo, docker)                │   │
│   │               • Absence Auto-Reply & Intelligent Message Revocation (Unsend)            │   │
│   └─────────────────────────────────────────────┬───────────────────────────────────────────┘   │
│                                                 │                                               │
│                                                 ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                   Multi-Provider Key Pool Engine (9router-style)                        │   │
│   │   Tier 1: Groq API Pool (Round-robin + 60s cooldown on 429 rate limit)                  │   │
│   │   Tier 2: OpenRouter API Pool (Automatic zero-downtime fallback failover)               │   │
│   └─────────────────────────────────────────────┬───────────────────────────────────────────┘   │
│                                                 │                                               │
│                 ┌───────────────────────────────┴───────────────────────────────┐               │
│                 ▼                                                               ▼               │
│   ┌───────────────────────────┐                                   ┌───────────────────────────┐ │
│   │    PostgreSQL Database    │                                   │    Remote Linux Host      │ │
│   │ (Thread State & History)  │                                   │ (SSH CLI Tool Execution)  │ │
│   └───────────────────────────┘                                   └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Multi-Provider LLM Key Pool Architecture

To eliminate single point of failure (SPOF) and circumvent strict free-tier rate limits, the AI Agent implements an advanced **Multi-Provider Key Pool**:

### Tier 1: Groq Multi-Key Pool (Primary Engine)
- **Model:** `openai/gpt-oss-120b` (or `llama-3.1-8b-instant`).
- **Key Rotation (9router pattern):** Automatically balances requests across multiple API keys (`GROQ_API_KEY`, `GROQ_API_KEY_2`, `GROQ_API_KEY_3`, ...).
- **Smart 60-second Cooldown:** When any key hits a `429 Rate limited` response, it enters a temporary 60-second cooldown while the pool immediately routes subsequent queries to the next healthy key in round-robin order.

### Tier 2: OpenRouter Multi-Key Pool (Automatic Fallback)
- **Model:** `nvidia/nemotron-3-super-120b-a12b:free` (or configured OpenRouter models).
- **Zero-Downtime Failover:** When all Groq keys are exhausted or unavailable, the system transparently falls back to the OpenRouter pool without dropping user sessions or throwing errors.

---

## 2. Telegram Bot Automation & Tool Calling

### Core Capabilities:
1. **Long Polling Receiver:** Asynchronously polls Telegram updates without requiring a public webhook domain.
2. **Autonomous Tool Calling:**
   - `run_command(command: str)`: Executes read-only system inspection commands (`top`, `free`, `df`, `ps`, `uptime`).
   - `sudo_command(command: str)`: Executes administrative commands with root privilege escalation.
   - `get_system_metrics()`: Directly gathers live CPU, RAM, Disk, and Network telemetry.
   - `docker_manage(container_id, action)`: Controls container lifecycles (start, stop, restart, inspect logs).
3. **Facebook Relay Command (`/reply <thread_id> <message>`):** Allows the owner to reply to incoming Facebook messages directly from Telegram.

---

## 3. Facebook Messenger E2EE Automation Engine

Built on top of **Playwright Python** with a dedicated headless Chromium instance and persistent browser profile storage (`browser_data:/app/browser_data`).

### Key Features:

1. **Automated E2EE PIN Recovery:**
   - Automatically detects Facebook End-to-End Encryption (E2EE) security challenge screens.
   - Types the user-configured 6-digit PIN into the encrypted pin pad to unlock conversation history.

2. **Absence Auto-Responder ("Báo vắng mặt"):**
   - Automatically scans incoming unread messages from friends/contacts.
   - Sends a polite absence notice: *"Chào bạn, tôi là Tiểu Bảo Bảo - trợ lý AI của anh Mạnh..."* when the owner is away.

3. **Intelligent Message Revocation (Auto-Unsend Engine):**
   - **DB-Backed State Tracking (`facebook_known_threads`):** Stores `auto_reply_text` and `auto_reply_unsent` state in PostgreSQL to ensure survival across container restarts.
   - **Human-Reply Detection:** Once the owner replies directly on Facebook Messenger or relays a message via Telegram (`/reply`), the bot detects that the latest message is from the human owner (`is_auto=False`).
   - **Automated Revocation Flow:**
     1. Navigates to the conversation thread.
     2. Locates the specific absence message bubble in the DOM.
     3. Hovers to trigger the action toolbar (`⋮ ↩ 😊`).
     4. Clicks the leftmost **"More" (⋮)** button.
     5. Selects **"Thu hồi"** (Unsend) from the context menu.
     6. Selects **"Thu hồi với mọi người"** (Unsend for everyone).
     7. Confirms by clicking **"Gỡ"** in the confirmation dialog.
     8. Updates database record (`auto_reply_text = ''`, `auto_reply_unsent = TRUE`).

4. **noVNC Interactive Visual Console (Port 6080):**
   - Bridges the headless Xvfb display via `x11vnc` + `noVNC`.
   - Access via browser at `http://localhost:6080/vnc.html` or through the dashboard at `/fb-vnc/` for visual debugging and manual 2FA verification.

---

## 4. Environment Variables Configuration

```dotenv
# ── Groq AI Pool ─────────────────────────────────────────────────────────────
GROQ_API_KEY=gsk_primary_key
GROQ_API_KEY_2=gsk_second_key
GROQ_MODEL=openai/gpt-oss-120b

# ── OpenRouter AI Pool ───────────────────────────────────────────────────────
OPENROUTER_API_KEY=sk-or-v1-primary_key
OPENROUTER_API_KEY_2=sk-or-v1-second_key
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free

# ── Telegram Bot ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_POLLING_ENABLED=true

# ── Facebook E2EE Automation ─────────────────────────────────────────────────
FB_PIN=your_6_digit_e2ee_pin
```
