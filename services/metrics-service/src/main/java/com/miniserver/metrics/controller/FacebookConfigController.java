package com.miniserver.metrics.controller;

import com.miniserver.metrics.model.FacebookConfig;
import com.miniserver.metrics.repository.FacebookConfigRepository;
import com.miniserver.metrics.service.FacebookMessengerService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/facebook")
public class FacebookConfigController {

    private final FacebookConfigRepository configRepository;
    private final FacebookMessengerService messengerService;

    public FacebookConfigController(FacebookConfigRepository configRepository, FacebookMessengerService messengerService) {
        this.configRepository = configRepository;
        this.messengerService = messengerService;
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
        return ResponseEntity.ok(Map.of("message", "Đã cập nhật Cookies Facebook thành công!"));
    }

    @PostMapping("/trigger")
    public ResponseEntity<Map<String, String>> triggerManualCheck() {
        Map<String, String> result = messengerService.triggerManualCheck();
        // Return 202 Accepted for async start; 200 OK for immediate skip/busy responses
        int status = "started".equals(result.get("status")) ? 202 : 200;
        return ResponseEntity.status(status).body(result);
    }

    @GetMapping("/scan-status")
    public ResponseEntity<Map<String, String>> getScanStatus() {
        return ResponseEntity.ok(messengerService.getScanStatus());
    }

    @PostMapping("/launch-browser")
    public ResponseEntity<Map<String, String>> launchBrowser() {
        Map<String, String> res = messengerService.launchInteractiveBrowserSession();
        return ResponseEntity.ok(res);
    }

    @PostMapping("/save-browser-session")
    public ResponseEntity<Map<String, String>> saveBrowserSession() {
        Map<String, String> res = messengerService.saveInteractiveBrowserSession();
        return ResponseEntity.ok(res);
    }

    /**
     * Lightweight readiness probe — returns {"ready": true/false}.
     * Frontend polls this after launch-browser succeeds to know when the VNC stack
     * (websockify on :6080) is actually accepting connections before rendering the iframe.
     */
    @GetMapping("/vnc-ready")
    public ResponseEntity<Map<String, Boolean>> isVncReady() {
        return ResponseEntity.ok(Map.of("ready", messengerService.isVncReady()));
    }

    @PostMapping("/test-send-target")
    public ResponseEntity<Map<String, String>> testSendTarget(@RequestBody Map<String, String> body) {
        String targetUrl = body.getOrDefault("targetUrl", "https://www.facebook.com/messages/t/100045592363397");
        String targetName = body.getOrDefault("targetName", "Trần Văn Mạnh");
        Map<String, String> res = messengerService.sendTestToThread(targetUrl, targetName);
        return ResponseEntity.ok(res);
    }

    @PostMapping("/capture-chat-screenshots")
    public ResponseEntity<Map<String, String>> captureChatScreenshots() {
        return ResponseEntity.ok(messengerService.captureChatScreenshots());
    }
}

