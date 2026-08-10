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
        cfg.setCooldownMinutes(Math.max(1, input.getCooldownMinutes()));
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
        String result = messengerService.triggerManualCheck();
        return ResponseEntity.ok(Map.of("result", result));
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
}
