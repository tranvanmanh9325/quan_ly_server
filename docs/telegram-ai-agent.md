# Telegram AI Agent & Groq Integration

A comprehensive guide to the autonomous Telegram AI agent, Groq LLM function calling pipeline, context window management, and SSH command execution engine.

---

## Overview

The Mini Server Dashboard integrates an autonomous AI sysadmin assistant into Telegram (`AiChatService`, `TelegramBotService`). Users can query system status or issue administrative instructions in natural language directly via Telegram. The AI parses the request, decides whether to invoke shell commands via SSH, executes them, and returns formatted diagnostic summaries.

```text
User Message (Telegram)
        │
        ▼
TelegramBotService (Long Polling)
        │
        ▼
AiChatService ───▶ Groq REST API (llama-3.1-8b-instant)
        │                 │
        │                 ▼ (Tool Call: run_command)
        ├───────▶ SshService (executeCommand / executeSudoCommand)
        │                 │
        │                 ▼
        │        Remote Linux Host
        │                 │
        │ ◀───────────────┘ (stdout / stderr)
        │
        ▼ (Interpreted Summary)
Telegram API ───▶ User Telegram Client
```

---

## 1. Core Services

### `TelegramBotService.java`

- **Long Polling Receiver:** Continuously polls updates from `https://api.telegram.org/bot<TOKEN>/getUpdates?offset=<OFFSET>&timeout=2`.
- **Thread Timeout Hardening:** Configured with `SimpleClientHttpRequestFactory` (5s connect timeout, 12s read timeout) to prevent JVM HTTP worker threads from locking up on dropped TCP packets.
- **Multithreading:** Runs on a dedicated thread pool managed by `SchedulingConfig` (5 worker threads).

### `AiChatService.java`

- **LLM Model:** `llama-3.1-8b-instant` via Groq Cloud REST API.
- **Function Calling / Tool Use:** Exposes `run_command` schema to Groq:

  ```json
  {
    "name": "run_command",
    "description": "Execute a bash shell command on the remote server to fetch real-time data.",
    "parameters": {
      "type": "object",
      "properties": {
        "command": { "type": "string", "description": "The exact bash command to execute" }
      },
      "required": ["command"]
    }
  }
  ```

---

## 2. Token & Rate Limit Protection (Groq Free Tier)

Groq's free tier imposes a strict limit of **6,000 Tokens Per Minute (TPM)**. To guarantee zero rate-limit crashes (`429 Rate limited`) or JSON parsing errors (`400 Bad Request`), the system enforces:

### Rolling Context Window

- `MAX_HISTORY_MESSAGES = 6` (keeps only the last 3 Q&A turns per chat ID).
- `MAX_OUTPUT_CHARS = 1000` (truncates large SSH command outputs before appending to LLM prompt).

### Resiliency & Backoff Retry

- **429 Rate Limit Handling:** Retries up to 3 times with a **2.5-second exponential backoff delay**.
- **Self-Healing State Reset:** If a 400 Bad Request or 429 error occurs, `AiChatService` automatically calls `clearHistory(chatId)` to purge corrupted context and allow immediate subsequent user queries.

### Strict System Prompt Guardrails

- **No Double Quotes:** Instructs LLM to exclusively use single quotes (`'`) for string arguments (e.g. `grep 'pattern'`), preventing nested unescaped double quotes from breaking Groq's JSON payload.
- **No `history` Command:** Explicitly bans `history` (unsupported in non-interactive SSH subshells).
- **Exact Log Commands:** Guides LLM to use `stat /var/lib/apt/periodic/update-success-stamp` and `grep -E 'Start-Date|Commandline' /var/log/apt/history.log` for checking system update history.

---

## 3. SSH Command & Sudo Execution

When Groq requests a `run_command` tool call:

1. `AiChatService` inspects the command string.
2. If the command requires administrative rights (e.g. `apt`, `systemctl`), it delegates to `SshService.executeSudoCommand(timedCommand)`.
3. `executeSudoCommand` pipes `SSH_PASSWORD + "\n"` into `sudo -S` via stdin, executing non-interactive privileged operations seamlessly.

---

## 4. Environment Configuration

Set the following variables in `backend/.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_allowed_chat_id
GROQ_API_KEY=your_groq_api_key
TELEGRAM_POLLING_ENABLED=true
```
