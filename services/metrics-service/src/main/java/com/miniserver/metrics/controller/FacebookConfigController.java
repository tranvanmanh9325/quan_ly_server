package com.miniserver.metrics.controller;

import com.miniserver.metrics.model.FacebookConfig;
import com.miniserver.metrics.repository.FacebookConfigRepository;
import com.miniserver.metrics.service.AiChatService;
import com.miniserver.metrics.service.FacebookMessengerService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/facebook")
public class FacebookConfigController {

    private final FacebookConfigRepository configRepository;
    private final FacebookMessengerService messengerService;
    private final AiChatService aiChatService;

    public FacebookConfigController(FacebookConfigRepository configRepository,
                                    FacebookMessengerService messengerService,
                                    AiChatService aiChatService) {
        this.configRepository = configRepository;
        this.messengerService = messengerService;
        this.aiChatService = aiChatService;
    }

    @GetMapping("/config")
    public ResponseEntity<FacebookConfig> getConfig() {
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        return ResponseEntity.ok(cfg);
    }

    @PostMapping("/config")
    public ResponseEntity<FacebookConfig> updateConfig(@RequestBody FacebookConfig input) {
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        cfg.setEnabled(input.isEnabled());
        cfg.setThreshold(Math.max(1, input.getThreshold()));
        if (input.getScanIntervalMinutes() > 0) cfg.setScanIntervalMinutes(input.getScanIntervalMinutes());
        if (input.getCustomMessage() != null) cfg.setCustomMessage(input.getCustomMessage());
        if (input.getCookiesJson() != null && !input.getCookiesJson().isBlank()) cfg.setCookiesJson(input.getCookiesJson());
        FacebookConfig saved = configRepository.save(cfg);
        return ResponseEntity.ok(saved);
    }

    @PostMapping("/cookies")
    public ResponseEntity<Map<String, String>> updateCookies(@RequestBody Map<String, String> body) {
        String cookiesJson = body.getOrDefault("cookiesJson", "");
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        cfg.setCookiesJson(cookiesJson);
        configRepository.save(cfg);
        return ResponseEntity.ok(Map.of("message", "Da cap nhat Cookies Facebook thanh cong!"));
    }

    @PostMapping("/trigger")
    public ResponseEntity<Map<String, String>> triggerManualCheck() {
        Map<String, String> result = messengerService.triggerManualCheck();
        int status = "started".equals(result.get("status")) ? 202 : 200;
        return ResponseEntity.status(status).body(result);
    }

    @GetMapping("/scan-status")
    public ResponseEntity<Map<String, String>> getScanStatus() {
        return ResponseEntity.ok(messengerService.getScanStatus());
    }

    @PostMapping("/launch-browser")
    public ResponseEntity<Map<String, String>> launchBrowser() {
        return ResponseEntity.ok(messengerService.launchInteractiveBrowserSession());
    }

    @PostMapping("/save-browser-session")
    public ResponseEntity<Map<String, String>> saveBrowserSession() {
        return ResponseEntity.ok(messengerService.saveInteractiveBrowserSession());
    }

    @GetMapping("/vnc-ready")
    public ResponseEntity<Map<String, Boolean>> isVncReady() {
        return ResponseEntity.ok(Map.of("ready", messengerService.isVncReady()));
    }

    @PostMapping("/test-send-target")
    public ResponseEntity<Map<String, String>> testSendTarget(@RequestBody Map<String, String> body) {
        String targetUrl  = body.getOrDefault("targetUrl", "https://www.facebook.com/messages/t/100045592363397");
        String targetName = body.getOrDefault("targetName", "Tran Van Manh");
        return ResponseEntity.ok(messengerService.sendTestToThread(targetUrl, targetName));
    }

    @PostMapping("/capture-chat-screenshots")
    public ResponseEntity<Map<String, String>> captureChatScreenshots() {
        return ResponseEntity.ok(messengerService.captureChatScreenshots());
    }

    @PostMapping("/test-ai-chat")
    public ResponseEntity<Map<String, String>> testAiChat(@RequestBody Map<String, String> body) {
        String msg = body.getOrDefault("message", "Trần Văn Mạnh nhắn tôi gì?");
        String reply = aiChatService.chat("test-cli-session", msg);
        return ResponseEntity.ok(Map.of("message", msg, "reply", reply));
    }
}


