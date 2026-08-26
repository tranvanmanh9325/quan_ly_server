# Autonomous AI Agent ("Tiểu Bảo Bảo") & 9Router Ecosystem

A comprehensive technical reference for the autonomous AI sysadmin assistant ("Tiểu Bảo Bảo"), the 9Router Multi-Provider LLM Pool (Groq + OpenRouter), Telegram Bot automation, and Facebook Messenger End-to-End Encrypted (E2EE) automation engine.

---

## 🌟 Overview

The **AI Agent Service (`ai-agent-service`)** is an autonomous operational microservice written in Python 3.11 (FastAPI). It runs 24/7 as a dedicated background worker providing natural language server administration, automated diagnostics, proactive alert notifications, and multi-platform communications across **Telegram** and **Facebook Messenger E2EE**.

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
│   │   • Pyramid Principle (BLUF - Bottom Line Up Front) Thinking Engine                     │   │
│   │   • Telegram Native Formatter (Table-to-Card, Balanced HTML, Vietnamese Normalizer)     │   │
│   │   • Active Turn Context Compactor & Anti-Loop Circuit Breaker (Anti-HTTP 413)           │   │
│   │   • Ground Truth Physical Location Metadata (Định Công, Hoàng Mai, Hà Nội)              │   │
│   │   • Sysadmin Tool Calling Engine (run_command, sudo, docker, browser, memory)          │   │
│   │   • Long-Term Memory Engine (AgentMemoryService: Lessons, Preferences, Reminders)       │   │
│   └─────────────────────────────────────────────┬───────────────────────────────────────────┘   │
│                                                 │                                               │
│                                                 ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│   │                   9Router Multi-Provider Key Pool & RTK Engine                          │   │
│   │   Tier 1: Groq API Pool (Round-robin + 60s cooldown on 429 rate limits)                 │   │
│   │   Tier 2: OpenRouter API Pool (Automatic zero-downtime failover)                       │   │
│   │   RTK: Real-Time Token Compressor (40–85% token volume reduction, DB persisted)         │   │
│   │   OpenAI-Compatible Gateway (/v1/chat/completions, /v1/models)                          │   │
│   └─────────────────────────────────────────────┬───────────────────────────────────────────┘   │
│                                                 │                                               │
│                 ┌───────────────────────────────┴───────────────────────────────┐               │
│                 ▼                                                               ▼               │
│   ┌───────────────────────────┐                                   ┌───────────────────────────┐ │
│   │    PostgreSQL Database    │                                   │    Remote Linux Host      │ │
│   │ (Thread State, Memories)  │                                   │ (AsyncSSH Tool Execution) │ │
│   └───────────────────────────┘                                   └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Pyramid Principle & BLUF Thinking Engine

To ensure all answers are crystal clear, direct, and actionable, the agent is governed by the **Pyramid Principle / BLUF (Bottom Line Up Front)**:

1. **Step 1: Direct Answer (Executive Summary)**
   - The very first line immediately delivers the definitive conclusion (1–2 sentences).
   - *Example:* `🎯 **KẾT QUẢ KIỂM TRA:** Dạ vâng anh Mạnh, lệnh sudo apt update ĐÃ ĐƯỢC CHẠY sáng nay (06:00 ICT) qua Systemd Timer apt-daily.service ạ!`
2. **Step 2: Verified Breakdown (High-Contrast Visual Cards)**
   - Key evidence is organized into card structures using emoji anchors (`📌`, `🕒`, `✅`, `🔍`).
   - Markdown tables are strictly transformed into cards to prevent Telegram layout breakage.
3. **Step 3: Actionable Insights & Guidance**
   - Concise technical explanations (e.g. why modern Ubuntu uses Systemd Timers over `cron.daily`).
   - Actionable recommendations or next steps.

---

## 2. Telegram Native Formatter Engine (`TelegramFormatter`)

Located in [`app/core/telegram_formatter.py`](../services/ai-agent-service/app/core/telegram_formatter.py):

- **Table-to-Card Transformer:** Converts raw Markdown tables (`|---|---|`) into formatted mobile-friendly bullet cards with header-value pairs.
- **Safe HTML Sanitization & Tag Balancing:** Converts Markdown to Telegram HTML (`<b>`, `<i>`, `<code>`, `<pre><code>`, `<blockquote>`, `<s>`), auto-escapes raw `<`, `>`, `&`, and balances any unclosed tags.
- **Collision-Free Placeholders:** Protects code blocks with alphanumeric tokens (`TGTOKENCODEBLOCK0END`, `TGTOKENINLINECODE0END`) preventing regex conflicts.
- **Vietnamese Typography & Spelling Auto-Normalizer:**
  - Fixes common slips (`"KẾ THÚC"` $\rightarrow$ `"KẾT LUẬN"`).
  - Normalizes timestamps (`"06:00 h"` $\rightarrow$ `"06:00"`).
  - Converts Unicode non-breaking hyphens (`\u2011`, `\u2013`, `\u2014`) to standard ASCII `-`.
  - Filters leaked multilingual/foreign tokens (`eindeutig` $\rightarrow$ `rõ ràng`, `ước lượngrough` $\rightarrow$ `ước lượng`, strips stray CJK).
- **Smart Message Chunker:** Safely splits long responses (>4,000 chars) on paragraph boundaries without breaking HTML tags.

---

## 3. Active Turn Context Compactor & Anti-Loop Circuit Breaker

Located in [`app/services/ai_agent.py`](../services/ai-agent-service/app/services/ai_agent.py):

1. **Active Turn Context Compactor (`_build_compact_messages_for_llm`):**
   - Progressively compresses older tool outputs in the current multi-step reasoning turn.
   - Retains full detail for the most recent 1–2 tool outputs, while collapsing older ones into 2-line summaries.
   - Caps total LLM request payload $\le 3,500$ chars (~900 tokens), **100% eliminating Groq `HTTP 413 Payload Too Large` errors**.
2. **Loop Detection & Circuit Breaker:**
   - Tracks executed bash commands (`executed_commands = set()`) to block duplicate executions.
   - Injects a synthesis directive when `iteration >= 3`.
   - Forces `tool_choice = "none"` when `iteration >= 4` or 3 commands have run, forcing the model to synthesize immediately.
3. **Graceful Final Synthesis Fallback:**
   - When loop limits are reached, the agent triggers a final synthesis pass to answer from accumulated context rather than failing with robotic error messages.

---

## 4. Ground Truth Physical Location Metadata

Configured in [`.env`](../.env) and [`app/config.py`](../services/ai-agent-service/app/config.py):

- **Physical Server Location:** `Định Công, Hoàng Mai, Hà Nội, Việt Nam` (On-premise hardware of anh Trần Văn Mạnh).
- **Network Infrastructure:** FPT Telecom (LAN: `192.168.0.100`, Public IP: `1.53.99.21`).
- **GeoIP vs. Physical Location Disambiguation:**
  - AI explicitly understands that dynamic ISP IP blocks route through central BGP gateways (which GeoIP services like `ipinfo.io` may report as TP.HCM or Cầu Giấy), while the physical on-premise hardware is 100% located at **Định Công, Hoàng Mai, Hà Nội**.

---

## 5. 9Router Multi-Provider Key Pool Architecture

Located in [`app/core/llm_router.py`](../services/ai-agent-service/app/core/llm_router.py):

### Tier 1: Groq Multi-Key Pool (Primary Engine)
- **Model:** `openai/gpt-oss-120b` (or `llama-3.1-8b-instant`).
- **Round-Robin Rotation:** Balances requests across all configured Groq keys (`GROQ_API_KEY`, `GROQ_API_KEY_2`, ...).
- **Smart 60-second Cooldown:** When a key hits `429 Rate limited`, it enters a 60s cooldown while subsequent queries route to healthy keys.

### Tier 2: OpenRouter Multi-Key Pool (Zero-Downtime Fallback)
- **Model:** `nvidia/nemotron-3-super-120b-a12b:free` (or custom models).
- **Auto-Failover:** Automatically triggers when Tier 1 keys are exhausted.
- **Payload Sanitization:** Strips provider-specific fields like `reasoning_details` before sending to Groq (preventing `HTTP 400`).

### Real-Time Token Compressor (RTK)
- Compacts JSON, removes ANSI color escapes, condenses repetitive dividers, and samples verbose log streams.
- Achieves 40–85% reduction in token consumption with stats persisted to PostgreSQL table `rtk_stats`.

---

## 6. Facebook Messenger E2EE Automation Engine

Located in [`app/services/facebook_service.py`](../services/ai-agent-service/app/services/facebook_service.py):

- **Playwright Chromium:** Runs in an isolated container with persistent session storage (`browser_data:/app/browser_data`).
- **Automated 6-Digit PIN Unlock:** Detects E2EE security PIN challenge screens and enters the configured PIN to decrypt chats.
- **Absence Auto-Responder:** Sends polite absence messages when the owner is offline.
- **Intelligent Message Revocation (Auto-Unsend):**
  - Tracks auto-reply state in table `facebook_known_threads`.
  - When the owner replies directly or via Telegram `/reply`, the bot locates the absence bubble, clicks `⋮` $\rightarrow$ `Thu hồi` $\rightarrow$ `Thu hồi với mọi người` $\rightarrow$ `Gỡ`.
- **noVNC Visual Console (Port 6080):** Access live browser stream at `http://localhost:6080/vnc.html` or `/fb-vnc/`.

---

## 7. TikTok Automation & Long-Term Memory

- **TikTok Streak Keeper ([`app/services/tiktok_service.py`](../services/ai-agent-service/app/services/tiktok_service.py)):** Automated check-ins, inbox scanning, and streak maintenance.
- **Proactive Appointment Reminders ([`app/services/appointment_service.py`](../services/ai-agent-service/app/services/appointment_service.py)):** Scans upcoming appointments and sends proactive 1-hour Telegram reminders.
- **Self-Learning Memory Engine ([`app/services/memory_service.py`](../services/ai-agent-service/app/services/memory_service.py)):** Stores cross-session memories in PostgreSQL (`ai_chat_memories`, `ai_agent_lessons`, `ai_agent_preferences`, `ai_scheduled_tasks`), allowing the agent to continuously learn from user feedback.

---

## 8. Unit Testing & Verification

Run the test suite inside the container:
```bash
docker exec dashboard_ai_agent python -m unittest discover -v -s /app/tests
```

**Test Suites:**
- `test_telegram_formatter.py` (11 tests): Markdown tables to cards, tag balancing, HTML sanitization, typography normalization, multilingual slip filter.
- `test_agent_loop_breaker.py` (2 tests): Context compaction and synthesis directive injection.
