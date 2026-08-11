package com.miniserver.metrics.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.Cookie;
import com.microsoft.playwright.options.WaitUntilState;
import com.miniserver.metrics.model.FacebookConfig;
import com.miniserver.metrics.repository.FacebookConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
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
 * Messenger chats. Maintains a single long-running persistent browser context
 * to prevent spamming Facebook login history and avoid account security checkpoints.
 */
@Service
public class FacebookMessengerService implements DisposableBean {

    private static final Logger log = LoggerFactory.getLogger(FacebookMessengerService.class);

    private final FacebookConfigRepository configRepository;
    private final AiChatService aiChatService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // senderKey -> last auto-reply instant (per-sender cooldown)
    private final Map<String, Instant> cooldownMap = new ConcurrentHashMap<>();

    // Long-running persistent browser context & page to prevent Facebook login spam
    private Playwright activePlaywright;
    private BrowserContext activeContext;
    private Page activePage;
    private String lastLoadedCookiesJson;

    public FacebookMessengerService(FacebookConfigRepository configRepository, AiChatService aiChatService) {
        this.configRepository = configRepository;
        this.aiChatService = aiChatService;
    }

    @Override
    public void destroy() {
        closeActiveSession();
    }

    private synchronized void closeActiveSession() {
        try {
            if (activePage != null && !activePage.isClosed()) {
                activePage.close();
            }
        } catch (Exception ignored) {}
        activePage = null;

        try {
            if (activeContext != null) {
                activeContext.close();
            }
        } catch (Exception ignored) {}
        activeContext = null;

        try {
            if (activePlaywright != null) {
                activePlaywright.close();
            }
        } catch (Exception ignored) {}
        activePlaywright = null;
    }

    private synchronized Page getOrInitActivePage(FacebookConfig cfg) throws Exception {
        String currentCookiesJson = cfg.getCookiesJson();
        boolean cookiesChanged = currentCookiesJson != null && !currentCookiesJson.equals(lastLoadedCookiesJson);

        if (activePage != null && !activePage.isClosed() && !cookiesChanged) {
            try {
                String currentUrl = activePage.url();
                if (currentUrl != null && !currentUrl.contains("login")) {
                    log.debug("[FB-Responder] Reusing active persistent Messenger session without reload. URL: {}", currentUrl);
                    return activePage;
                }
            } catch (Exception e) {
                log.warn("[FB-Responder] Active Messenger tab unresponsive, re-initializing persistent session...");
            }
        }

        closeActiveSession();

        Map<String, String> env = new HashMap<>(System.getenv());
        env.put("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1");
        env.put("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium");
        env.put("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node");
        Playwright.CreateOptions createOptions = new Playwright.CreateOptions().setEnv(env);

        activePlaywright = Playwright.create(createOptions);

        List<String> args = List.of(
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--mute-audio",
                "--disable-speech-api",
                "--disable-background-networking",
                "--disable-component-extensions-with-background-pages",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process"
        );

        BrowserType.LaunchPersistentContextOptions pOptions = new BrowserType.LaunchPersistentContextOptions()
                .setHeadless(true)
                .setArgs(args)
                .setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
                .setViewportSize(1280, 800);

        if (Paths.get("/usr/bin/chromium").toFile().exists()) {
            pOptions.setExecutablePath(Paths.get("/usr/bin/chromium"));
        } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
            pOptions.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
        }

        java.nio.file.Path profileDir = Paths.get("/tmp/fb_bot_profile");
        activeContext = activePlaywright.chromium().launchPersistentContext(profileDir, pOptions);

        // Block heavy resources (images, media, fonts) to minimize CPU & RAM consumption
        activeContext.route("**/*", route -> {
            String resourceType = route.request().resourceType();
            if ("image".equals(resourceType) || "media".equals(resourceType) || "font".equals(resourceType)) {
                route.abort();
            } else {
                route.fallback();
            }
        });

        applyCookies(activeContext, currentCookiesJson);
        lastLoadedCookiesJson = currentCookiesJson;

        activePage = activeContext.newPage();
        activePage.navigate("https://www.facebook.com/messages/t/", new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED));
        activePage.waitForTimeout(4000);

        return activePage;
    }

    /** Scheduled check running every 60 seconds */
    @Scheduled(fixedDelay = 60000, initialDelay = 15000)
    public void scheduledCheck() {
        Optional<FacebookConfig> configOpt = configRepository.getConfig();
        if (configOpt.isEmpty()) return;

        FacebookConfig cfg = configOpt.get();
        if (!cfg.isEnabled()) {
            closeActiveSession();
            updateStatus(cfg, "Tắt", null);
            return;
        }

        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) {
            closeActiveSession();
            updateStatus(cfg, "Cần nhập Cookies Facebook để đăng nhập phiên làm việc", LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
            return;
        }

        try {
            int repliesSent = processMessengerChats(cfg);
            LocalDateTime vnNow = LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh"));
            java.time.format.DateTimeFormatter fmt = java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss dd/MM/yyyy");
            String status = "Hoạt động: Đã kiểm tra lúc " + vnNow.format(fmt)
                    + (repliesSent > 0 ? " (Đã phản hồi " + repliesSent + " tin nhắn vắng mặt)" : "");
            updateStatus(cfg, status, vnNow);
        } catch (Exception e) {
            log.error("[FB-Responder] Error during Messenger check: {}", e.getMessage(), e);
            updateStatus(cfg, "Lỗi: " + e.getMessage(), LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
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

        try {
            Page page = getOrInitActivePage(cfg);

            // Close any popup/modal if present (e.g. E2E encryption / PIN popup / Not Now)
            try {
                List<ElementHandle> closeBtns = page.querySelectorAll("div[role='dialog'] div[role='button']:has-text('Not now'), div[role='dialog'] div[role='button']:has-text('Không phải bây giờ'), div[role='dialog'] div[aria-label='Close'], div[role='dialog'] div[aria-label='Đóng']");
                for (ElementHandle btn : closeBtns) {
                    if (btn.isVisible()) {
                        btn.click();
                        page.waitForTimeout(1000);
                    }
                }
            } catch (Exception ignored) {}

            // Check if logged in
            String currentUrl = page.url();
            if (currentUrl.contains("login") || page.title().contains("Log in") || page.title().contains("Đăng nhập")) {
                log.warn("[FB-Responder] Cookies expired or invalid. Redirected to login page.");
                updateStatus(cfg, "Lỗi: Session Cookies hết hạn hoặc không hợp lệ. Vui lòng cập nhật Cookies mới.", LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
                closeActiveSession();
                return 0;
            }

            log.info("[FB-Responder] Successfully inspecting persistent Messenger session. Current URL: {}", currentUrl);

            // Wait for conversation list
            try {
                page.waitForSelector("[role='gridcell'], [role='row'], a[href*='/messages/t/'], div[role='navigation'] a", new Page.WaitForSelectorOptions().setTimeout(8000));
            } catch (Exception e) {
                log.warn("[FB-Responder] Wait for thread list selector timed out, attempting query fallback...");
            }

            // Find unread/active conversation elements
            List<ElementHandle> threads = page.querySelectorAll("[role='gridcell'], [role='row'], a[href*='/messages/t/'], div[role='navigation'] a, div[role='listitem']");
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
            closeActiveSession();
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

    /** Launches Xvfb, openbox WM, x11vnc, websockify (noVNC), and Chromium on :99 for live web login */
    public Map<String, String> launchInteractiveBrowserSession() {
        try {
            cleanupProcesses();

            // 1. Start Xvfb virtual framebuffer on :99 with RANDR extension enabled
            new ProcessBuilder("Xvfb", ":99", "-screen", "0", "1280x800x24", "-ac", "+extension", "RANDR").start();
            Thread.sleep(600);

            // 2. Start Openbox lightweight window manager for smooth window focus & menu rendering
            ProcessBuilder pbWm = new ProcessBuilder("openbox");
            pbWm.environment().put("DISPLAY", ":99");
            pbWm.start();
            Thread.sleep(400);

            // 3. Start x11vnc server on port 5900 with frame deferral & region caching flags
            new ProcessBuilder("x11vnc", "-display", ":99", "-forever", "-shared", "-nopw", "-rfbport", "5900", "-wait", "10", "-defer", "10", "-ncache", "10").start();
            Thread.sleep(600);

            // 4. Start websockify (noVNC) on port 6080
            new ProcessBuilder("websockify", "--web=/usr/share/novnc", "6080", "localhost:5900").start();
            Thread.sleep(600);

            // 5. Start Chromium on :99 with performance & process throttling flags
            ProcessBuilder pb = new ProcessBuilder(
                    "/usr/lib/chromium/chromium",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--window-size=1280,800",
                    "--force-device-scale-factor=1",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-renderer-backgrounding",
                    "--user-data-dir=/tmp/fb_interactive_profile",
                    "--remote-debugging-port=9222",
                    "https://www.facebook.com/login"
            );
            pb.environment().put("DISPLAY", ":99");
            pb.start();

            log.info("[FB-Responder] Launched high-performance noVNC Chromium login session on display :99");
            String vncOptUrl = "/fb-vnc/vnc.html?autoconnect=true&resize=scale&quality=6&compression=6&reconnect=true&reconnect_delay=1000";
            return Map.of("status", "success", "vncUrl", vncOptUrl, "message", "Trình duyệt Facebook đã được mở mượt mà trên Server.");
        } catch (Exception e) {
            log.error("[FB-Responder] Failed to launch interactive browser session: {}", e.getMessage(), e);
            return Map.of("status", "error", "message", "Lỗi khi mở trình duyệt Server: " + e.getMessage());
        }
    }

    /** Connects to live Chromium via CDP, extracts session cookies into PostgreSQL DB, and cleanup */
    public Map<String, String> saveInteractiveBrowserSession() {
        try {
            List<Map<String, Object>> cookieList = new ArrayList<>();
            Map<String, String> env = new HashMap<>();
            env.put("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node");
            env.put("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium");
            env.put("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1");

            try (Playwright playwright = Playwright.create(new Playwright.CreateOptions().setEnv(env))) {
                Browser browser = playwright.chromium().connectOverCDP("http://localhost:9222");
                List<BrowserContext> contexts = browser.contexts();
                if (!contexts.isEmpty()) {
                    BrowserContext ctx = contexts.get(0);
                    List<Cookie> rawCookies = ctx.cookies();
                    for (Cookie c : rawCookies) {
                        Map<String, Object> map = new LinkedHashMap<>();
                        map.put("domain", c.domain);
                        map.put("name", c.name);
                        map.put("value", c.value);
                        map.put("path", c.path);
                        map.put("secure", c.secure);
                        map.put("httpOnly", c.httpOnly);
                        map.put("sameSite", c.sameSite != null ? c.sameSite.toString() : "no_restriction");
                        if (c.expires != null && c.expires > 0) {
                            map.put("expirationDate", c.expires);
                        }
                        cookieList.add(map);
                    }
                }
            }

            if (cookieList.isEmpty()) {
                return Map.of("status", "error", "message", "Không tìm thấy Cookies trên trình duyệt. Vui lòng hoàn tất đăng nhập Facebook trước khi lưu.");
            }

            String cookiesJson = objectMapper.writeValueAsString(cookieList);
            FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
            cfg.setCookiesJson(cookiesJson);
            cfg.setEnabled(true);
            LocalDateTime vnNow = LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh"));
            java.time.format.DateTimeFormatter fmt = java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss dd/MM/yyyy");
            cfg.setLastStatus("Hoạt động: Đã cập nhật Session mới từ Trình duyệt Server lúc " + vnNow.format(fmt));
            cfg.setLastCheckAt(vnNow);
            configRepository.save(cfg);

            cleanupProcesses();
            log.info("[FB-Responder] Successfully captured {} cookies from interactive browser session into DB.", cookieList.size());
            return Map.of("status", "success", "message", "Đã lưu thành công " + cookieList.size() + " Cookies Facebook & kích hoạt AI Agent 24/7!");
        } catch (Exception e) {
            log.error("[FB-Responder] Failed to save interactive browser session: {}", e.getMessage(), e);
            return Map.of("status", "error", "message", "Lỗi khi lưu phiên làm việc: " + e.getMessage());
        }
    }

    private void cleanupProcesses() {
        closeActiveSession();
        try {
            new ProcessBuilder("pkill", "-f", "chromium").start();
            new ProcessBuilder("pkill", "-f", "openbox").start();
            new ProcessBuilder("pkill", "-f", "websockify").start();
            new ProcessBuilder("pkill", "-f", "x11vnc").start();
            new ProcessBuilder("pkill", "-f", "Xvfb").start();
            Thread.sleep(500);
        } catch (Exception ignored) {}
    }
}
