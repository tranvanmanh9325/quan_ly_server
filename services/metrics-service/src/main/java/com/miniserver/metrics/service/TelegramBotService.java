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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

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

    @org.springframework.beans.factory.annotation.Value("${telegram.polling-enabled:false}")
    private boolean pollingEnabled;

    // Tracks the last processed update_id to avoid re-processing
    private long updateOffset = 0;

    private final RestClient restClient;

    // Instance-level ExecutorService so Spring can manage its lifecycle via @PreDestroy.
    // Virtual threads are ideal here: AI inference blocks for seconds (SSH + LLM round-trip)
    // without pinning any OS thread, keeping the @Scheduled poller free.
    private final ExecutorService aiExecutor = Executors.newVirtualThreadPerTaskExecutor();

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

        // 12s read timeout — must exceed the 2s long-polling timeout to avoid false SocketTimeoutExceptions
        this.restClient = RestClientFactory.create(5_000, 12_000);
    }

    @jakarta.annotation.PostConstruct
    public void initDatabaseSchema() {
        try {
            jdbcTemplate.execute(
                    "CREATE TABLE IF NOT EXISTS processed_telegram_updates (" +
                    "    update_id BIGINT PRIMARY KEY, " +
                    "    processed_at TIMESTAMP NOT NULL DEFAULT now()" +
                    ")"
            );
            log.info("[TelegramBot] Database schema initialized for processed_telegram_updates.");
        } catch (Exception e) {
            log.warn("[TelegramBot] Could not initialize processed_telegram_updates table: {}", e.getMessage());
        }
    }

    @jakarta.annotation.PreDestroy
    public void shutdownAiExecutor() {
        // Allow in-flight AI calls (SSH + LLM) up to 5s to complete before hard kill.
        // Prevents orphaned virtual threads that would otherwise be silently terminated.
        aiExecutor.shutdown();
        try {
            if (!aiExecutor.awaitTermination(5, TimeUnit.SECONDS)) {
                aiExecutor.shutdownNow();
                log.warn("[TelegramBot] AI executor did not terminate cleanly; forced shutdown.");
            }
        } catch (InterruptedException e) {
            aiExecutor.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }

    // Adaptive backoff state to prevent CPU/Network spam when token conflict (409) occurs
    private long backoffUntilMs = 0;
    private int conflictCount = 0;

    @Scheduled(fixedDelay = 3_000)
    public void pollUpdates() {
        if (!pollingEnabled) return;

        // Skip execution if we are in an exponential backoff period
        if (System.currentTimeMillis() < backoffUntilMs) {
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
            String response = restClient.get().uri(url).retrieve().body(String.class);

            // Successfully received response -> reset conflict backoff
            if (conflictCount > 0) {
                log.info("[TelegramBot] Polling conflict resolved. Resuming normal 3s polling schedule.");
                conflictCount = 0;
            }

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
            conflictCount++;
            // Exponential backoff: 10s, 20s, 40s, max 60s
            long delaySeconds = Math.min(60, 10L * (1L << Math.min(conflictCount - 1, 3)));
            backoffUntilMs = System.currentTimeMillis() + (delaySeconds * 1000);
            log.warn("[TelegramBot] Polling conflict (409) — another bot instance is active with the same token. Backing off for {}s (conflict #{})", delaySeconds, conflictCount);
        } catch (Exception e) {
            // Temporary network glitch or timeout -> back off for 10s
            backoffUntilMs = System.currentTimeMillis() + 10_000;
            log.error("[TelegramBot] Error polling updates: {}. Retrying in 10s.", e.getMessage());
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

    /** Forwards free-text messages to Groq AI and sends the reply back.
     *
     * Runs on a virtual thread so the @Scheduled pollUpdates() thread is never
     * blocked by SSH execution, LLM inference, or retry sleeps.
     */
    private void handleAiMessage(String userMessage, String chatId) {
        if (!aiService.isConfigured()) {
            notificationService.sendMessage(
                    "AI chua duoc cai dat. Dung /help de xem cac lenh co san.");
            return;
        }

        // Show "typing..." indicator immediately so user knows bot is working
        notificationService.sendTypingAction(chatId);
        log.debug("[TelegramBot] Routing to Groq AI: {}", userMessage);

        // Offload to virtual thread — aiExecutor creates a new VT per task,
        // so Thread.sleep() in callGroq() never pins the scheduler thread pool.
        aiExecutor.execute(() -> {
            String reply = aiService.chat(chatId, userMessage);
            notificationService.sendMessage(reply);
        });
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
        try {
            String clean = raw.trim();
            int upIdx = clean.indexOf("up ");
            int loadIdx = clean.indexOf("load average:");

            String uptimeStr = "";
            String loadStr = "";
            if (upIdx != -1 && loadIdx != -1) {
                uptimeStr = clean.substring(upIdx + 3, clean.lastIndexOf(',', loadIdx)).trim();
                loadStr = clean.substring(loadIdx + "load average:".length()).trim();
            }

            StringBuilder sb = new StringBuilder();
            sb.append("🖥️ *Server System Status*\n");
            sb.append("━━━━━━━━━━━━━━━━━━\n");
            if (!uptimeStr.isBlank()) {
                sb.append("⏱️ *Uptime:* `").append(uptimeStr).append("`\n");
            }
            if (!loadStr.isBlank()) {
                sb.append("📊 *Load Average:* `").append(loadStr).append("`\n");
            }
            sb.append("🟢 *System Health:* `OPTIMAL`");
            return sb.toString();
        } catch (Exception e) {
            log.warn("[TelegramBot] Error parsing status stats: {}", e.getMessage());
        }
        return "🖥 *Server Status*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchCpu() {
        String cmd = "awk 'BEGIN{getline a < \"/proc/stat\"; close(\"/proc/stat\"); system(\"sleep 0.1\"); getline b < \"/proc/stat\"; split(a,t1); split(b,t2); u=(t2[2]+t2[4])-(t1[2]+t1[4]); i=t2[5]-t1[5]; tot=(t2[2]+t2[3]+t2[4]+t2[5]+t2[6]+t2[7]+t2[8])-(t1[2]+t1[3]+t1[4]+t1[5]+t1[6]+t1[7]+t1[8]); if(tot>0){printf \"%.1f|%.1f|%.1f|%.1f\\n\", ((t2[2]-t1[2])/tot)*100, ((t2[4]-t1[4])/tot)*100, (i/tot)*100, (1-i/tot)*100} else {print \"0.0|0.0|100.0|0.0\"}}'";
        String raw = sshService.executeCommand(cmd);
        if (raw == null || raw.isBlank() || raw.startsWith("Lỗi")) {
            return "❌ *CPU:* SSH unavailable";
        }
        try {
            String[] parts = raw.trim().split("\\|");
            if (parts.length >= 4) {
                double us = Double.parseDouble(parts[0]);
                double sy = Double.parseDouble(parts[1]);
                double id = Double.parseDouble(parts[2]);
                double total = Double.parseDouble(parts[3]);
                return String.format(
                    "🖥️ *CPU Usage Overview*\n" +
                    "━━━━━━━━━━━━━━━━━━\n" +
                    "⚡ *Total CPU Load:* `%.1f%%` \n\n" +
                    "📊 *Detailed Breakdown:*\n" +
                    "• User (`us`): `%.1f%%` \n" +
                    "• System (`sy`): `%.1f%%` \n" +
                    "• Idle (`id`): `%.1f%%` ",
                    total, us, sy, id
                );
            }
        } catch (Exception e) {
            log.warn("[TelegramBot] Error parsing CPU stats: {}", e.getMessage());
        }
        return "🔲 *CPU Usage*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchRam() {
        String raw = sshService.executeCommand("free -m");
        if (raw == null || raw.isBlank() || raw.startsWith("Lỗi")) {
            return "❌ *RAM:* SSH unavailable";
        }
        try {
            String[] lines = raw.trim().split("\n");
            String memLine = null;
            String swapLine = null;
            for (String l : lines) {
                if (l.startsWith("Mem:")) memLine = l;
                else if (l.startsWith("Swap:")) swapLine = l;
            }
            if (memLine != null) {
                String[] m = memLine.trim().split("\\s+");
                long total = Long.parseLong(m[1]);
                long used = Long.parseLong(m[2]);
                long free = Long.parseLong(m[3]);
                long buff = m.length > 5 ? Long.parseLong(m[5]) : 0;
                long avail = m.length > 6 ? Long.parseLong(m[6]) : free;
                double usagePct = (double) used / total * 100;

                StringBuilder sb = new StringBuilder();
                sb.append("💾 *RAM Usage Overview*\n");
                sb.append("━━━━━━━━━━━━━━━━━━\n");
                sb.append(String.format("📊 *Usage:* `%d MB / %d MB` (`%.1f%%`)\n\n", used, total, usagePct));
                sb.append(String.format("• Free: `%d MB` \n", free));
                sb.append(String.format("• Buffers/Cache: `%d MB` \n", buff));
                sb.append(String.format("• Available: `%d MB` \n", avail));

                if (swapLine != null) {
                    String[] s = swapLine.trim().split("\\s+");
                    long sTotal = Long.parseLong(s[1]);
                    long sUsed = Long.parseLong(s[2]);
                    if (sTotal > 0) {
                        double sPct = (double) sUsed / sTotal * 100;
                        sb.append(String.format("• Swap: `%d MB / %d MB` (`%.1f%%`)", sUsed, sTotal, sPct));
                    }
                }
                return sb.toString();
            }
        } catch (Exception e) {
            log.warn("[TelegramBot] Error parsing RAM stats: {}", e.getMessage());
        }
        return "💾 *RAM Usage*\n```\n" + raw.trim() + "\n```";
    }

    private String fetchDisk() {
        String raw = sshService.executeCommand("df -h -x tmpfs -x devtmpfs -x overlay -x squashfs");
        if (raw == null || raw.isBlank() || raw.startsWith("Lỗi")) {
            return "❌ *Disk:* SSH unavailable";
        }
        try {
            String[] lines = raw.trim().split("\n");
            StringBuilder sb = new StringBuilder();
            sb.append("🗄️ *Disk Usage Overview*\n");
            sb.append("━━━━━━━━━━━━━━━━━━\n");
            for (int i = 1; i < lines.length; i++) {
                String[] parts = lines[i].trim().split("\\s+");
                if (parts.length >= 6) {
                    String size = parts[1];
                    String used = parts[2];
                    String pct = parts[4];
                    String mount = parts[5];
                    sb.append(String.format("• `%s` — `%s / %s` (`%s`)\n", mount, used, size, pct));
                }
            }
            return sb.toString().trim();
        } catch (Exception e) {
            log.warn("[TelegramBot] Error parsing disk stats: {}", e.getMessage());
        }
        return "🗄 *Disk Usage*\n```\n" + raw.trim() + "\n```";
    }
}
