# Troubleshooting & Diagnostic Handbook

Runbooks, diagnostic procedures, and interactive decision trees for identifying and resolving common issues across the Mini Server Dashboard ecosystem.

---

## 1. Troubleshooting Decision Tree

```mermaid
flowchart TD
    ProblemStart(["⚠️ Incident / Issue Detected"]) --> Category{"Which subsystem is affected?"}

    Category -->|AI Agent / Groq / Vision| AIPath{"Error Type?"}
    Category -->|Telegram Bot| TGPath{"Formatting / Polling?"}
    Category -->|Video / Audio / Media| MediaPath{"Processing Error?"}
    Category -->|Facebook E2EE / TikTok| SocialPath{"Decryption / Sessions?"}
    Category -->|SSH / Telemetry / Network| SSHPath{"Connection / Network?"}

    AIPath -->|HTTP 413 Payload Too Large| Fix413["Active Context Compactor auto-condenses tools.\nEnsure envelope guard is active for special media."]
    AIPath -->|Wrong Server Location| FixLoc["Check SERVER_PHYSICAL_LOCATION in .env.\nGround Truth: Định Công, Hoàng Mai, Hà Nội."]
    AIPath -->|Non-ASCII Header Error| FixAscii["Ensure all HTTP custom headers (X-Title) use ASCII only."]

    TGPath -->|Raw HTML Tags Visible (<i>)| FixHTML["TelegramFormatter v2 uses _VALID_TAG_PATTERN to whitelist tags."]
    TGPath -->|Markdown Tables Broken| FixTable["TelegramFormatter auto-converts tables to Card layouts."]
    TGPath -->|Bot Not Responding| FixPolling["Check TELEGRAM_POLLING_ENABLED=true in .env.\nVerify token with curl api.telegram.org/bot<TOKEN>/getMe."]

    MediaPath -->|Whisper STT Distortion| FixASR["Visual-informed prompt bias + _normalize_video_speech_phonetics."]
    MediaPath -->|Video Bot Silence| FixDebounce["VideoDebounceManager holds 5s with inline buttons for follow-ups."]
    MediaPath -->|Archive Password Forgot| FixCrack["ArchiveRecoveryEngine provides 4-tier password recovery."]

    SocialPath -->|E2EE Chats Encrypted| FixPIN["Verify FB_PIN in .env or database.\nOpen http://<server-ip>:6080/vnc.html to inspect."]
    SocialPath -->|Absence Message Not Sent| FixAway["Check away_mode_enabled=true in facebook_config table."]

    SSHPath -->|Connection Timed Out| FixSSH["Verify SSH credentials & test: ssh -p 22 user@host.\nIf remote, verify Ngrok fallback tunnel."]
    SSHPath -->|Dual Wi-Fi Loss of SSH| FixBond["Wi-Fi bonding cannot use mode 0/4. Use ECMP with strict default route guard."]
```

---

## 2. Detailed Runbooks

### Runbook 1: Groq `HTTP 413 Payload Too Large`

- **Root Cause:** Accumulation of verbose raw shell outputs in multi-step agent reasoning turns or uncompressed media context.
- **Resolution:** The **Active Turn Context Compactor (`_build_compact_messages_for_llm`)** in `ai_agent.py` automatically retains full detail only for the 2 most recent tool outputs and collapses older outputs into 2-line summaries, capping turn payload under 3,500 characters (~900 tokens). For special structured attachments (`[🎬`, `[📄`), context is safely budgeted up to 8,000 characters with `_tok_synth = 2048`.

### Runbook 2: Server Location Discrepancy (GeoIP vs. Physical Location)

- **Root Cause:** Dynamic ISP IP blocks (`1.53.99.21`) route via central ISP BGP gateways which GeoIP services report as TP.HCM or Cầu Giấy.
- **Resolution:** Configured `SERVER_PHYSICAL_LOCATION="Định Công, Hoàng Mai, Hà Nội, Việt Nam"` in `.env` and `app/config.py`. The AI Agent explicitly explains the difference between ISP BGP GeoIP and on-premise hardware coordinates.

### Runbook 3: OpenRouter `reasoning_details` causing Groq `HTTP 400`

- **Root Cause:** Provider-specific reasoning fields returned by OpenRouter models are rejected by Groq API validation.
- **Resolution:** `LlmRouter.route_chat()` strips `reasoning_details` from message objects before constructing request payloads.

### Runbook 4: Telegram Markdown Entity Parsing Recovery

- **Root Cause:** Telegram API rejects unescaped raw HTML entities or unbalanced tags.
- **Resolution:** `TelegramFormatter` auto-balances open tags (`_balance_html_tags`) and `TelegramBot._send_single_chunk` provides an automated fallback that strips tags and resends plain text if entity parsing fails.

### Runbook 5: Whisper STT Acoustic Mismatch & Vietnamese Dialect Distortion

- **Root Cause:** Fast conversational speech, regional dialects (Nghệ An, Hà Tĩnh), and English loan words (*"drone show"*) cause acoustic confusion (e.g. *"19h ngày 12"* heard as *"19h22"*, *"drone show"* heard as *"đôi ôn show"*).
- **Resolution:**
  1. Inject contextual keywords via `prompt_bias` in `MediaProcessor.transcribe_voice()`.
  2. Apply regex phonetic post-correction in `MediaProcessor._normalize_video_speech_phonetics()` (e.g. converting `19h22` directly to `19h00 ngày 12`).
  3. Strip acoustic error keywords completely from the synthesized LLM prompt in `video_pipeline.py` to prevent LLM priming bias.

### Runbook 6: Raw HTML Tags Leaking in Telegram (`&lt;i&gt;` / `&lt;b&gt;`)

- **Root Cause:** `html.escape()` converts legitimate Telegram HTML formatting tags (`<i>`, `<b>`) into `&lt;i&gt;`, causing Telegram to render raw tags on screen.
- **Resolution:** `TelegramFormatter` uses `_VALID_TAG_PATTERN` to temporarily substitute valid Telegram tags with opaque tokens (`TGVALIDHTMLTAG{idx}END`) prior to `html.escape()`, and restores them in Step 9.

### Runbook 7: Double Context Payload Inflation via Dialect Normalizer

- **Root Cause:** `VietnameseLinguisticNormalizer.enrich_dialect_semantics()` appended `[Ý định & Ngữ nghĩa: ...]` to structured media envelopes, turning 6,000 characters of video data into 12,000 characters and triggering HTTP 413 errors.
- **Resolution:** Enforced **Envelope Guard**:
  `if text.startswith(("[📄", "[📸", "[🎤", "[📍", "[🎬")): return text`

### Runbook 8: `UnicodeEncodeError: 'ascii' codec can't encode character` in HTTP Headers

- **Root Cause:** `_OR_VISION_HEADERS_BASE` contained `"X-Title": "Tiểu Bảo Bảo AI Agent"`. Under RFC 7230, HTTP header values must strictly adhere to ISO-8859-1/ASCII.
- **Resolution:** Changed header to ASCII-safe text: `"X-Title": "Tieu Bao Bao AI Agent"`.

### Runbook 9: High-Speed Archive Cracker Password Interception

- **Root Cause:** When an encrypted RAR/ZIP file was pending, the user's natural language request (*"anh quên mật khẩu rồi bẻ khóa giúp anh"*) was mistaken for an actual password attempt.
- **Resolution:** Implemented intent regex detection (`quên pass`, `phá khóa`, `crack`, `bẻ khóa`) in `TelegramBot` to automatically route the archive to `ArchiveRecoveryEngine` instead of treating the sentence as a password.

### Runbook 10: Dual Wi-Fi Network Bonding Without Disconnecting SSH

- **Root Cause:** Standard Linux `bonding` (mode 0 balance-rr, mode 4 LACP) fails over Wi-Fi 802.11 client interfaces because Access Points drop non-matching MAC frames. Changing the default gateway disconnects active remote SSH sessions.
- **Resolution:** Do not use `bonding` module on Wi-Fi. Use **Equal-Cost Multi-Path (ECMP)** routing via `ip route add default scope global nexthop dev wlp2s0 weight 1 nexthop dev wlx... weight 1` with a persistent route guard for the primary SSH IP interface.

---

## 3. Diagnostic & Testing Commands

```bash
# Run all unit tests inside container
docker exec dashboard_ai_agent python -m unittest discover -v -s /app/tests

# Verify Telegram HTML tag preservation in container
docker exec dashboard_ai_agent python3 -c "
from app.core.telegram_formatter import TelegramFormatter
res = TelegramFormatter.format_for_telegram('⚡ <i>Đang phân tích...</i>')
assert '<i>Đang phân tích...</i>' in res
print('Formatter HTML Tag Whitelist: 100% OK')
"

# Check container health and logs
docker compose ps
docker compose logs --tail 50 dashboard_ai_agent
```
