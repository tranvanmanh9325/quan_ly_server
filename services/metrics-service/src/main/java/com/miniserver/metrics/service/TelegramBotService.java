package com.miniserver.metrics.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.miniserver.metrics.model.TelegramConfig;
import com.miniserver.metrics.repository.TelegramConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import java.util.Optional;

/**
 * Long-Polling service for receiving Telegram Bot updates.
 *
 * Polls /getUpdates every 3 seconds (fixedDelay ensures no overlap).
 * Only responds to messages from the configured chat_id (security guard).
 * Uses PostgreSQL atomic lock (`processed_telegram_updates`) to guarantee
 * single-instance execution across multi-node/dev+prod environments.
 *
 * Routing logic:
 *   • Messages starting with "/" → slash commands (handled locally).
 *   • All other messages         → forwarded to Groq AI for response.
 */
@Service
public class TelegramBotService {

    private static final Logger log = LoggerFactory.getLogger(TelegramBotService.class);
    private static final String TG_API_BASE = "https://api.telegram.org/bot";

    private final TelegramConfigRepository configRepository;
    private final TelegramNotificationService notificationService;
    private final SshService sshService;
    private final AiChatService aiService;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @org.springframework.beans.factory.annotation.Value("${telegram.bot-token:}")
    private String envBotToken;

    @org.springframework.beans.factory.annotation.Value("${telegram.chat-id:}")
    private String envChatId;

    @org.springframework.beans.factory.annotation.Value("${telegram.polling-enabled:true}")
    private boolean pollingEnabled;

    @org.springframework.beans.factory.annotation.Value("${telegram.node-type:dev}")
    private String nodeType;

    // Tracks the last processed update_id to avoid re-processing
    private long updateOffset = 0;

    public TelegramBotService(TelegramConfigRepository configRepository,
                              TelegramNotificationService notificationService,
                              SshService sshService,
                              AiChatService aiService,
                              JdbcTemplate jdbcTemplate) {
        this.configRepository = configRepository;
        this.notificationService = notificationService;
        this.sshService = sshService;
        this.aiService = aiService;
        this.jdbcTemplate = jdbcTemplate;
    }

    @Scheduled(fixedDelay = 5_000)
    public void sendNodeHeartbeat() {
        if ("dev".equalsIgnoreCase(nodeType) && pollingEnabled) {
            try {
                jdbcTemplate.update(
                        "INSERT INTO telegram_active_node (id, node_name, last_heartbeat) VALUES (1, 'dev', now()) " +
                        "ON CONFLICT (id) DO UPDATE SET node_name = 'dev', last_heartbeat = now()"
                );
            } catch (Exception e) {
                log.debug("[TelegramBot] Heartbeat error: {}", e.getMessage());
            }
        }
    }

    private boolean isDevNodeActive() {
        try {
            Integer count = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM telegram_active_node WHERE node_name = 'dev' AND last_heartbeat > now() - INTERVAL '15 seconds'",
                    Integer.class
            );
            return count != null && count > 0;
        } catch (Exception e) {
            return false;
        }
    }

    @Scheduled(fixedDelay = 3_000)
    public void pollUpdates() {
        if (!pollingEnabled) return;

        // Dev priority guard: If running in production, yield immediately to active Dev node
        if ("prod".equalsIgnoreCase(nodeType) && isDevNodeActive()) {
            log.debug("[TelegramBot] Dev node is active. Production standing down.");
            return;
        }

        Optional<TelegramConfig> cfgOpt = configRepository.getConfig();
        TelegramConfig cfg = cfgOpt.orElseGet(TelegramConfig::new);

        String token  = (envBotToken != null && !envBotToken.isBlank()) ? envBotToken : cfg.getBotToken();
        String chatId = (envChatId  != null && !envChatId.isBlank())  ? envChatId  : cfg.getChatId();

        boolean isEnvConfigured = (envBotToken != null && !envBotToken.isBlank()) && (envChatId != null && !envChatId.isBlank());
        boolean isEnabled = isEnvConfigured || cfg.isEnabled();

        if (!isEnabled || token.isBlank() || chatId.isBlank()) return;

        String url = TG_API_BASE + token + "/getUpdates?timeout=2&offset=" + updateOffset;

        try {
            String response = RestClient.create().get().uri(url).retrieve().body(String.class);
            if (response == null || response.isBlank()) return;

            JsonNode root = objectMapper.readTree(response);
            if (!root.path("ok").asBoolean()) return;

            for (JsonNode update : root.path("result")) {
                long updateId = update.path("update_id").asLong();
                updateOffset = Math.max(updateOffset, updateId + 1);

                // Atomic distributed lock: Claim update_id in DB (ON CONFLICT DO NOTHING)
                if (!claimUpdate(updateId)) {
                    log.info("[TelegramBot] Update ID {} already processed by another instance. Skipping.", updateId);
                    continue;
                }

                JsonNode message = update.path("message");
                if (message.isMissingNode()) continue;

                long chatIdLong = message.path("chat").path("id").asLong();
                String text     = message.path("text").asText("").trim();

                // Security guard: only respond to the configured chat_id
                if (!String.valueOf(chatIdLong).equals(chatId)) {
                    log.warn("[TelegramBot] Ignoring message from unauthorized chat_id: {}", chatIdLong);
                    continue;
                }

                if (text.isBlank()) continue;

                // Route: slash commands → local handlers, everything else → Groq AI
                if (text.startsWith("/")) {
                    handleCommand(text, String.valueOf(chatIdLong));
                } else {
                    handleAiMessage(text, String.valueOf(chatIdLong));
                }
            }
        } catch (HttpClientErrorException.Conflict e) {
            log.warn("[TelegramBot] Polling conflict (409) — another bot instance is active with the same token.");
        } catch (Exception e) {
            log.error("[TelegramBot] Error polling updates: {}", e.getMessage());
        }
    }

    private boolean claimUpdate(long updateId) {
        try {
            int rows = jdbcTemplate.update(
                    "INSERT INTO processed_telegram_updates (update_id) VALUES (?) ON CONFLICT (update_id) DO NOTHING",
                    updateId
            );
            return rows > 0;
        } catch (Exception e) {
            log.warn("[TelegramBot] Could not claim updateId {}: {}", updateId, e.getMessage());
            return true;
        }
    }

    @Scheduled(fixedDelay = 3_600_000)
    public void cleanupOldUpdates() {
        try {
            jdbcTemplate.update("DELETE FROM processed_telegram_updates WHERE processed_at < now() - INTERVAL '24 hours'");
        } catch (Exception e) {
            log.warn("[TelegramBot] Failed to cleanup old update IDs: {}", e.getMessage());
        }
    }

    // ─── Command Handlers ────────────────────────────────────────────────────

    private void handleCommand(String text, String chatId) {
        // Strip bot username suffix: "/start@MyBot" → "/start"
        String command = text.contains("@") ? text.substring(0, text.indexOf('@')) : text;
        command = command.toLowerCase();

        switch (command) {
            case "/start", "/help" -> notificationService.sendMessage(buildHelpMessage());
            case "/status"         -> notificationService.sendMessage(fetchStatus());
            case "/cpu"            -> notificationService.sendMessage(fetchCpu());
            case "/ram"            -> notificationService.sendMessage(fetchRam());
            case "/disk"           -> notificationService.sendMessage(fetchDisk());
            case "/ai"             -> {
                aiService.clearHistory(chatId);
                notificationService.sendMessage(
                        "Lich su cuoc tro chuyen AI da duoc xoa.\n" +
                        "Ban co the bat dau cuoc hoi thoai moi.");
            }
            default -> {
                // Unknown slash command → let AI handle it (user might mistype a command)
                handleAiMessage(text, chatId);
            }
        }
    }

    /** Forwards free-text messages to Groq AI and sends the reply back. */
    private void handleAiMessage(String userMessage, String chatId) {
        if (!aiService.isConfigured()) {
            notificationService.sendMessage(
                    "AI chua duoc cai dat. Dung /help de xem cac lenh co san.");
            return;
        }

        // Show "typing..." indicator immediately so user knows bot is working
        notificationService.sendTypingAction(chatId);
        log.debug("[TelegramBot] Routing to Groq AI: {}", userMessage);

        String reply = aiService.chat(chatId, userMessage);
        notificationService.sendMessage(reply);
    }

    // ─── SSH data fetchers ───────────────────────────────────────────────────

    private String buildHelpMessage() {
        boolean aiEnabled = aiService.isConfigured();
        return "🤖 *Server Monitor Bot*\n" +
               "━━━━━━━━━━━━━━━━━━\n" +
               "📊 *Commands:*\n\n" +
               "/status — Server uptime & load\n" +
               "/cpu    — CPU usage\n" +
               "/ram    — RAM usage\n" +
               "/disk   — Disk usage\n" +
               "/ai     — Clear AI chat history\n" +
               "/help   — Show this message\n\n" +
               "━━━━━━━━━━━━━━━━━━\n" +
               (aiEnabled
                   ? "✨ *AI Assistant active* — just type any question!"
                   : "⚠️ AI not configured (GROQ_API_KEY missing)");
    }

    private String fetchStatus() {
        String raw = sshService.executeCommand("uptime");
        if (raw == null || raw.isBlank() || raw.startsWith("Lỗi")) {
            return "❌ *Status:* SSH unavailable";
        }
        return "🖥 *Server Status*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchCpu() {
        String raw = sshService.executeCommand("top -b -n 2 -d 0.2 | grep 'Cpu(s)' | tail -n 1");
        if (raw == null || raw.isBlank()) return "❌ *CPU:* SSH unavailable";
        return "🔲 *CPU Usage*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchRam() {
        String raw = sshService.executeCommand("free -m");
        if (raw == null || raw.isBlank()) return "❌ *RAM:* SSH unavailable";
        return "💾 *RAM Usage*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchDisk() {
        String raw = sshService.executeCommand("df -h -x tmpfs -x devtmpfs");
        if (raw == null || raw.isBlank()) return "❌ *Disk:* SSH unavailable";
        return "🗄 *Disk Usage*\n```\n" + raw.trim() + "\n```";
    }
}
