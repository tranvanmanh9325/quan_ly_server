# Troubleshooting & Diagnostic Handbook

Runbooks and diagnostic procedures for identifying and resolving common issues across the Mini Server Dashboard ecosystem.

---

## 1. AI Agent & LLM Router Issues

### Symptom 1: Groq `HTTP 413 Payload Too Large`
- **Root Cause:** In earlier versions, running multiple consecutive shell commands accumulated large log outputs in the turn context, exceeding Groq's request size limit.
- **Resolution:** Upgraded with the **Active Turn Context Compactor (`_build_compact_messages_for_llm`)** in `ai_agent.py`. Tool outputs older than the 2 most recent steps are automatically condensed, keeping the payload under 3,500 characters (~900 tokens).

### Symptom 2: AI answers server location incorrectly (e.g. TP.HCM instead of Hà Nội)
- **Root Cause:** AI was querying dynamic ISP GeoIP databases (`ipinfo.io`) which assign ISP blocks to central BGP gateways rather than physical hardware addresses.
- **Resolution:** Configured `SERVER_PHYSICAL_LOCATION="Định Công, Hoàng Mai, Hà Nội, Việt Nam"` in `.env` and `app/config.py`. The AI's System Prompt now embeds Ground Truth physical metadata and explains the difference between ISP GeoIP and on-premise hardware location.

### Symptom 3: OpenRouter `reasoning_details` causes Groq `HTTP 400`
- **Root Cause:** When switching from OpenRouter to Groq, leftover `reasoning_details` properties in message history caused Groq API validation failures.
- **Resolution:** `LlmRouter.route_chat()` now sanitizes all message objects before constructing request payloads.

---

## 2. Telegram Bot Issues

### Symptom: Markdown tables or messages broken on Telegram
- **Root Cause:** Telegram does not support native Markdown pipe tables (`|---|---|`).
- **Resolution:** The `TelegramFormatter` engine automatically converts Markdown tables into formatted visual cards and converts Markdown to safe, balanced Telegram HTML.

---

## 3. Facebook Messenger E2EE & noVNC Issues

### Symptom: E2EE Encrypted messages not decrypting
- **Check 1:** Ensure `FB_PIN` (or pin code in database) is correctly set to your 6-digit security PIN.
- **Check 2:** Open `http://<server-ip>:6080/vnc.html` to visually check if Facebook is requesting 2FA or re-login.

---

## 4. SSH & Connectivity Issues

### Symptom: `SshException: Connection timed out`
- **Check 1:** Verify SSH credentials (`SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PASSWORD`) in `.env`.
- **Check 2:** Test SSH manually:
  ```bash
  ssh -p 22 kirito@192.168.0.100
  ```
- **Check 3:** If using Ngrok fallback, verify that `SSH_FALLBACK_HOST` and `SSH_FALLBACK_PORT` are updated.

---

## 5. Running Diagnostics & Tests

```bash
# Run all unit tests inside container
docker exec dashboard_ai_agent python -m unittest discover -v -s /app/tests

# Check container health and logs
docker compose ps
docker compose logs --tail 50 dashboard_ai_agent
```
