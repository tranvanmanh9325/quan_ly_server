package com.miniserver.dashboard.service;

import com.miniserver.dashboard.model.TelegramConfig;
import com.miniserver.dashboard.repository.TelegramConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Sends Telegram messages via the HTTP Bot API (no external library).
 *
 * Design choices:
 * - Uses Spring's RestClient (non-blocking-friendly, fluent API, no extra dependency).
 * - Config is always fetched fresh from DB so changes take effect without restart.
 * - Per-metric cooldown prevents alert spam: each metric type is tracked independently.
 */
@Service
public class TelegramNotificationService {

    private static final Logger log = LoggerFactory.getLogger(TelegramNotificationService.class);
    private static final String TG_API_BASE = "https://api.telegram.org/bot";
    // Always use Vietnam timezone — Docker Alpine containers default to UTC,
    // so ZoneId.systemDefault() would be wrong inside containers.
    private static final ZoneId TZ_VIETNAM = ZoneId.of("Asia/Ho_Chi_Minh");
    private static final DateTimeFormatter TIMESTAMP_FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(TZ_VIETNAM);

    private final TelegramConfigRepository configRepository;
    private final RestClient restClient;

    // Credentials injected from .env via application.properties.
    // These take priority over any value stored in the DB.
    @org.springframework.beans.factory.annotation.Value("${telegram.bot-token:}")
    private String envBotToken;

    @org.springframework.beans.factory.annotation.Value("${telegram.chat-id:}")
    private String envChatId;

    // cooldown tracking: metric key → last alert sent time
    private final Map<String, Instant> lastAlertTime = new ConcurrentHashMap<>();

    public TelegramNotificationService(TelegramConfigRepository configRepository) {
        this.configRepository = configRepository;
        this.restClient = RestClient.create();
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    /**
     * Resolves effective bot token: env var takes priority over DB value.
     * This allows credentials to live in .env without DB roundtrips.
     */
    private String resolveToken(TelegramConfig cfg) {
        return (envBotToken != null && !envBotToken.isBlank()) ? envBotToken : cfg.getBotToken();
    }

    private String resolveChatId(TelegramConfig cfg) {
        return (envChatId != null && !envChatId.isBlank()) ? envChatId : cfg.getChatId();
    }

    /**
     * Evaluates collected metrics against configured thresholds and sends
     * an alert if any threshold is exceeded AND the per-metric cooldown has expired.
     */
    public void checkAndAlert(double cpuPercent, double ramPercent, double diskPercent) {
        Optional<TelegramConfig> cfgOpt = configRepository.getConfig();
        if (cfgOpt.isEmpty()) return;

        TelegramConfig cfg = cfgOpt.get();
        if (!cfg.isEnabled()) return;

        String token  = resolveToken(cfg);
        String chatId = resolveChatId(cfg);
        if (token.isBlank() || chatId.isBlank()) return;

        boolean cpuAlert  = cpuPercent  > cfg.getCpuThreshold()  && isCooldownExpired("cpu",  cfg.getCooldownMinutes());
        boolean ramAlert  = ramPercent  > cfg.getRamThreshold()  && isCooldownExpired("ram",  cfg.getCooldownMinutes());
        boolean diskAlert = diskPercent > cfg.getDiskThreshold() && isCooldownExpired("disk", cfg.getCooldownMinutes());

        if (!cpuAlert && !ramAlert && !diskAlert) return;

        // Update cooldown timestamps for triggered alerts
        if (cpuAlert)  lastAlertTime.put("cpu",  Instant.now());
        if (ramAlert)  lastAlertTime.put("ram",  Instant.now());
        if (diskAlert) lastAlertTime.put("disk", Instant.now());

        String message = buildAlertMessage(cfg, cpuPercent, ramPercent, diskPercent,
                cpuAlert, ramAlert, diskAlert);

        // Use a temporary config copy with resolved credentials for sending
        TelegramConfig resolved = new TelegramConfig();
        resolved.setBotToken(resolveToken(cfg));
        resolved.setChatId(resolveChatId(cfg));
        sendMessage(resolved, message);
    }

    /** Sends an arbitrary text message to the configured chat. */
    public void sendMessage(String text) {
        configRepository.getConfig().ifPresent(cfg -> {
            String token  = resolveToken(cfg);
            String chatId = resolveChatId(cfg);
            if (!token.isBlank() && !chatId.isBlank()) {
                TelegramConfig resolved = new TelegramConfig();
                resolved.setBotToken(token);
                resolved.setChatId(chatId);
                sendMessage(resolved, text);
            }
        });
    }

    /**
     * Sends a "typing..." action to a specific chat.
     * Telegram shows this indicator for 5 seconds or until a message arrives.
     * Call this right before a slow operation (e.g. AI inference) to signal the bot is working.
     */
    public void sendTypingAction(String chatId) {
        configRepository.getConfig().ifPresent(cfg -> {
            String token = resolveToken(cfg);
            if (token.isBlank() || chatId.isBlank()) return;
            String url = TG_API_BASE + token + "/sendChatAction";
            try {
                restClient.post()
                        .uri(url)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(Map.of("chat_id", chatId, "action", "typing"))
                        .retrieve()
                        .toBodilessEntity();
            } catch (Exception e) {
                log.warn("[Telegram] Failed to send typing action: {}", e.getMessage());
            }
        });
    }

    /** Returns true if bot token and chat ID are both available (env or DB). */
    public boolean isConfigured() {
        if (envBotToken != null && !envBotToken.isBlank()
                && envChatId != null && !envChatId.isBlank()) return true;
        return configRepository.getConfig().map(this::isConfigured).orElse(false);
    }

    // ─── Internal helpers ────────────────────────────────────────────────────

    private boolean isConfigured(TelegramConfig cfg) {
        return cfg.getBotToken() != null && !cfg.getBotToken().isBlank()
                && cfg.getChatId() != null && !cfg.getChatId().isBlank();
    }

    private boolean isCooldownExpired(String metricKey, int cooldownMinutes) {
        Instant last = lastAlertTime.get(metricKey);
        if (last == null) return true;
        return Instant.now().isAfter(last.plusSeconds((long) cooldownMinutes * 60));
    }

    private void sendMessage(TelegramConfig cfg, String text) {
        String url = TG_API_BASE + cfg.getBotToken() + "/sendMessage";
        String sanitized = sanitizeMarkdown(text);
        try {
            // Attempt 1: with Markdown formatting
            restClient.post()
                    .uri(url)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("chat_id", cfg.getChatId(), "text", sanitized, "parse_mode", "Markdown"))
                    .retrieve()
                    .toBodilessEntity();
            log.debug("[Telegram] Message sent (Markdown).");
        } catch (HttpClientErrorException.BadRequest e) {
            // Markdown parse failed (special chars in text) — retry as plain text
            log.warn("[Telegram] Markdown parse failed, retrying as plain text.");
            try {
                restClient.post()
                        .uri(url)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(Map.of("chat_id", cfg.getChatId(), "text", text))
                        .retrieve()
                        .toBodilessEntity();
                log.debug("[Telegram] Message sent (plain text fallback).");
            } catch (Exception ex) {
                log.error("[Telegram] Plain text send also failed: {}", ex.getMessage());
            }
        } catch (Exception e) {
            log.error("[Telegram] Failed to send message: {}", e.getMessage());
        }
    }

    private String sanitizeMarkdown(String text) {
        if (text == null || text.isBlank()) return text;
        String[] lines = text.split("\n");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (line.contains("_") && !line.contains("`")) {
                line = line.replaceAll("(?<![`a-zA-Z0-9_/])([a-zA-Z0-9]+(?:_[a-zA-Z0-9-]+)+)(?![`a-zA-Z0-9_/])", "`$1`");
            }
            sb.append(line);
            if (i < lines.length - 1) sb.append("\n");
        }
        return sb.toString();
    }

    private String buildAlertMessage(TelegramConfig cfg,
                                     double cpu, double ram, double disk,
                                     boolean cpuAlert, boolean ramAlert, boolean diskAlert) {
        String now = TIMESTAMP_FMT.format(Instant.now());

        StringBuilder sb = new StringBuilder();
        sb.append("⚠️ *SERVER ALERT*\n");
        sb.append("━━━━━━━━━━━━━━━━━━\n");
        sb.append("📅 *Time:* `").append(now).append("`\n\n");

        sb.append(cpuAlert
                ? "🔴 *CPU:* `" + String.format("%.1f", cpu) + "%` \\(threshold: " + cfg.getCpuThreshold() + "%\\)\n"
                : "✅ *CPU:* `" + String.format("%.1f", cpu) + "%`\n");

        sb.append(ramAlert
                ? "🔴 *RAM:* `" + String.format("%.1f", ram) + "%` \\(threshold: " + cfg.getRamThreshold() + "%\\)\n"
                : "✅ *RAM:* `" + String.format("%.1f", ram) + "%`\n");

        sb.append(diskAlert
                ? "🔴 *Disk:* `" + String.format("%.1f", disk) + "%` \\(threshold: " + cfg.getDiskThreshold() + "%\\)\n"
                : "✅ *Disk:* `" + String.format("%.1f", disk) + "%`\n");

        sb.append("\n━━━━━━━━━━━━━━━━━━\n");
        sb.append("🖥 Check dashboard for details.");
        return sb.toString();
    }
}
