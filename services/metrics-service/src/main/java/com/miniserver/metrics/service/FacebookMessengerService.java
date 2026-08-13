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
            // Remove stale lock files if previous process crashed.
            new java.io.File(dir, "SingletonLock").delete();
            new java.io.File(dir, "SingletonSocket").delete();
            new java.io.File(dir, "SingletonCookie").delete();

            // Clear Chromium's session restoration files so it doesn't restore the last-visited
            // thread URL on next launch. Without this, launchPersistentContext reopens the specific
            // thread URL instead of the inbox root, which prevents the sidebar from loading.
            // IMPORTANT: we do NOT touch IndexedDB or LocalStorage — that's where E2EE PIN keys live.
            java.io.File defaultDir = new java.io.File(dir, "Default");
            if (defaultDir.exists()) {
                new java.io.File(defaultDir, "Current Session").delete();
                new java.io.File(defaultDir, "Current Tabs").delete();
                new java.io.File(defaultDir, "Last Session").delete();
                new java.io.File(defaultDir, "Last Tabs").delete();
            }
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

    // Lean Chromium args for headless automation — disables all non-essential features.
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
            "--window-size=1920,1080",
            // Prevent Chromium from restoring the last session or showing crash dialogs.
            // Without these flags, a persistent context launched after the previous one closed
            // abnormally will ask to restore the last URLs, which blocks our navigation.
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--restore-last-session=false"
    );

    // JS injected into every new page to hide Playwright's automation fingerprint from Facebook's bot detection.
    private static final String WEBDRIVER_STEALTH_SCRIPT =
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });" +
            "window.chrome = { runtime: {} };" +
            "Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });" +
            "Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN','vi','en-US','en'] });";

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

        if (!scanRunning.compareAndSet(false, true)) {
            log.info("[FB-Responder] Scheduled scan skipped: another scan or test send is currently running.");
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
        } finally {
            scanRunning.set(false);
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
        cooldownMap.clear();
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
     *
     * Navigation strategy: always land on inbox root (/messages/t/) first so the Facebook SPA
     * can fully hydrate its React state before we interact with any specific thread.
     * Direct navigation to a thread URL in a fresh headless context causes a blank chat panel
     * because React's client-side router needs the root route to bootstrap global state first.
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

            // Case 2: Standalone check using persistent browser context.
            // We use launchPersistentContext (NOT ephemeral) so IndexedDB is preserved.
            // IndexedDB stores the E2EE PIN key for Messenger's end-to-end encrypted conversations.
            // Without it, Facebook shows a "Enter PIN" screen on every conversation open.
            // Session restoration files are cleared in preparePersistentProfileDir() so Chromium
            // always starts at the URL we navigate to, not at the last-visited thread URL.
            preparePersistentProfileDir();

            BrowserType.LaunchPersistentContextOptions pOptions = new BrowserType.LaunchPersistentContextOptions()
                    .setHeadless(true)
                    .setArgs(CHROMIUM_ARGS)
                    .setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
                    .setViewportSize(1920, 1080);

            if (Paths.get("/usr/bin/chromium").toFile().exists()) {
                pOptions.setExecutablePath(Paths.get("/usr/bin/chromium"));
            } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
                pOptions.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
            }

            try (BrowserContext context = playwright.chromium().launchPersistentContext(Paths.get(PROFILE_DIR_PATH), pOptions)) {
                context.addInitScript(WEBDRIVER_STEALTH_SCRIPT);

                if (cfg.getCookiesJson() != null && !cfg.getCookiesJson().isBlank()) {
                    applyCookies(context, cfg.getCookiesJson());
                }

                // CRITICAL: Always create a fresh new page. Reusing an existing page from the
                // persistent context means that page may already be in a mid-session state (e.g.
                // on a specific thread URL), causing navigation inconsistencies. A new page always
                // starts blank and navigates cleanly to the URL we specify.
                // Close any leftover pages from previous sessions first to conserve memory.
                for (Page p : context.pages()) {
                    try { p.close(); } catch (Exception ignored) {}
                }
                Page page = context.newPage();

                // Navigate to Messenger inbox root from a blank page.
                page.navigate("https://www.facebook.com/messages/t/",
                        new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(20000));
                page.waitForTimeout(3000);

                String currentUrl = page.url();
                log.info("[FB-Responder] Navigated to inbox. Current URL: {}", currentUrl);

                if (currentUrl.contains("login") || page.title().contains("Log in") || page.title().contains("Đăng nhập")) {
                    log.warn("[FB-Responder] Cookies expired or invalid. Redirected to login page.");
                    updateStatus(cfg, "Lỗi: Session Cookies hết hạn hoặc không hợp lệ. Vui lòng cập nhật Cookies mới.",
                            LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")));
                    return 0;
                }

                try {
                    page.waitForSelector(
                            "a[href*='/messages/t/'], a[href*='/messages/e2ee/t/'], a[href*='/messages/requests/']",
                            new Page.WaitForSelectorOptions().setTimeout(12000));
                    log.info("[FB-Responder] Sidebar loaded. URL: {}", page.url());
                } catch (Exception e) {
                    Object diagResult = page.evaluate(
                            "() => { let links = document.querySelectorAll('a[href]'); " +
                            "let msgLinks = Array.from(links).filter(a => a.href.includes('/messages/')).map(a => a.href); " +
                            "return JSON.stringify({ url: window.location.href, title: document.title, msgLinks: msgLinks.slice(0,5), totalLinks: links.length }); }");
                    log.warn("[FB-Responder] Sidebar timeout. DOM diag: {}", diagResult);
                }

                try { page.keyboard().press("Escape"); page.waitForTimeout(200); } catch (Exception ignored) {}

                int totalReplies = inspectAndReply(page, cfg);

                // Also scan Message Requests tab (Tin nhắn đang chờ) for non-friends/strangers
                try {
                    log.info("[FB-Responder] Navigating to Message Requests inbox (Tin nhắn đang chờ)...");
                    page.navigate("https://www.facebook.com/messages/requests/",
                            new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(15000));
                    page.waitForTimeout(5000);
                    totalReplies += inspectAndReply(page, cfg);
                } catch (Exception e) {
                    log.warn("[FB-Responder] Scanning Message Requests tab encountered notice: {}", e.getMessage());
                }

                // Also scan Spam Requests tab (Tin nhắn Spam / Bị ẩn)
                try {
                    log.info("[FB-Responder] Navigating to Spam Requests inbox (Tin nhắn Spam)...");
                    page.navigate("https://www.facebook.com/messages/requests/spam/",
                            new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(15000));
                    page.waitForTimeout(5000);
                    totalReplies += inspectAndReply(page, cfg);
                } catch (Exception e) {
                    log.warn("[FB-Responder] Scanning Spam Requests tab encountered notice: {}", e.getMessage());
                }

                return totalReplies;
            }
        }
    }

    /**
     * Scans the Messenger inbox sidebar for unread DM threads and sends AI away-replies.
     *
     * Uses anchor tag links (a[href*='/messages/t/']) as the thread selector — these are more
     * reliable than role-based selectors because:
     * 1. The href attribute explicitly identifies the thread and lets us extract the thread ID.
     * 2. Anchor tags are structurally stable across Facebook DOM updates.
     * 3. We can skip group chats by checking if the href belongs to a known group pattern.
     */
    private int inspectAndReply(Page page, FacebookConfig cfg) {
        int autoRepliesSent = 0;

        // Scroll sidebar to hydrate all threads in virtualized list
        try {
            page.evaluate("() => {" +
                    "  let sidebar = document.querySelector('[role=\"navigation\"], div[aria-label*=\"\u0110o\u1ea1n chat\"], div[aria-label*=\"Tin nh\u1eafn\"], div[aria-label*=\"Chats\"]');" +
                    "  if (sidebar) { sidebar.scrollTop = 0; sidebar.scrollBy(0, 400); }" +
                    "}");
            page.waitForTimeout(500);
        } catch (Exception ignored) {}

        // Query all DM + E2EE + Message Requests + Spam conversation URLs from the sidebar.
        @SuppressWarnings("unchecked")
        List<String> threadHrefs = (List<String>) page.evaluate("() => {" +
                "  let links = Array.from(document.querySelectorAll('a[href*=\"/messages/t/\"], a[href*=\"/messages/e2ee/t/\"], a[href*=\"/messages/requests/\"], a[href*=\"/messages/read/\"]'));" +
                "  return links.map(a => a.href).filter(h => h && h.trim().length > 0 && !h.endsWith('/messages/t/') && !h.endsWith('/messages/requests/') && !h.endsWith('/messages/requests') && !h.endsWith('/messages/requests/spam/') && !h.endsWith('/messages/requests/spam'));" +
                "}");

        log.info("[FB-Responder] Found {} conversation URLs in sidebar.", threadHrefs != null ? threadHrefs.size() : 0);

        if (threadHrefs == null || threadHrefs.isEmpty()) {
            log.warn("[FB-Responder] No thread URLs found. Sidebar may not have loaded correctly. URL: {}", page.url());
            return 0;
        }

        // Scan up to 20 threads to reach past group chats at the top of the inbox
        int maxCheck = Math.min(threadHrefs.size(), 20);
        for (int i = 0; i < maxCheck; i++) {
            try {
                String href = threadHrefs.get(i);
                if (href == null || href.isBlank()) continue;

                // Extract the unique path/ID part of the thread (e.g. "t/100045592363397/" or "e2ee/t/1019980833988260/")
                String threadPath = href.replaceAll(".*/messages/", "");

                // Navigate directly to thread URL to guarantee React mounts the active conversation window
                try {
                    page.navigate(href, new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(12000));
                } catch (Exception e) {
                    log.warn("[FB-Responder] Navigation to '{}' failed/timed out: {}", href, e.getMessage());
                }

                page.waitForTimeout(1000);

                // Poll up to 6s for the active chat panel header to render after navigation.
                String senderName = waitForChatHeaderToLoad(page, 6000);

                // Handle E2EE PIN screen if it appears after opening a conversation.
                handleE2eePinScreen(page);

                if (senderName == null || senderName.isBlank()) {
                    senderName = extractCurrentChatHeaderName(page);
                }

                boolean isGroup = isGroupOrCommunityChat(page);
                if (isGroup) {
                    log.info("[FB-Responder] Thread #{} [{}] is a GROUP CHAT. Skipping.", i, href);
                    continue;
                }

                if (senderName == null || senderName.isBlank()) {
                    Object diag = page.evaluate("() => {" +
                            "  let headers = Array.from(document.querySelectorAll('header, [role=\"main\"] header, [role=\"main\"] h1, [role=\"main\"] h2, h2')).map(el => ({ tag: el.tagName, role: el.getAttribute('role'), text: el.innerText?.trim()?.substring(0,50) }));" +
                            "  let mainText = document.querySelector('[role=\"main\"]')?.innerText?.trim()?.substring(0,100) || '';" +
                            "  return JSON.stringify({ url: window.location.href, title: document.title, mainText, headers });" +
                            "}");
                    log.info("[FB-Responder] Thread #{} [{}] empty header. DOM diag: {}", i, href, diag);
                    continue;
                }

                // Safety: verify header matches a real contact name (blocks spurious clicks on nav elements)
                if (!verifyRecipientIdentity(page, senderName)) {
                    log.warn("[FB-Responder] Thread #{} header '{}' failed identity check. Skipping.", i, senderName);
                    continue;
                }

                int unrepliedCount = countUnrepliedIncomingMessages(page);
                log.info("[FB-Responder] DM with '{}': {} unreplied incoming message(s).", senderName, unrepliedCount);

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

    /**
     * Opens a specific Messenger thread by finding and clicking its sidebar anchor link.
     * If the thread is not present in the sidebar (no prior conversation), falls back to the
     * "New Message" compose flow to search for the contact by name.
     *
     * @param page           active Playwright page, already on the Messenger inbox root
     * @param threadId       numeric Facebook user/thread ID (e.g. "100045592363397")
     * @param contactName    display name to verify after opening (e.g. "Trần Văn Mạnh")
     * @return true if the chat window was opened and identity was verified
     */
    /**
     * Detects and automatically handles the Facebook Messenger E2EE PIN entry screen.
     *
     * When a Messenger conversation uses End-to-End Encryption and the persistent browser profile
     * does not yet have the IndexedDB decryption key, Facebook shows a PIN entry dialog.
     * This method detects that screen and fills the hardcoded PIN so the key is derived and stored
     * in IndexedDB — meaning subsequent scans will NOT trigger this screen again.
     *
     * The PIN screen selector targets: any visible input near text containing "PIN" or
     * "khôi phục" (recover). This is resilient to Facebook DOM changes because it
     * looks for a password-type input or a numeric input within the page.
     *
     * @param page  the active Playwright page, already on the conversation URL.
     */
    private void handleE2eePinScreen(Page page) {
        try {
            // Fast-path check: evaluate JS to see if a PIN screen is present.
            // We look for an input field of type 'password', 'number', or 'text' that is
            // adjacent to heading text containing PIN-related keywords.
            Boolean pinScreenPresent = (Boolean) page.evaluate(
                    "() => {" +
                    "  const heading = document.querySelector('h2,h3,h4,[role=heading]');" +
                    "  if (!heading) return false;" +
                    "  const text = (heading.innerText || '').toLowerCase();" +
                    "  if (!text.includes('pin') && !text.includes('kh\u00f4i ph\u1ee5c') && !text.includes('recover') && !text.includes('m\u00e3')) return false;" +
                    "  const inp = document.querySelector('input[type=password], input[type=number], input[inputmode=numeric], input[aria-label*=PIN]');" +
                    "  return inp !== null;" +
                    "}");

            if (!Boolean.TRUE.equals(pinScreenPresent)) {
                return; // No PIN screen — nothing to do
            }

            log.info("[FB-Responder] E2EE PIN screen detected. Attempting automatic PIN entry (090325)...");

            // Find the PIN input field — try multiple selectors in order of specificity
            ElementHandle pinInput = page.querySelector(
                    "input[type='password'], input[type='number'], input[inputmode='numeric'], " +
                    "input[aria-label*='PIN'], input[aria-label*='pin'], input[aria-label*='M\u00e3']");

            if (pinInput == null) {
                // Fallback: find any input visible near the PIN heading
                pinInput = page.querySelector("input");
            }

            if (pinInput != null) {
                pinInput.click();
                page.waitForTimeout(200);
                pinInput.fill("090325");
                page.waitForTimeout(500);

                // Submit: try pressing Enter, then look for a submit/continue button
                page.keyboard().press("Enter");
                page.waitForTimeout(1500);

                // If still on PIN screen (Enter didn’t work), click the confirm button
                ElementHandle confirmBtn = page.querySelector(
                        "[aria-label*='Tiếp theo'], [aria-label*='Xác nhập'], [aria-label*='Continue'], " +
                        "[aria-label*='OK'], [aria-label*='Submit'], [role='button']:not([aria-label*='Huỷ']):not([aria-label*='Cancel'])");
                if (confirmBtn != null) {
                    confirmBtn.click();
                    page.waitForTimeout(2000);
                }

                log.info("[FB-Responder] PIN submitted. Waiting for conversation to unlock...");
                page.waitForTimeout(2000);

                String headerAfterPin = extractCurrentChatHeaderName(page);
                if (headerAfterPin != null && !headerAfterPin.isBlank()
                        && !headerAfterPin.toLowerCase().contains("pin")
                        && !headerAfterPin.toLowerCase().contains("kh\u00f4i ph\u1ee5c")) {
                    log.info("[FB-Responder] PIN entry SUCCESS. Conversation header: '{}'", headerAfterPin);
                } else {
                    log.warn("[FB-Responder] PIN entry may have failed. Header after PIN: '{}'", headerAfterPin);
                }
            } else {
                log.warn("[FB-Responder] PIN screen detected but no input field found. Cannot auto-fill.");
            }
        } catch (Exception e) {
            log.warn("[FB-Responder] Error handling E2EE PIN screen: {}", e.getMessage());
        }
    }

    private boolean openTargetThreadInSidebar(Page page, String threadId, String contactName) {
        // Step 1: Look for the thread's anchor link in the current sidebar.
        log.info("[FB-TestSend] Searching sidebar for thread link containing '{}'", threadId);
        List<ElementHandle> anchors = page.querySelectorAll(
                "a[href*='/messages/t/"+threadId+"'], a[href*='/messages/e2ee/t/"+threadId+"']");

        if (!anchors.isEmpty()) {
            try {
                log.info("[FB-TestSend] Found sidebar link for thread '{}'. Clicking...", threadId);
                try {
                    anchors.get(0).evaluate("el => (el.closest('[role=\"row\"], [role=\"link\"], [role=\"button\"]') || el).click()");
                } catch (Exception ignored) {
                    anchors.get(0).click();
                }
                page.waitForTimeout(500);
                if (!page.url().contains(threadId)) {
                    try {
                        page.navigate("https://www.facebook.com/messages/t/" + threadId + "/",
                                new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(10000));
                    } catch (Exception ignored) {}
                }

                // Poll up to 6s for the chat panel header to appear after the SPA route change.
                String header = waitForChatHeaderToLoad(page, 6000);

                // Automatically handle E2EE PIN screen if it appears.
                handleE2eePinScreen(page);

                if (header == null) header = extractCurrentChatHeaderName(page);
                if (header != null && (header.contains("PIN") || header.contains("m\u00e3") || header.contains("kh\u00f4i ph\u1ee5c"))) {
                    log.warn("[FB-TestSend] Still on PIN screen after auto-fill attempt (header='{}'). Skipping.", header);
                    return false;
                }

                if (verifyRecipientIdentity(page, contactName)) {
                    log.info("[FB-TestSend] Sidebar click SUCCESS. Verified chat header for '{}'", contactName);
                    return true;
                }
                log.warn("[FB-TestSend] Sidebar click done but header mismatch. Header: '{}'", header);
            } catch (Exception e) {
                log.warn("[FB-TestSend] Sidebar anchor click failed: {}", e.getMessage());
            }
        } else {
            log.info("[FB-TestSend] No sidebar link found for thread '{}'. Will try direct SPA navigate.", threadId);
        }

        // Step 2: Fallback — direct SPA navigation to the thread URL.
        log.info("[FB-TestSend] Attempting direct SPA navigation to thread URL...");
        try {
            String threadUrl = "https://www.facebook.com/messages/t/" + threadId + "/";
            page.navigate(threadUrl,
                    new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(15000));

            // Poll up to 8s for the chat panel header to render
            String header = waitForChatHeaderToLoad(page, 8000);

            log.info("[FB-TestSend] Direct navigate result. URL: {} Header: '{}'", page.url(), header);

            // Handle E2EE PIN screen if it appears on direct navigate
            handleE2eePinScreen(page);

            // URL-based identity check: if the current URL contains the expected thread ID,
            // we are definitively on the correct conversation. This is necessary for E2EE threads
            // where the chat panel body won't render in a headless context without the IndexedDB
            // PIN key — the URL is the only reliable indicator we can check programmatically.
            String currentUrl = page.url();
            if (currentUrl.contains(threadId)) {
                log.info("[FB-TestSend] URL verification passed (URL contains thread ID '{}').", threadId);
                return true;
            }

            // Secondary check: header name match (works for non-E2EE conversations)
            if (verifyRecipientIdentity(page, contactName)) {
                log.info("[FB-TestSend] Direct SPA navigate SUCCESS. Verified chat for '{}'", contactName);
                return true;
            }
            log.warn("[FB-TestSend] Direct navigate verification failed. Header: '{}' URL: {}",
                    extractCurrentChatHeaderName(page), page.url());
        } catch (Exception e) {
            log.warn("[FB-TestSend] Direct SPA navigate error: {}", e.getMessage());
        }

        return false;
    }

    /**
     * Polls until extractCurrentChatHeaderName returns a valid header for the active chat panel,
     * or until timeoutMs expires. This prevents premature header reads after clicking a thread anchor.
     */
    private String waitForChatHeaderToLoad(Page page, int timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            String header = extractCurrentChatHeaderName(page);
            if (header != null && !header.isBlank()
                    && !header.equalsIgnoreCase("Đoạn chat")
                    && !header.equalsIgnoreCase("Messenger")) {
                return header;
            }
            try { page.waitForTimeout(300); } catch (Exception ignored) {}
        }
        return extractCurrentChatHeaderName(page);
    }

    /** Reads the current active chat's header name from the DOM. Returns null if not found. */
    private String extractCurrentChatHeaderName(Page page) {
        try {
            Object result = page.evaluate("() => {" +
                    "  let main = document.querySelector('[role=\"main\"]');" +
                    "  if (main) {" +
                    "    let header = main.querySelector('header, [role=\"banner\"]');" +
                    "    if (header) {" +
                    "      let titleEl = header.querySelector('h1, h2, [role=\"heading\"], a[href*=\"facebook.com/\"] span, span[dir=\"auto\"]');" +
                    "      if (titleEl && titleEl.innerText && titleEl.innerText.trim()) {" +
                    "        let txt = titleEl.innerText.trim();" +
                    "        let lower = txt.toLowerCase();" +
                    "        if (!lower.startsWith('cu\u1ed9c tr\u00f2 chuy\u1ec7n') && !lower.startsWith('tin nh\u1eafn') && !lower.includes('messenger') && !lower.startsWith('(')) {" +
                    "          return txt;" +
                    "        }" +
                    "      }" +
                    "    }" +
                    "    let text = main.innerText || '';" +
                    "    let lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);" +
                    "    for (let line of lines) {" +
                    "      let lower = line.toLowerCase();" +
                    "      if (lower.startsWith('cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi ')) {" +
                    "        return line.substring('cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi '.length).trim();" +
                    "      }" +
                    "    }" +
                    "  }" +
                    "  let currentPath = window.location.pathname || '';" +
                    "  if (currentPath.includes('/messages/')) {" +
                    "    let parts = currentPath.split('/messages/');" +
                    "    if (parts.length > 1) {" +
                    "      let threadId = parts[1].replace(/requests\\/|e2ee\\/|t\\//g, '').replace(/\\//g, '');" +
                    "      if (threadId.length > 0) {" +
                    "        let sidebarLink = document.querySelector('a[href*=\"' + threadId + '\"]');" +
                    "        if (sidebarLink) {" +
                    "          let nameEl = sidebarLink.querySelector('span[dir=\"auto\"], span');" +
                    "          if (nameEl && nameEl.innerText && nameEl.innerText.trim()) {" +
                    "            let stxt = nameEl.innerText.trim();" +
                    "            let lower = stxt.toLowerCase();" +
                    "            if (!lower.includes('messenger') && !lower.startsWith('(')) return stxt;" +
                    "          }" +
                    "        }" +
                    "      }" +
                    "    }" +
                    "  }" +
                    "  let docTitle = document.title || '';" +
                    "  let candidate = '';" +
                    "  if (docTitle.includes('|')) candidate = docTitle.split('|')[0].trim();" +
                    "  else if (docTitle.includes('-')) candidate = docTitle.split('-')[0].trim();" +
                    "  else candidate = docTitle.trim();" +
                    "  let lowerCand = candidate.toLowerCase();" +
                    "  if (candidate.length > 0 && !lowerCand.includes('messenger') && !lowerCand.startsWith('(') && !lowerCand.startsWith('tin nh\u1eafn')) {" +
                    "    return candidate;" +
                    "  }" +
                    "  return null;" +
                    "}");
            return result instanceof String s ? s : null;
        } catch (Exception e) {
            return null;
        }
    }

    private boolean verifyRecipientIdentity(Page page, String expectedTarget) {
        if (expectedTarget == null || expectedTarget.isBlank()) {
            return true;
        }

        Object checkResult = page.evaluate("(expected) => {" +
                "  let headerText = '';" +
                "  let main = document.querySelector('[role=\"main\"]');" +
                "  if (main) {" +
                "    let header = main.querySelector('header, [role=\"banner\"]');" +
                "    if (header) {" +
                "      let titleEl = header.querySelector('h1, h2, [role=\"heading\"], a[href*=\"facebook.com/\"] span, span[dir=\"auto\"]');" +
                "      if (titleEl && titleEl.innerText && titleEl.innerText.trim()) {" +
                "        headerText = titleEl.innerText.trim();" +
                "      }" +
                "    }" +
                "    if (!headerText) {" +
                "      let text = main.innerText || '';" +
                "      let lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);" +
                "      for (let line of lines) {" +
                "        let lower = line.toLowerCase();" +
                "        if (lower.startsWith('cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi ')) {" +
                "          headerText = line.substring('cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi '.length).trim();" +
                "          break;" +
                "        }" +
                "      }" +
                "    }" +
                "  }" +
                "  if (!headerText) {" +
                "    let currentPath = window.location.pathname || '';" +
                "    if (currentPath.includes('/messages/')) {" +
                "      let parts = currentPath.split('/messages/');" +
                "      if (parts.length > 1) {" +
                "        let threadId = parts[1].replace(/requests\\/|e2ee\\/|t\\//g, '').replace(/\\//g, '');" +
                "        if (threadId.length > 0) {" +
                "          let sidebarLink = document.querySelector('a[href*=\"' + threadId + '\"]');" +
                "          if (sidebarLink) {" +
                "            let nameEl = sidebarLink.querySelector('span[dir=\"auto\"], span');" +
                "            if (nameEl && nameEl.innerText && nameEl.innerText.trim()) {" +
                "              headerText = nameEl.innerText.trim();" +
                "            }" +
                "          }" +
                "        }" +
                "      }" +
                "    }" +
                "  }" +
                "  if (!headerText) {" +
                "    let docTitle = document.title || '';" +
                "    if (docTitle.includes('|')) headerText = docTitle.split('|')[0].trim();" +
                "    else if (docTitle.includes('-')) headerText = docTitle.split('-')[0].trim();" +
                "    else headerText = docTitle.trim();" +
                "  }" +
                "  let lower = (headerText || '').toLowerCase();" +
                "  if (!headerText || lower.includes('messenger') || lower.startsWith('(')) {" +
                "    return JSON.stringify({ valid: false, reason: 'Header text is empty or generic title: ' + headerText, headerText, currentUrl: window.location.href });" +
                "  }" +
                "  let exp = expected.toLowerCase().trim();" +
                "  let matchName = lower.includes(exp);" +
                "  let words = exp.split(/\\s+/).filter(w => w.length > 1);" +
                "  let anyWordMatch = words.some(w => lower.includes(w));" +
                "  if (!matchName && !anyWordMatch) {" +
                "    return JSON.stringify({ valid: false, reason: 'Header \"' + headerText + '\" does not match target \"' + expected + '\"', headerText, currentUrl: window.location.href });" +
                "  }" +
                "  return JSON.stringify({ valid: true, headerText, currentUrl: window.location.href });" +
                "}", expectedTarget);

        log.info("[FB-Responder] Recipient Identity Verification: {}", checkResult);
        return checkResult != null && checkResult.toString().contains("\"valid\":true");
    }

    private boolean isGroupOrCommunityChat(Page page) {
        Object isGroupResult = page.evaluate("() => {" +
                // Only look at the chat panel header — NOT document.body or sidebar panel.
                // When the chat panel doesn't render (E2EE headless context), return false
                // rather than falling back to body/sidebar text which contains 'Thành viên' etc.
                "  let header = document.querySelector('[role=\"main\"] header');" +
                "  if (!header) return false;" +
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
                "  let main = document.querySelector('[role=\"main\"]');" +
                "  if (!main) return 0;" +
                "  let chatRegion = main.querySelector('[role=\"region\"], [aria-label*=\"Tin nhắn\"], [aria-label*=\"Messages\"]') || main;" +
                "  let regionRect = chatRegion.getBoundingClientRect();" +
                "  let mainMidX = regionRect.left + (regionRect.width / 2);" +
                "  let rawRows = Array.from(main.querySelectorAll('[role=\"row\"], [data-scope=\"messages_table\"]'));" +
                "  if (rawRows.length === 0) {" +
                "    rawRows = Array.from(main.querySelectorAll('div[dir=\"auto\"]')).map(el => el.closest('div[style*=\"flex\"]') || el).filter(Boolean);" +
                "  }" +
                "  let rows = rawRows.filter(el => !rawRows.some(parent => parent !== el && parent.contains(el)));" +
                "  let count = 0;" +
                "  for (let i = rows.length - 1; i >= 0; i--) {" +
                "    let row = rows[i];" +
                "    let text = (row.innerText || '').trim();" +
                "    if (!text) continue;" +
                "    let lowerText = text.toLowerCase();" +
                "    let isNoticeBanner = lowerText.includes('mu\u1ed1n g\u1eedi tin nh\u1eafn') || " +
                "                         lowerText.includes('mu\u1ed1n k\u1ebft n\u1ed1i') || " +
                "                         lowerText.includes('m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i') || " +
                "                         lowerText.includes('t\u00ednh n\u0103ng m\u00e3 h\u00f3a') || " +
                "                         lowerText.includes('t\u00ecm hi\u1ec3u th\u00eam') || " +
                "                         lowerText.includes('b\u1ea3o m\u1eadt b\u1eb1ng');" +
                "    if (isNoticeBanner) continue;" +
                "    let isOutgoing = false;" +
                "    let aria = (row.getAttribute('aria-label') || '') + ' ' + (row.querySelector('[aria-label]')?.getAttribute('aria-label') || '');" +
                "    // Outgoing messages explicitly state 'B\u1ea1n \u0111\u00e3 g\u1eedi' or 'You sent'. Generic 'Đã gửi X phút trước' is an incoming message timestamp!" +
                "    if (aria.includes('B\u1ea1n \u0111\u00e3 g\u1eedi') || aria.includes('You sent') || aria.startsWith('B\u1ea1n:') || aria.includes(' B\u1ea1n:')) {" +
                "      isOutgoing = true;" +
                "    }" +
                "    if (!isOutgoing) {" +
                "      let bubble = row.querySelector('div[dir=\"auto\"], div[style*=\"background\"], div[role=\"none\"]') || row;" +
                "      let bRect = bubble.getBoundingClientRect();" +
                "      if (bRect.width > 0 && bRect.left > mainMidX + 20) {" +
                "        isOutgoing = true;" +
                "      }" +
                "    }" +
                "    if (!isOutgoing) {" +
                "      let flexParent = row.closest('div[style*=\"flex-end\"]') || row;" +
                "      let comp = window.getComputedStyle(flexParent);" +
                "      if (comp.alignItems === 'flex-end' || comp.justifyContent === 'flex-end' || comp.flexDirection === 'row-reverse') {" +
                "        isOutgoing = true;" +
                "      }" +
                "    }" +
                "    if (isOutgoing) {" +
                "      break;" +
                "    } else {" +
                "      count++;" +
                "    }" +
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
                + "Hãy viết 1 câu trả lời ngắn gọn (1-2 câu), xưng là 'Tiểu Bảo Bảo trợ lí của Mạnh (Cua)', thông báo rằng anh Mạnh (Cua) hiện đang vắng mặt và đã nhận được " + unrepliedCount + " tin nhắn của họ, sẽ báo lại anh ấy ngay khi quay lại. "
                + "LƯU Ý QUAN TRỌNG: CHỈ TRẢ LỜI BẰNG CHỮ THƯỜNG THUẦN TÚY (PLAIN TEXT), KHÔNG DÙNG ĐỊNH DẠNG JSON, KHÔNG DÙNG THẺ XML, KHÔNG DÙNG THẺ FUNCTION/TOOL.";

        try {
            String raw = aiChatService.chat("fb-away-" + senderName.hashCode(), prompt);
            String cleaned = cleanAwayMessageText(raw);
            if (cleaned != null && !cleaned.isBlank()) {
                return cleaned;
            }
        } catch (Exception e) {
            log.warn("[FB-Responder] AI Chat Service error, using fallback away message: {}", e.getMessage());
        }

        return "Chào bạn, mình là Tiểu Bảo Bảo trợ lí của Mạnh (Cua). Hiện tại anh Mạnh (Cua) đang đi vắng và đã nhận được " + unrepliedCount + " tin nhắn của bạn. Mình sẽ báo lại anh ấy ngay khi quay lại nhé!";
    }

    private String cleanAwayMessageText(String rawText) {
        if (rawText == null || rawText.isBlank()) {
            return "";
        }
        String text = rawText;

        // 1. Remove XML/Function tags like <function>...</function>, <tool_call>...</tool_call>, </function>
        text = text.replaceAll("(?i)<function[^>]*>", "")
                   .replaceAll("(?i)</function>", "")
                   .replaceAll("(?i)<tool_call[^>]*>", "")
                   .replaceAll("(?i)</tool_call>", "");

        // 2. Remove markdown code fence blocks like ```json ... ```
        text = text.replaceAll("```[a-zA-Z]*", "").replaceAll("```", "");

        // 3. Extract text inside JSON object if LLM returned {"message": "...", "text": "..."}
        if (text.trim().startsWith("{") && text.contains("}")) {
            try {
                java.util.regex.Matcher strMatcher = java.util.regex.Pattern.compile("\"([^\"]{10,})\"").matcher(text);
                if (strMatcher.find()) {
                    text = strMatcher.group(1);
                }
            } catch (Exception ignored) {}
        }

        // 4. Remove leading/trailing quotes
        text = text.trim();
        if (text.startsWith("\"") && text.endsWith("\"") && text.length() > 2) {
            text = text.substring(1, text.length() - 1).trim();
        }

        // 5. Clean escaped quotes, newlines, extra spaces
        text = text.replace("\\n", " ").replace("\\\"", "\"").replace("\\t", " ").replaceAll("\\s+", " ").trim();

        return text;
    }

    private boolean sendMessengerReply(Page page, String text) {
        try {
            // Target the bottom-most LEAF-NODE contenteditable input box inside [role='main']
            // Wrapper containers (like [aria-label*='Tin nhắn trong cuộc trò chuyện']) contain nested editables,
            // so filtering for leaf nodes (elements with 0 child editables) excludes wrapper containers and selects
            // the exact text input box at the bottom of the chat window.
            JSHandle handle = page.evaluateHandle("() => {" +
                    "  let main = document.querySelector('[role=\"main\"]') || document.body;" +
                    "  let editables = Array.from(main.querySelectorAll('div[contenteditable=\"true\"], div[data-lexical-editor=\"true\"], [role=\"textbox\"]'));" +
                    "  let leafEditables = editables.filter(el => el.querySelectorAll('div[contenteditable=\"true\"], div[role=\"textbox\"]').length === 0);" +
                    "  if (leafEditables.length > 0) {" +
                    "    leafEditables.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);" +
                    "    return leafEditables[0];" +
                    "  }" +
                    "  return null;" +
                    "}");

            ElementHandle targetInput = handle != null ? handle.asElement() : null;
            if (targetInput == null) {
                log.warn("[FB-Responder] Chat input box NOT found on page. URL: {}", page.url());
                return false;
            }

            String ariaLabel = (String) targetInput.evaluate("el => el.getAttribute('aria-label') || el.getAttribute('aria-placeholder') || ''");
            log.info("[FB-Responder] Target chat input box selected. ariaLabel='{}' URL={}", ariaLabel, page.url());

            // Step 1: Focus and click the target input box
            try {
                targetInput.click();
                targetInput.focus();
            } catch (Exception ignored) {}
            page.waitForTimeout(300);

            // Step 2: Inject text via JS Event Pipeline + execCommand (specifically designed for Lexical / DraftJS)
            targetInput.evaluate("(el, txt) => {" +
                    "  el.focus();" +
                    "  let sel = window.getSelection();" +
                    "  let range = document.createRange();" +
                    "  range.selectNodeContents(el);" +
                    "  sel.removeAllRanges();" +
                    "  sel.addRange(range);" +
                    "  try {" +
                    "    let inputEvt = new InputEvent('beforeinput', { bubbles: true, cancelable: true, inputType: 'insertText', data: txt });" +
                    "    el.dispatchEvent(inputEvt);" +
                    "  } catch (e) {}" +
                    "  document.execCommand('insertText', false, txt);" +
                    "  try {" +
                    "    el.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true }));" +
                    "  } catch (e) {}" +
                    "}", text);

            page.waitForTimeout(400);

            // Check if text successfully populated into editor; if not, use keyboard.insertText with explicit focus
            String typedText = (String) targetInput.evaluate("el => (el.innerText || '').trim()");
            if (typedText == null || typedText.isEmpty() || !typedText.contains(text.substring(0, Math.min(10, text.length())))) {
                log.info("[FB-Responder] JS execCommand did not populate text. Using keyboard.insertText with explicit focus...");
                try {
                    targetInput.click();
                    targetInput.focus();
                } catch (Exception ignored) {}
                page.keyboard().insertText(text);
                page.waitForTimeout(400);
            }

            // Verify text is now present in editor before submitting
            typedText = (String) targetInput.evaluate("el => (el.innerText || '').trim()");
            log.info("[FB-Responder] Editor content before submit: '{}'", typedText != null && typedText.length() > 30 ? typedText.substring(0, 30) : typedText);

            // Step 3: Submit message (Press Enter, then fallback to Send button if needed)
            page.keyboard().press("Enter");
            page.waitForTimeout(1000);

            String remainingText = (String) targetInput.evaluate("el => (el.innerText || '').trim()");
            if (remainingText != null && !remainingText.isEmpty() && remainingText.contains(text.substring(0, Math.min(10, text.length())))) {
                log.info("[FB-Responder] Editor still contains text ('{}') after Enter. Attempting Send button click...",
                        remainingText.substring(0, Math.min(20, remainingText.length())));

                ElementHandle sendBtn = page.querySelector(
                        "[role='main'] [aria-label*='G\u1eedi'], [role='main'] [aria-label*='Send'], " +
                        "[role='main'] [aria-label*='g\u1eedi'], [role='main'] [aria-label*='send'], " +
                        "[role='main'] div[role='button'][tabindex='0']:last-child");
                if (sendBtn != null) {
                    try {
                        sendBtn.click();
                        page.waitForTimeout(1000);
                    } catch (Exception ignored) {}
                }
            }

            // CRITICAL: Wait 4.5 seconds on active conversation page so Facebook's MQTT/GraphQL WebSocket network payload finishes transmitting and receives server ACK before any SPA navigation.
            log.info("[FB-Responder] Waiting 4.5s for Facebook MQTT/GraphQL network transmission to complete...");
            page.waitForTimeout(4500);

            // Step 4: Save PNG screenshot for visual verification
            try {
                page.screenshot(new Page.ScreenshotOptions().setPath(Paths.get("/tmp/fb_send_result.png")));
                log.info("[FB-Responder] Saved visual verification screenshot to /tmp/fb_send_result.png");
            } catch (Exception e) {
                log.warn("[FB-Responder] Could not save verification screenshot: {}", e.getMessage());
            }

            // Step 5: EMPIRICAL VERIFICATION — confirm message snippet is in conversation body
            Object verification = page.evaluate("(txt) => {" +
                    "  let main = document.querySelector('[role=\"main\"]') || document.body;" +
                    "  let mainText = main ? main.innerText || '' : '';" +
                    "  let snippet = txt.length > 15 ? txt.substring(0, 15) : txt;" +
                    "  let inBody = mainText.includes(snippet);" +
                    "  return JSON.stringify({ inBody, snippet });" +
                    "}", text);

            log.info("[FB-Responder] Message send verification result: {}", verification);

            boolean isVerified = verification != null && verification.toString().contains("\"inBody\":true");
            if (isVerified) {
                log.info("[FB-Responder] EMPIRICALLY VERIFIED: Message was successfully typed and sent to chat!");
                return true;
            } else {
                log.warn("[FB-Responder] Send verification FAILED. Verification payload: {}", verification);
                return false;
            }
        } catch (Exception e) {
            log.error("[FB-Responder] Error typing/sending Messenger reply: {}", e.getMessage(), e);
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
        if (status != null && status.length() > 245) {
            status = status.substring(0, 242) + "...";
        }
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

    /** Direct test send to a target thread (overload with default contact name) */
    public Map<String, String> sendTestToThread(String threadTarget) {
        return sendTestToThread(threadTarget, "Trần Văn Mạnh");
    }

    /**
     * Sends a test AI away-message to a specific Messenger thread.
     *
     * Strategy (correct order):
     * 1. Navigate to Messenger inbox root (/messages/t/) — SPA bootstraps global state.
     * 2. Call openTargetThreadInSidebar() — finds the thread's sidebar anchor and clicks it,
     *    so the SPA router mounts the correct chat panel. Falls back to New Message compose.
     * 3. Verify chat header shows the correct contact name.
     * 4. Send the AI-generated away message.
     */
    public Map<String, String> sendTestToThread(String threadTarget, String expectedTargetName) {
        FacebookConfig cfg = configRepository.getConfig().orElseGet(FacebookConfig::new);
        if (cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) {
            return Map.of("status", "error", "message", "Chưa cấu hình Cookies Facebook.");
        }

        if (!scanRunning.compareAndSet(false, true)) {
            return Map.of("status", "running", "message", "Đang có tiến trình quét Messenger khác chạy. Vui lòng thử lại sau vài giây.");
        }

        String contactName = (expectedTargetName != null && !expectedTargetName.isBlank()) ? expectedTargetName : "Trần Văn Mạnh";

        // Extract numeric thread ID from the URL (e.g. "100045592363397" from ".../t/100045592363397")
        String threadId = threadTarget.replaceAll(".*/t/", "").replaceAll("/.*", "").trim();
        if (threadId.isBlank()) threadId = threadTarget;

        final String finalThreadId = threadId;

        scanExecutor.submit(() -> {
            Map<String, String> env = new HashMap<>(System.getenv());
            env.put("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1");
            env.put("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium");
            env.put("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node");

            try (Playwright playwright = Playwright.create(new Playwright.CreateOptions().setEnv(env))) {

                // Path A: VNC browser is running on CDP port 9222 — connect to the live session.
                // This is the same browser the user sees in the VNC panel, which is already logged in
                // and has all E2EE keys in IndexedDB. This is the most reliable path.
                if (isPortOpen("localhost", 9222)) {
                    log.info("[FB-TestSend] VNC browser detected on CDP port 9222. Connecting to live session...");
                    try {
                        Browser browser = playwright.chromium().connectOverCDP("http://localhost:9222");
                        if (!browser.contexts().isEmpty()) {
                            BrowserContext ctx = browser.contexts().get(0);
                            Page page = ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0);

                            // Navigate to inbox root so sidebar is available
                            page.navigate("https://www.facebook.com/messages/t/",
                                    new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(20000));
                            page.waitForTimeout(3000);

                            try {
                                page.waitForSelector(
                                        "a[href*='/messages/t/'], a[href*='/messages/e2ee/t/']",
                                        new Page.WaitForSelectorOptions().setTimeout(12000));
                                log.info("[FB-TestSend] Sidebar loaded via VNC CDP. URL: {}", page.url());
                            } catch (Exception e) {
                                log.warn("[FB-TestSend] Sidebar timeout on VNC. Proceeding anyway. URL: {}", page.url());
                            }

                            boolean opened = openTargetThreadInSidebar(page, finalThreadId, contactName);
                            if (!opened) {
                                log.warn("[FB-TestSend] ABORTED via VNC: Could not open verified chat window for '{}'", contactName);
                                return;
                            }

                            String verifiedName = extractCurrentChatHeaderName(page);
                            if (verifiedName == null || verifiedName.isBlank()) verifiedName = contactName;

                            String testMsg = generateAwayMessage(verifiedName, 1, cfg.getCustomMessage());
                            log.info("[FB-TestSend] Sending via VNC to verified recipient '{}': {}", verifiedName, testMsg);
                            boolean sent = sendMessengerReply(page, testMsg);
                            log.info("[FB-TestSend] VNC send result for '{}': {}", verifiedName, sent);
                            return;
                        }
                    } catch (Exception e) {
                        log.warn("[FB-TestSend] Failed to connect to VNC CDP session: {}. Falling back to persistent context.", e.getMessage());
                    }
                }

                // Path B: No VNC browser — use persistent context (IndexedDB preserved).
                // Session files are cleared by preparePersistentProfileDir() to prevent URL restoration.
                preparePersistentProfileDir();

                BrowserType.LaunchPersistentContextOptions pOptions = new BrowserType.LaunchPersistentContextOptions()
                        .setHeadless(true)
                        .setArgs(CHROMIUM_ARGS)
                        .setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
                        .setViewportSize(1920, 1080);

                if (Paths.get("/usr/bin/chromium").toFile().exists()) {
                    pOptions.setExecutablePath(Paths.get("/usr/bin/chromium"));
                } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
                    pOptions.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
                }

                try (BrowserContext context = playwright.chromium().launchPersistentContext(Paths.get(PROFILE_DIR_PATH), pOptions)) {
                    context.addInitScript(WEBDRIVER_STEALTH_SCRIPT);

                    applyCookies(context, cfg.getCookiesJson());

                    // Close all stale pages before opening a fresh one.
                    // Reusing an existing page from a previous session causes navigation issues
                    // because that page may already be at a specific thread URL.
                    for (Page p : context.pages()) {
                        try { p.close(); } catch (Exception ignored) {}
                    }
                    Page page = context.newPage();

                    log.info("[FB-TestSend] Navigating to Messenger inbox root...");
                    page.navigate("https://www.facebook.com/messages/t/",
                            new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(20000));
                    page.waitForTimeout(3000);

                    String landedUrl = page.url();
                    log.info("[FB-TestSend] Landed on URL: {}", landedUrl);
                    if (landedUrl.contains("login")) {
                        log.warn("[FB-TestSend] ABORTED: Redirected to login. Cookies may have expired.");
                        return;
                    }

                    try {
                        page.waitForSelector(
                                "a[href*='/messages/t/'], a[href*='/messages/e2ee/t/']",
                                new Page.WaitForSelectorOptions().setTimeout(12000));
                        log.info("[FB-TestSend] Inbox sidebar loaded. URL: {}", page.url());
                    } catch (Exception e) {
                        Object diagResult = page.evaluate(
                                "() => { let links = document.querySelectorAll('a[href]'); " +
                                "let msgLinks = Array.from(links).filter(a => a.href.includes('/messages/')).map(a => a.href); " +
                                "return JSON.stringify({ url: window.location.href, title: document.title, msgLinks: msgLinks.slice(0,5), totalLinks: links.length }); }");
                        log.warn("[FB-TestSend] Sidebar timeout. DOM diag: {}", diagResult);
                    }

                    boolean opened = openTargetThreadInSidebar(page, finalThreadId, contactName);
                    if (!opened) {
                        log.warn("[FB-TestSend] ABORTED: Could not open verified chat window for '{}'", contactName);
                        return;
                    }

                    String verifiedName = extractCurrentChatHeaderName(page);
                    if (verifiedName == null || verifiedName.isBlank()) verifiedName = contactName;

                    String testMsg = generateAwayMessage(verifiedName, 1, cfg.getCustomMessage());
                    log.info("[FB-TestSend] Sending test message to verified recipient '{}': {}", verifiedName, testMsg);

                    boolean sent = sendMessengerReply(page, testMsg);
                    log.info("[FB-TestSend] Send result for '{}': {}", verifiedName, sent);
                }

            } catch (Exception e) {
                log.error("[FB-TestSend] Error in sendTestToThread for '{}': {}", contactName, e.getMessage(), e);
            } finally {
                scanRunning.set(false);
            }
        });

        return Map.of("status", "started", "message", "Đã khởi động tiến trình gửi tin nhắn thử nghiệm có xác thực tới " + contactName);
    }
}
