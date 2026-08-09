package com.miniserver.metrics.controller;

import com.miniserver.metrics.model.TelegramConfig;
import com.miniserver.metrics.repository.TelegramConfigRepository;
import com.miniserver.metrics.service.TelegramNotificationService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;

/**
 * REST API for managing Telegram Bot configuration.
 * All endpoints are protected by JwtInterceptor (configured in WebMvcConfig).
 */
@RestController
@RequestMapping("/api/telegram")
public class TelegramController {

    private final TelegramConfigRepository configRepository;
    private final TelegramNotificationService notificationService;

    @org.springframework.beans.factory.annotation.Value("${telegram.bot-token:}")
    private String envBotToken;

    @org.springframework.beans.factory.annotation.Value("${telegram.chat-id:}")
    private String envChatId;

    public TelegramController(TelegramConfigRepository configRepository,
                              TelegramNotificationService notificationService) {
        this.configRepository = configRepository;
        this.notificationService = notificationService;
    }

    /** Returns current config — bot token is always masked; env var status shown separately */
    @GetMapping("/config")
    public Map<String, Object> getConfig() {
        TelegramConfig cfg = configRepository.getConfig().orElseGet(TelegramConfig::new);
        Map<String, Object> result = new HashMap<>();
        result.put("enabled",         cfg.isEnabled());
        result.put("chatId",          cfg.getChatId());
        result.put("cpuThreshold",    cfg.getCpuThreshold());
        result.put("ramThreshold",    cfg.getRamThreshold());
        result.put("diskThreshold",   cfg.getDiskThreshold());
        result.put("cooldownMinutes", cfg.getCooldownMinutes());
        // Token lives in .env — never expose it; just indicate if it is set
        boolean envTokenSet = envBotToken != null && !envBotToken.isBlank();
        result.put("botTokenMasked", envTokenSet ? "from .env ••••••••" : "");
        result.put("configured",     envTokenSet && !envChatId.isBlank());
        return result;
    }

    /** Saves Telegram config. Token & Chat ID are managed via .env — only other settings are persisted. */
    @PostMapping("/config")
    public ResponseEntity<Map<String, String>> saveConfig(@RequestBody Map<String, Object> body) {
        TelegramConfig cfg = configRepository.getConfig().orElseGet(TelegramConfig::new);

        // Token and chatId are managed via .env — ignore any values from request body
        // (keeping DB columns empty is fine; services resolve from env var first)

        if (body.containsKey("enabled"))
            cfg.setEnabled(Boolean.TRUE.equals(body.get("enabled")));

        if (body.get("cpuThreshold") instanceof Number n)
            cfg.setCpuThreshold(clamp(n.intValue(), 50, 100));

        if (body.get("ramThreshold") instanceof Number n)
            cfg.setRamThreshold(clamp(n.intValue(), 50, 100));

        if (body.get("diskThreshold") instanceof Number n)
            cfg.setDiskThreshold(clamp(n.intValue(), 50, 100));

        if (body.get("cooldownMinutes") instanceof Number n)
            cfg.setCooldownMinutes(clamp(n.intValue(), 1, 1440));

        configRepository.save(cfg);
        return ResponseEntity.ok(Map.of("status", "success", "message", "Telegram config saved."));
    }

    /** Sends a test message using credentials from .env */
    @PostMapping("/test")
    public Map<String, String> testMessage() {
        if (!notificationService.isConfigured()) {
            return Map.of("status", "error", "message", "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env");
        }

        String now = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
                .withZone(ZoneId.of("Asia/Ho_Chi_Minh"))
                .format(java.time.Instant.now());

        try {
            notificationService.sendMessage(
                    "✅ *Server Dashboard* \u2014 Test message\n📅 `" + now + "`\n\nBot is connected and working!"
            );
            return Map.of("status", "success", "message", "Test message sent! Check your Telegram.");
        } catch (Exception e) {
            return Map.of("status", "error", "message", "Failed: " + e.getMessage());
        }
    }

    private int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }
}
