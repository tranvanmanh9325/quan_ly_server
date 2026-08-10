package com.miniserver.metrics.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.Cookie;
import com.miniserver.metrics.model.FacebookConfig;
import com.miniserver.metrics.repository.FacebookConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Server-side Headless Web Automation Service for Facebook Messenger.
 *
 * Uses Playwright Chromium (running inside Docker on the server) to monitor
 * Messenger chats. When Away Mode is enabled (enabled=true) and an incoming sender
 * sends >= threshold (default: 5) unreplied messages, the AI Agent automatically
 * formulates a polite away response using Groq AI and sends it via Messenger.
 */
@Service
public class FacebookMessengerService {

    private static final Logger log = LoggerFactory.getLogger(FacebookMessengerService.class);

    private final FacebookConfigRepository configRepository;
    private final AiChatService aiChatService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // senderKey -> last auto-reply instant (per-sender cooldown)
    private final Map<String, Instant> cooldownMap = new ConcurrentHashMap<>();

    public FacebookMessengerService(FacebookConfigRepository configRepository, AiChatService aiChatService) {
        this.configRepository = configRepository;
        this.aiChatService = aiChatService;
    }

    /** Scheduled check running every 60 seconds */
    @Scheduled(fixedDelay = 60000, initialDelay = 15000)
    public void scheduledCheck() {
        Optional<FacebookConfig> configOpt = configRepository.getConfig();
        if (configOpt.isEmpty()) return;

        FacebookConfig cfg = configOpt.get();
        if (!cfg.isEnabled()) {
            updateStatus(cfg, "Tắt", null);
            return;
        }

        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) {
            updateStatus(cfg, "Cần nhập Cookies Facebook để đăng nhập phiên làm việc", LocalDateTime.now());
            return;
        }

        try {
            int repliesSent = processMessengerChats(cfg);
            String status = "Hoạt động: Đã kiểm tra lúc " + LocalDateTime.now().toLocalTime()
                    + (repliesSent > 0 ? " (Đã phản hồi " + repliesSent + " tin nhắn vắng mặt)" : "");
            updateStatus(cfg, status, LocalDateTime.now());
        } catch (Exception e) {
            log.error("[FB-Responder] Error during Messenger check: {}", e.getMessage(), e);
            updateStatus(cfg, "Lỗi: " + e.getMessage(), LocalDateTime.now());
        }
    }

    /** Manually trigger a check from REST API */
    public String triggerManualCheck() {
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        if (!cfg.isEnabled()) return "Chức năng Vắng mặt hiện đang TẮT. Hãy bật công tắc trước.";
        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) return "Chưa cấu hình Cookies Facebook.";

        try {
            int count = processMessengerChats(cfg);
            return "Đã quét xong! Số tin nhắn vắng mặt đã tự động trả lời: " + count;
        } catch (Exception e) {
            log.error("[FB-Responder] Manual trigger error: {}", e.getMessage(), e);
            return "Lỗi khi quét Messenger: " + e.getMessage();
        }
    }

    private int processMessengerChats(FacebookConfig cfg) {
        int autoRepliesSent = 0;

        BrowserType.LaunchOptions launchOptions = new BrowserType.LaunchOptions()
                .setHeadless(true)
                .setArgs(List.of(
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled"
                ));

        // Use system chromium if available in Linux/Docker container
        if (Paths.get("/usr/bin/chromium").toFile().exists()) {
            launchOptions.setExecutablePath(Paths.get("/usr/bin/chromium"));
        } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
            launchOptions.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
        }

        try (Playwright playwright = Playwright.create();
             Browser browser = playwright.chromium().launch(launchOptions)) {

            BrowserContext context = browser.newContext(new Browser.NewContextOptions()
                    .setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
                    .setViewportSize(1280, 800)
            );

            // Import cookies
            applyCookies(context, cfg.getCookiesJson());

            Page page = context.newPage();
            page.navigate("https://www.facebook.com/messages/t/");
            page.waitForTimeout(4000);

            // Check if logged in
            String currentUrl = page.url();
            if (currentUrl.contains("login") || page.title().contains("Log in") || page.title().contains("Đăng nhập")) {
                log.warn("[FB-Responder] Cookies expired or invalid. Redirected to login page.");
                updateStatus(cfg, "Lỗi: Session Cookies hết hạn hoặc không hợp lệ. Vui lòng cập nhật Cookies mới.", LocalDateTime.now());
                return 0;
            }

            log.info("[FB-Responder] Successfully loaded Messenger page.");

            // Find unread/active conversation elements
            List<ElementHandle> threads = page.querySelectorAll("[role='gridcell'], [role='row'], a[href*='/messages/t/']");
            log.info("[FB-Responder] Found {} potential conversation elements.", threads.size());

            int maxCheck = Math.min(threads.size(), 10);
            for (int i = 0; i < maxCheck; i++) {
                try {
                    ElementHandle thread = threads.get(i);

                    // Layer 1: Check thread sidebar item text for group markers BEFORE clicking
                    String threadItemText = thread.innerText() != null ? thread.innerText().toLowerCase() : "";
                    if (threadItemText.contains("đã thêm") || threadItemText.contains("ảnh nhóm") || threadItemText.contains("đổi tên") || threadItemText.contains("rời khỏi")) {
                        log.info("[FB-Responder] Skipping thread #{} (Sidebar item marked as Group/Community chat)", i);
                        continue;
                    }

                    thread.click();
                    page.waitForTimeout(2500);

                    // Layer 2: Check opened conversation header/sidebar for Group indicators
                    boolean isGroup = isGroupOrCommunityChat(page);
                    if (isGroup) {
                        log.info("[FB-Responder] Thread #{} is a GROUP CHAT / COMMUNITY. Strictly skipping without inspection or auto-reply.", i);
                        continue;
                    }

                    // Extract thread title/sender for 1-on-1 personal chat
                    String senderName = "User_" + i;
                    ElementHandle headerElem = page.querySelector("h2, [role='main'] header span");
                    if (headerElem != null && headerElem.textContent() != null) {
                        senderName = headerElem.textContent().trim();
                    }

                    // Count unreplied consecutive incoming message bubbles from opponent in 1-on-1 chat
                    int unrepliedCount = countUnrepliedIncomingMessages(page);
                    log.info("[FB-Responder] Personal Chat with '{}': {} unreplied incoming message(s).", senderName, unrepliedCount);

                    if (unrepliedCount >= cfg.getThreshold()) {
                        if (isCooldownExpired(senderName, cfg.getCooldownMinutes())) {
                            log.info("[FB-Responder] Triggering AI Away reply for 1-on-1 sender '{}' (Unreplied: {} >= Threshold: {})",
                                    senderName, unrepliedCount, cfg.getThreshold());

                            String awayReply = generateAwayMessage(senderName, unrepliedCount, cfg.getCustomMessage());
                            boolean sent = sendMessengerReply(page, awayReply);

                            if (sent) {
                                autoRepliesSent++;
                                cooldownMap.put(senderName, Instant.now());
                                log.info("[FB-Responder] AUTO-REPLY SENT to '{}': {}", senderName, awayReply);
                            }
                        } else {
                            log.info("[FB-Responder] Sender '{}' is currently on cooldown; skipping.", senderName);
                        }
                    }
                } catch (Exception ex) {
                    log.warn("[FB-Responder] Error processing thread #{}: {}", i, ex.getMessage());
                }
            }
        } catch (Exception e) {
            log.error("[FB-Responder] Playwright execution error: {}", e.getMessage(), e);
            throw new RuntimeException(e);
        }

        return autoRepliesSent;
    }

    private boolean isGroupOrCommunityChat(Page page) {
        Object isGroupResult = page.evaluate("() => {" +
                "  let text = document.body.innerText || '';" +
                "  let header = document.querySelector('[role=\"main\"] header, [role=\"complementary\"]') || document.body;" +
                "  let headerText = (header.innerText || '').toLowerCase();" +
                "  let groupKeywords = ['thành viên', 'view members', 'members', 'thêm người', 'add people', 'đổi tên đoạn chat', 'change chat name', 'rời khỏi nhóm', 'leave group', 'ảnh nhóm', 'cộng đồng', 'community'];" +
                "  for (let kw of groupKeywords) {" +
                "    if (headerText.includes(kw)) return true;" +
                "  }" +
                "  let memberButtons = document.querySelectorAll('[aria-label*=\"Thành viên\"], [aria-label*=\"Members\"], [aria-label*=\"View members\"]');" +
                "  if (memberButtons.length > 0) return true;" +
                "  return false;" +
                "}");

        return Boolean.TRUE.equals(isGroupResult);
    }

    private int countUnrepliedIncomingMessages(Page page) {
        // Evaluate DOM inside the browser to count trailing incoming message bubbles
        Object countResult = page.evaluate("() => {" +
                "  let rows = document.querySelectorAll('[role=\"row\"], [data-scope=\"messages_table\"]');" +
                "  if (!rows || rows.length === 0) {" +
                "    let bubbles = document.querySelectorAll('[dir=\"auto\"]');" +
                "    return Math.min(bubbles.length, 5);" +
                "  }" +
                "  let count = 0;" +
                "  for (let i = rows.length - 1; i >= 0; i--) {" +
                "    let row = rows[i];" +
                "    let text = row.innerText || '';" +
                "    if (!text.trim()) continue;" +
                "    let isOutgoing = row.querySelector('[aria-label*=\"You sent\"], [aria-label*=\"Bạn đã gửi\"]') !== null;" +
                "    if (isOutgoing) break;" +
                "    count++;" +
                "  }" +
                "  return count;" +
                "}");

        if (countResult instanceof Number num) {
            return num.intValue();
        }
        return 0;
    }

    private String generateAwayMessage(String senderName, int unrepliedCount, String customTemplate) {
        if (customTemplate != null && !customTemplate.isBlank()) {
            return customTemplate.replace("{name}", senderName).replace("{count}", String.valueOf(unrepliedCount));
        }

        String prompt = "Bạn là 'Tiểu Bảo Bảo' - trợ lý AI của anh Mạnh (Cua). "
                + "Người dùng cá nhân tên \"" + senderName + "\" đã gửi cho anh Mạnh (Cua) " + unrepliedCount + " tin nhắn liên tiếp trong lúc anh ấy vắng mặt. "
                + "Hãy viết 1 câu trả lời ngắn gọn (1-2 câu), xưng là 'Tiểu Bảo Bảo trợ lí của Mạnh (Cua)', thông báo rằng anh Mạnh (Cua) hiện đang vắng mặt và đã nhận được " + unrepliedCount + " tin nhắn của họ, sẽ báo lại anh ấy ngay khi quay lại.";

        try {
            return aiChatService.chat("fb-away-" + senderName.hashCode(), prompt);
        } catch (Exception e) {
            return "Chào bạn, mình là Tiểu Bảo Bảo trợ lí của Mạnh (Cua). Hiện tại anh Mạnh (Cua) đang đi vắng và đã nhận được " + unrepliedCount + " tin nhắn của bạn. Mình sẽ báo lại anh ấy ngay khi quay lại nhé!";
        }
    }

    private boolean sendMessengerReply(Page page, String text) {
        try {
            // Locators for Messenger input box
            ElementHandle inputBox = page.querySelector("[role='textbox'], [contenteditable='true'], [aria-label*='Message'], [aria-label*='Tin nhắn']");
            if (inputBox == null) {
                log.warn("[FB-Responder] Could not find Messenger message textbox element.");
                return false;
            }

            inputBox.focus();
            inputBox.fill(text);
            page.waitForTimeout(500);

            // Press Enter to send
            page.keyboard().press("Enter");
            page.waitForTimeout(1000);
            return true;
        } catch (Exception e) {
            log.error("[FB-Responder] Failed to send Messenger reply: {}", e.getMessage());
            return false;
        }
    }

    private void applyCookies(BrowserContext context, String cookiesJson) {
        try {
            JsonNode arrayNode = objectMapper.readTree(cookiesJson);
            if (!arrayNode.isArray()) return;

            List<Cookie> cookies = new ArrayList<>();
            for (JsonNode node : arrayNode) {
                String name = node.path("name").asText("");
                String value = node.path("value").asText("");
                String domain = node.path("domain").asText(".facebook.com");
                String path = node.path("path").asText("/");

                if (!name.isBlank() && !value.isBlank()) {
                    Cookie c = new Cookie(name, value);
                    c.setDomain(domain);
                    c.setPath(path);
                    cookies.add(c);
                }
            }
            if (!cookies.isEmpty()) {
                context.addCookies(cookies);
                log.info("[FB-Responder] Successfully imported {} cookies into browser context.", cookies.size());
            }
        } catch (Exception e) {
            log.warn("[FB-Responder] Failed to parse/apply cookies JSON: {}", e.getMessage());
        }
    }

    private boolean isCooldownExpired(String senderName, int cooldownMinutes) {
        Instant lastTime = cooldownMap.get(senderName);
        if (lastTime == null) return true;
        return Instant.now().isAfter(lastTime.plusSeconds((long) cooldownMinutes * 60));
    }

    private void updateStatus(FacebookConfig cfg, String status, LocalDateTime checkAt) {
        cfg.setLastStatus(status);
        if (checkAt != null) cfg.setLastCheckAt(checkAt);
        configRepository.save(cfg);
    }
}
