package com.miniserver.metrics.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.Cookie;
import com.microsoft.playwright.options.SameSiteAttribute;
import com.microsoft.playwright.options.WaitUntilState;
import com.miniserver.metrics.model.FacebookConfig;
import com.miniserver.metrics.repository.FacebookConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.net.Socket;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Server-side Headless Web Automation Service for Facebook Messenger.
 *
 * Uses Playwright Chromium (running inside Docker on the server) to monitor
 * Messenger chats. Each scheduled check spawns an ephemeral browser, does work,
 * then closes it immediately. This keeps CPU at 0% between checks because the
 * Chromium Renderer process (the main CPU consumer due to Facebook's JS engine)
 * only lives for the ~5-10 seconds needed to inspect the inbox.
 *
 * Login history spam is avoided because cookie-based auth re-uses the same
 * Facebook session tokens on every launch — Facebook sees the same session,
 * not a new login event.
 */
@Service
public class FacebookMessengerService implements DisposableBean {

    private static final Logger log = LoggerFactory.getLogger(FacebookMessengerService.class);

    private static final String PROFILE_DIR_PATH;

    static {
        String envDir = System.getenv("FB_PROFILE_DIR");
        if (envDir != null && !envDir.isBlank()) {
            PROFILE_DIR_PATH = envDir;
        } else if (Paths.get("/var/lib/fb_browser_profile").toFile().exists() || Paths.get("/var/lib").toFile().canWrite()) {
            PROFILE_DIR_PATH = "/var/lib/fb_browser_profile";
        } else {
            PROFILE_DIR_PATH = "/tmp/fb_persistent_profile";
        }
    }

    private static void preparePersistentProfileDir() {
        try {
            java.io.File dir = new java.io.File(PROFILE_DIR_PATH);
            if (!dir.exists()) {
                boolean created = dir.mkdirs();
                log.info("[FB-Responder] Created persistent profile directory at {}: {}", PROFILE_DIR_PATH, created);
            }
            // Remove ONLY stale lock files if previous process crashed. DO NOT wipe IndexedDB / LocalStorage / E2EE keys!
            new java.io.File(dir, "SingletonLock").delete();
            new java.io.File(dir, "SingletonSocket").delete();
            new java.io.File(dir, "SingletonCookie").delete();
        } catch (Exception e) {
            log.warn("[FB-Responder] Error preparing persistent profile directory: {}", e.getMessage());
        }
    }

    private static boolean isPortOpen(String host, int port) {
        try (Socket s = new Socket(host, port)) {
            return s.isConnected();
        } catch (Exception e) {
            return false;
        }
    }

    // Lean Chromium args for headless automation — disables all non-essential features
    private static final List<String> CHROMIUM_ARGS = List.of(
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--mute-audio",
            "--disable-speech-api",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-component-extensions-with-background-pages",
            "--disable-ipc-flooding-protection",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--process-per-site",
            "--renderer-process-limit=1"
    );

    private final FacebookConfigRepository configRepository;
    private final AiChatService aiChatService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // senderKey -> last auto-reply instant (per-sender cooldown)
    private final Map<String, Instant> cooldownMap = new ConcurrentHashMap<>();

    // VNC-only singleton state (used only for interactive login session, NOT for scheduled checks)
    private Playwright activePlaywright;
    private BrowserContext activeContext;
    private Page activePage;

    // Async manual scan state — single-thread executor prevents concurrent scans
    private final ExecutorService scanExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "fb-manual-scan");
        t.setDaemon(true);
        return t;
    });
    private final AtomicBoolean scanRunning = new AtomicBoolean(false);
    private volatile String lastScanResult = null;

    public FacebookMessengerService(FacebookConfigRepository configRepository, AiChatService aiChatService) {
        this.configRepository = configRepository;
        this.aiChatService = aiChatService;
    }

    @Override
    public void destroy() {
        closeActiveSession();
        scanExecutor.shutdownNow();
        try { scanExecutor.awaitTermination(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
    }

    // ========================================================================================
    // SCHEDULED CHECK — Ephemeral browser per cycle (CPU = 0% between checks)
    // ========================================================================================

    /** Scheduled check running every 5 minutes (300s) */
    @Scheduled(fixedDelay = 300000, initialDelay = 15000)
    public void scheduledCheck() {
        Optional<FacebookConfig> configOpt = configRepository.getConfig();
        if (configOpt.isEmpty()) return;

        FacebookConfig cfg = configOpt.get();
        if (!cfg.isEnabled()) {
            updateStatus(cfg, "Tắt", null);
            return;
        }

        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) {
            updateStatus(cfg, "Cần nhập Cookies Facebook để đăng nhập phiên làm việc",
                    LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
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

    /** Manually trigger a check from REST API — runs async to avoid HTTP timeout */
    public Map<String, String> triggerManualCheck() {
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        if (!cfg.isEnabled())
            return Map.of("status", "skipped", "message", "Chức năng Vắng mặt hiện đang TẮT. Hãy bật công tắc trước.");
        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank())
            return Map.of("status", "skipped", "message", "Chưa cấu hình Cookies Facebook.");

        if (scanRunning.get())
            return Map.of("status", "running", "message", "Đang quét... Vui lòng đợi.");

        scanRunning.set(true);
        lastScanResult = null;
        scanExecutor.submit(() -> {
            try {
                int count = processMessengerChats(cfg);
                lastScanResult = "Đã quét xong! Số tin nhắn vắng mặt đã tự động trả lời: " + count;
            } catch (Exception e) {
                log.error("[FB-Responder] Manual trigger error: {}", e.getMessage(), e);
                lastScanResult = "Lỗi khi quét Messenger: " + e.getMessage();
            } finally {
                scanRunning.set(false);
            }
        });
        return Map.of("status", "started", "message", "Đã bắt đầu quét Messenger...");
    }

    /** Poll endpoint — returns current scan status */
    public Map<String, String> getScanStatus() {
        if (scanRunning.get())
            return Map.of("status", "running", "message", "Đang quét...");
        if (lastScanResult != null)
            return Map.of("status", "done", "message", lastScanResult);
        return Map.of("status", "idle", "message", "");
    }

    /**
     * Core check logic: starts an ephemeral Playwright browser, injects cookies,
     * inspects Messenger inbox, sends auto-replies, then closes browser immediately.
     * The browser lives only for the duration of this method (~5-15 seconds).
     */
    private int processMessengerChats(FacebookConfig cfg) {
        Map<String, String> env = new HashMap<>(System.getenv());
        env.put("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1");
        env.put("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium");
        env.put("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node");

        try (Playwright playwright = Playwright.create(new Playwright.CreateOptions().setEnv(env))) {

            // Case 1: Active VNC browser is running on CDP port 9222 -> connect to live Chromium
            if (isPortOpen("localhost", 9222)) {
                log.info("[FB-Responder] Active VNC browser session detected on CDP port 9222. Inspecting live browser context.");
                try {
                    Browser browser = playwright.chromium().connectOverCDP("http://localhost:9222");
                    if (!browser.contexts().isEmpty()) {
                        BrowserContext ctx = browser.contexts().get(0);
                        Page page = ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0);
                        return inspectAndReply(page, cfg);
                    }
                } catch (Exception e) {
                    log.warn("[FB-Responder] Failed to connect to CDP session on port 9222: {}", e.getMessage());
                }
            }

            // Case 2: Standalone check using persistent browser context (preserves IndexedDB / E2EE PIN keys)
            preparePersistentProfileDir();

            BrowserType.LaunchPersistentContextOptions pOptions = new BrowserType.LaunchPersistentContextOptions()
                    .setHeadless(true)
                    .setArgs(CHROMIUM_ARGS)
                    .setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
                    .setViewportSize(1280, 800);

            if (Paths.get("/usr/bin/chromium").toFile().exists()) {
                pOptions.setExecutablePath(Paths.get("/usr/bin/chromium"));
            } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
                pOptions.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
            }

            try (BrowserContext context = playwright.chromium().launchPersistentContext(Paths.get(PROFILE_DIR_PATH), pOptions)) {
                // Block heavy resources — images/media/fonts/stylesheets have no value for DOM automation
                context.route("**/*", route -> {
                    String rt = route.request().resourceType();
                    if ("image".equals(rt) || "media".equals(rt) || "font".equals(rt) || "stylesheet".equals(rt)) {
                        route.abort();
                    } else {
                        route.fallback();
                    }
                });

                if (cfg.getCookiesJson() != null && !cfg.getCookiesJson().isBlank()) {
                    applyCookies(context, cfg.getCookiesJson());
                }

                Page page = context.pages().isEmpty() ? context.newPage() : context.pages().get(0);

                page.navigate("https://www.facebook.com/messages/t/",
                        new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED));
                page.waitForTimeout(4000);

                String currentUrl = page.url();
                if (currentUrl.contains("login") || page.title().contains("Log in") || page.title().contains("Đăng nhập")) {
                    log.warn("[FB-Responder] Cookies expired or invalid. Redirected to login page.");
                    updateStatus(cfg, "Lỗi: Session Cookies hết hạn hoặc không hợp lệ. Vui lòng cập nhật Cookies mới.",
                            LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
                    return 0;
                }

                log.info("[FB-Responder] Persistent browser ready. Current URL: {}", currentUrl);

                // Dismiss popups if any
                try {
                    List<ElementHandle> closeBtns = page.querySelectorAll(
                            "div[role='dialog'] div[role='button']:has-text('Not now'), " +
                            "div[role='dialog'] div[role='button']:has-text('Không phải bây giờ'), " +
                            "div[role='dialog'] div[aria-label='Close'], " +
                            "div[role='dialog'] div[aria-label='Đóng']");
                    for (ElementHandle btn : closeBtns) {
                        if (btn.isVisible()) {
                            btn.click();
                            page.waitForTimeout(500);
                        }
                    }
                } catch (Exception ignored) {}

                // Wait for conversation list to render
                try {
                    page.waitForSelector("[role='gridcell'], [role='row'], a[href*='/messages/t/'], div[role='navigation'] a",
                            new Page.WaitForSelectorOptions().setTimeout(8000));
                } catch (Exception e) {
                    log.warn("[FB-Responder] Wait for thread list selector timed out, attempting query fallback...");
                }

                return inspectAndReply(page, cfg);
            }
        }
    }

    private int inspectAndReply(Page page, FacebookConfig cfg) {
        int autoRepliesSent = 0;

        List<ElementHandle> threads = page.querySelectorAll(
                "[role='gridcell'], [role='row'], a[href*='/messages/t/'], div[role='navigation'] a, div[role='listitem']");
        log.info("[FB-Responder] Found {} potential conversation elements.", threads.size());

        int maxCheck = Math.min(threads.size(), 10);
        for (int i = 0; i < maxCheck; i++) {
            try {
                ElementHandle thread = threads.get(i);

                String threadItemText = thread.innerText() != null ? thread.innerText().toLowerCase() : "";
                if (threadItemText.contains("đã thêm") || threadItemText.contains("ảnh nhóm")
                        || threadItemText.contains("đổi tên") || threadItemText.contains("rời khỏi")) {
                    log.info("[FB-Responder] Skipping thread #{} (Group/Community sidebar marker)", i);
                    continue;
                }

                thread.click();
                page.waitForTimeout(2000);

                boolean isGroup = isGroupOrCommunityChat(page);
                if (isGroup) {
                    log.info("[FB-Responder] Thread #{} is a GROUP CHAT / COMMUNITY. Skipping.", i);
                    continue;
                }

                String senderName = "User_" + i;
                ElementHandle headerElem = page.querySelector("h2, [role='main'] header span");
                if (headerElem != null && headerElem.textContent() != null) {
                    senderName = headerElem.textContent().trim();
                }

                int unrepliedCount = countUnrepliedIncomingMessages(page);
                log.info("[FB-Responder] Personal Chat with '{}': {} unreplied incoming message(s).", senderName, unrepliedCount);

                if (unrepliedCount >= cfg.getThreshold()) {
                    if (isCooldownExpired(senderName, cfg.getCooldownMinutes())) {
                        log.info("[FB-Responder] Triggering AI Away reply for '{}' (Unreplied: {} >= Threshold: {})",
                                senderName, unrepliedCount, cfg.getThreshold());
                        String awayReply = generateAwayMessage(senderName, unrepliedCount, cfg.getCustomMessage());
                        boolean sent = sendMessengerReply(page, awayReply);
                        if (sent) {
                            autoRepliesSent++;
                            cooldownMap.put(senderName, Instant.now());
                            log.info("[FB-Responder] AUTO-REPLY SENT to '{}': {}", senderName, awayReply);
                        }
                    } else {
                        log.info("[FB-Responder] Sender '{}' is on cooldown; skipping.", senderName);
                    }
                }
            } catch (Exception ex) {
                log.warn("[FB-Responder] Error processing thread #{}: {}", i, ex.getMessage());
            }
        }

        return autoRepliesSent;
    }

    // ========================================================================================
    // HELPER METHODS
    // ========================================================================================

    private boolean isGroupOrCommunityChat(Page page) {
        Object isGroupResult = page.evaluate("() => {" +
                "  let header = document.querySelector('[role=\"main\"] header, [role=\"complementary\"]') || document.body;" +
                "  let headerText = (header.innerText || '').toLowerCase();" +
                "  let groupKeywords = ['thành viên', 'view members', 'members', 'thêm người', 'add people', 'đổi tên đoạn chat', 'change chat name', 'rời khỏi nhóm', 'leave group', 'ảnh nhóm', 'cộng đồng', 'community'];" +
                "  for (let kw of groupKeywords) { if (headerText.includes(kw)) return true; }" +
                "  let memberButtons = document.querySelectorAll('[aria-label*=\"Thành viên\"], [aria-label*=\"Members\"], [aria-label*=\"View members\"]');" +
                "  return memberButtons.length > 0;" +
                "}");
        return Boolean.TRUE.equals(isGroupResult);
    }

    private int countUnrepliedIncomingMessages(Page page) {
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
        if (countResult instanceof Number num) return num.intValue();
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
            ElementHandle inputBox = page.querySelector("[role='textbox'], [contenteditable='true'], [aria-label*='Message'], [aria-label*='Tin nhắn']");
            if (inputBox == null) {
                log.warn("[FB-Responder] Could not find Messenger message textbox element.");
                return false;
            }
            inputBox.focus();
            inputBox.fill(text);
            page.waitForTimeout(500);
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
                log.info("[FB-Responder] Successfully imported {} cookies into ephemeral browser context.", cookies.size());
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

    // ========================================================================================
    // VNC INTERACTIVE LOGIN SESSION (for manual Facebook login via browser)
    // ========================================================================================

    private synchronized void closeActiveSession() {
        try {
            if (activePage != null && !activePage.isClosed()) activePage.close();
        } catch (Exception ignored) {}
        activePage = null;

        try {
            if (activeContext != null) activeContext.close();
        } catch (Exception ignored) {}
        activeContext = null;

        try {
            if (activePlaywright != null) activePlaywright.close();
        } catch (Exception ignored) {}
        activePlaywright = null;
    }

    /**
     * Launches Xvfb, openbox WM, x11vnc, websockify (noVNC), and Chromium on :99 for live web login.
     *
     * If Facebook session cookies are already saved in the DB, they are injected into Chromium via
     * Playwright CDP so the user lands on facebook.com already logged in.
     *
     * IMPORTANT: Cookie injection runs in a daemon thread AFTER this method returns the VNC URL,
     * so the HTTP response (and VNC connection) is never blocked by the CDP/Playwright overhead.
     */
    public Map<String, String> launchInteractiveBrowserSession() {
        try {
            cleanupProcesses();

            // Extract cookies JSON from DB — null means no saved session exists
            String savedCookiesJson = configRepository.getConfig()
                    .map(cfg -> cfg.getCookiesJson())
                    .filter(c -> c != null && !c.isBlank())
                    .orElse(null);
            boolean hasSavedSession = savedCookiesJson != null;

            // Prepare persistent profile directory (preserve IndexedDB, LocalStorage & E2EE PIN keys)
            preparePersistentProfileDir();

            // 1. Start Xvfb virtual framebuffer on :99 (Full HD 1920x1080)
            new ProcessBuilder("Xvfb", ":99", "-screen", "0", "1920x1080x24", "-ac", "+extension", "RANDR").start();
            Thread.sleep(800);

            // 2. Start Openbox lightweight window manager
            ProcessBuilder pbWm = new ProcessBuilder("openbox");
            pbWm.environment().put("DISPLAY", ":99");
            pbWm.start();
            Thread.sleep(600);

            // 3. Start x11vnc — '-cursor most' / '-xkb' for accurate mouse & keyboard events
            new ProcessBuilder("x11vnc", "-display", ":99", "-forever", "-shared", "-nopw", "-rfbport", "5900",
                    "-cursor", "most", "-xkb", "-wait", "10", "-defer", "10").start();
            Thread.sleep(600);

            // 4. Start websockify (noVNC bridge) on port 6080 — MUST be running before returning VNC URL
            new ProcessBuilder("websockify", "--web=/usr/share/novnc", "6080", "localhost:5900").start();
            // Block until websockify is genuinely accepting TCP connections (up to 15s).
            // This replaces a fixed Thread.sleep() that was too short on loaded systems.
            waitForPort(6080, 15);

            // 5. Start Chromium with remote debugging enabled.
            //    Open about:blank when a saved session exists — cookies will be injected via CDP asynchronously.
            //    Open the login page directly when no session is saved.
            String initialUrl = hasSavedSession ? "about:blank" : "https://www.facebook.com/login";
            ProcessBuilder pb = new ProcessBuilder(
                    "/usr/lib/chromium/chromium",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--window-position=0,0",
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--force-device-scale-factor=1",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-renderer-backgrounding",
                    "--user-data-dir=" + PROFILE_DIR_PATH,
                    "--remote-debugging-port=9222",
                    initialUrl
            );
            pb.environment().put("DISPLAY", ":99");
            pb.start();

            // 6. Offload all post-startup work to a daemon thread.
            //    This is critical: returning the VNC URL immediately lets the frontend connect
            //    BEFORE Playwright's CDP session touches Chromium. Playwright's CDP navigate() call
            //    is heavy and was previously blocking x11vnc frame capture, causing VNC to hang.
            final String cookiesJsonSnapshot = savedCookiesJson;
            Thread asyncSetup = new Thread(() -> {
                try {
                    // Wait for Chromium to fully start and bind the CDP remote debugging port
                    Thread.sleep(3000);

                    // Resize Chromium window to fill the entire virtual display
                    new ProcessBuilder("sh", "-c",
                            "DISPLAY=:99 xdotool search --sync --class chromium windowmove 0 0 windowsize 1920 1080 2>/dev/null || true"
                    ).start().waitFor(5, java.util.concurrent.TimeUnit.SECONDS);

                    // Inject saved cookies and navigate to Facebook
                    if (cookiesJsonSnapshot != null) {
                        restoreSessionCookies(cookiesJsonSnapshot);
                    }
                } catch (Exception e) {
                    log.warn("[FB-Responder] Async setup error: {}", e.getMessage());
                }
            });
            asyncSetup.setDaemon(true);
            asyncSetup.setName("fb-session-restore");
            asyncSetup.start();

            String message = hasSavedSession
                    ? "Đang khôi phục phiên Facebook từ Session đã lưu..."
                    : "Trình duyệt Facebook đã được mở trên Server."
                    ;
            log.info("[FB-Responder] Launched noVNC Chromium on :99 (hasSavedSession={})", hasSavedSession);
            String vncUrl = "/fb-vnc/vnc.html?autoconnect=true&resize=scale&quality=6&compression=6&reconnect=true&reconnect_delay=1000";
            return Map.of("status", "success", "vncUrl", vncUrl, "message", message);
        } catch (Exception e) {
            log.error("[FB-Responder] Failed to launch interactive browser session: {}", e.getMessage(), e);
            return Map.of("status", "error", "message", "Lỗi khi mở trình duyệt Server: " + e.getMessage());
        }
    }

    /**
     * Injects previously saved Facebook session cookies into the running Chromium via CDP,
     * then triggers navigation to facebook.com via JavaScript (fire-and-forget — does NOT wait
     * for page load, so Playwright closes cleanly without blocking Chromium's rendering thread).
     *
     * Called only from the async daemon thread in launchInteractiveBrowserSession.
     */
    private void restoreSessionCookies(String cookiesJson) {
        Map<String, String> env = new HashMap<>();
        env.put("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node");
        env.put("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/lib/chromium/chromium");
        env.put("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1");

        try (Playwright playwright = Playwright.create(new Playwright.CreateOptions().setEnv(env))) {
            Browser browser = playwright.chromium().connectOverCDP("http://localhost:9222");
            if (browser.contexts().isEmpty()) {
                log.warn("[FB-Responder] restoreSessionCookies: no browser context found via CDP.");
                return;
            }
            BrowserContext ctx = browser.contexts().get(0);

            // Parse saved cookies JSON and reconstruct Playwright Cookie objects
            List<Map<String, Object>> rawList = objectMapper.readValue(cookiesJson, new TypeReference<>() {});
            List<Cookie> cookies = new ArrayList<>();
            for (Map<String, Object> raw : rawList) {
                Cookie cookie = new Cookie(
                        String.valueOf(raw.get("name")),
                        String.valueOf(raw.get("value"))
                );
                if (raw.containsKey("domain"))   cookie.setDomain(String.valueOf(raw.get("domain")));
                if (raw.containsKey("path"))     cookie.setPath(String.valueOf(raw.get("path")));
                if (raw.containsKey("secure"))   cookie.setSecure(Boolean.TRUE.equals(raw.get("secure")));
                if (raw.containsKey("httpOnly")) cookie.setHttpOnly(Boolean.TRUE.equals(raw.get("httpOnly")));
                if (raw.containsKey("expirationDate")) {
                    Object exp = raw.get("expirationDate");
                    if (exp instanceof Number) cookie.setExpires(((Number) exp).doubleValue());
                }
                if (raw.containsKey("sameSite")) {
                    try {
                        String ss = String.valueOf(raw.get("sameSite")).toUpperCase();
                        // Playwright uses STRICT / LAX / NONE — map legacy "NO_RESTRICTION" to NONE
                        if (ss.equals("STRICT")) {
                            cookie.setSameSite(SameSiteAttribute.STRICT);
                        } else if (ss.equals("LAX")) {
                            cookie.setSameSite(SameSiteAttribute.LAX);
                        } else {
                            cookie.setSameSite(SameSiteAttribute.NONE);
                        }
                    } catch (Exception ignored) {}
                }
                cookies.add(cookie);
            }

            ctx.addCookies(cookies);
            log.info("[FB-Responder] Injected {} cookies into Chromium via CDP.", cookies.size());

            // Use JavaScript to trigger navigation — this is fire-and-forget from Playwright's perspective.
            // We do NOT use page.navigate() which blocks until page load completes and interferes with
            // x11vnc's frame capture by keeping Chromium busy inside a CDP session.
            if (!ctx.pages().isEmpty()) {
                ctx.pages().get(0).evaluate("() => { window.location.href = 'https://www.facebook.com'; }");
                log.info("[FB-Responder] Triggered navigation to facebook.com via JS eval.");
            }
        } catch (Exception e) {
            log.warn("[FB-Responder] Could not restore session cookies via CDP: {}", e.getMessage());
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
            // Use waitFor() on each pkill so we don't return until the OS has processed the signal.
            // fire-and-forget pkill was the root cause of the "stuck on second launch" bug:
            // the old websockify was still holding port 6080 when the next launch tried to bind it.
            new ProcessBuilder("pkill", "-TERM", "-f", "chromium").start().waitFor(3, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-TERM", "-f", "openbox").start().waitFor(2, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-TERM", "-f", "websockify").start().waitFor(3, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-TERM", "-f", "x11vnc").start().waitFor(3, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-TERM", "-f", "Xvfb").start().waitFor(3, java.util.concurrent.TimeUnit.SECONDS);

            // Force-kill any survivors that ignored SIGTERM
            new ProcessBuilder("pkill", "-9", "-f", "websockify").start().waitFor(2, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-9", "-f", "x11vnc").start().waitFor(2, java.util.concurrent.TimeUnit.SECONDS);
            new ProcessBuilder("pkill", "-9", "-f", "Xvfb").start().waitFor(2, java.util.concurrent.TimeUnit.SECONDS);

            // Block until port 6080 is actually free — this is the critical guard that prevents
            // the new websockify from racing against a zombie of the old one.
            waitForPortClosed(6080, 10);
        } catch (Exception e) {
            log.warn("[FB-Responder] cleanupProcesses error: {}", e.getMessage());
        }
    }

    /**
     * Returns true if websockify (port 6080) is currently accepting TCP connections.
     * Used by the REST health endpoint so the frontend can poll before rendering the iframe.
     */
    public boolean isVncReady() {
        try (Socket s = new Socket("localhost", 6080)) {
            return s.isConnected();
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * Blocks the calling thread until {@code localhost:port} accepts a TCP connection
     * or {@code timeoutSeconds} elapses. Uses exponential back-off starting at 200 ms
     * to avoid hammering the OS with rapid retries.
     *
     * @param port           the TCP port to probe
     * @param timeoutSeconds maximum seconds to wait before giving up
     */
    private void waitForPort(int port, int timeoutSeconds) {
        long deadline = System.currentTimeMillis() + (long) timeoutSeconds * 1000;
        long sleepMs = 200;
        while (System.currentTimeMillis() < deadline) {
            try (Socket s = new Socket("localhost", port)) {
                if (s.isConnected()) {
                    log.info("[FB-Responder] Port {} is ready.", port);
                    return;
                }
            } catch (Exception ignored) {}
            try {
                Thread.sleep(sleepMs);
                // Exponential back-off capped at 1s to remain responsive
                sleepMs = Math.min(sleepMs * 2, 1000);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        log.warn("[FB-Responder] Timed out waiting for port {} to open after {}s.", port, timeoutSeconds);
    }

    /**
     * Blocks until {@code localhost:port} refuses connections (i.e. the process holding
     * the port has actually exited) or {@code timeoutSeconds} elapses.
     * This complements {@link #waitForPort} to guarantee a clean port hand-off between
     * an old and a new websockify process.
     */
    private void waitForPortClosed(int port, int timeoutSeconds) {
        long deadline = System.currentTimeMillis() + (long) timeoutSeconds * 1000;
        long sleepMs = 200;
        while (System.currentTimeMillis() < deadline) {
            try (Socket s = new Socket("localhost", port)) {
                // Port still open — keep waiting
                log.debug("[FB-Responder] Port {} still open, waiting for it to close...", port);
            } catch (Exception e) {
                log.info("[FB-Responder] Port {} is now closed.", port);
                return; // Connection refused = port is free
            }
            try {
                Thread.sleep(sleepMs);
                sleepMs = Math.min(sleepMs * 2, 1000);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        log.warn("[FB-Responder] Port {} still open after {}s cleanup wait — proceeding anyway.", port, timeoutSeconds);
    }
}
