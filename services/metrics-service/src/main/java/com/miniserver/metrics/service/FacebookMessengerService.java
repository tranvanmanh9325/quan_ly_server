package com.miniserver.metrics.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.AriaRole;
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
import java.time.LocalDateTime;
import java.util.*;
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

    public FacebookMessengerService(FacebookConfigRepository configRepository,
                                    AiChatService aiChatService) {
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

                // Scan non-E2EE Message Requests (Tin nhắn đang chờ thường)
                try {
                    log.info("[FB-Responder] Navigating to Message Requests inbox (/messages/requests/)...");
                    page.navigate("https://www.facebook.com/messages/requests/",
                            new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(15000));
                    page.waitForTimeout(3000);
                    totalReplies += inspectAndReply(page, cfg);
                } catch (Exception e) {
                    log.warn("[FB-Responder] Scanning /messages/requests/ encountered notice: {}", e.getMessage());
                }

                // Scan "Có thể bạn biết" tab inside Message Requests.
                // This tab contains E2EE-encrypted requests from strangers and is only visible AFTER clicking
                // the "Có thể bạn biết" tab explicitly. It does NOT have its own URL — all tabs live under
                // /messages/requests/ and are rendered client-side via tab selection.
                try {
                    log.info("[FB-Responder] Clicking 'Có thể bạn biết' tab on /messages/requests/...");
                    page.navigate("https://www.facebook.com/messages/requests/",
                            new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(15000));
                    page.waitForTimeout(4000);

                    // Click "Có thể bạn biết" tab to switch to the E2EE/People You May Know filter
                    Boolean tabClicked = (Boolean) page.evaluate("() => {" +
                            "  let tabs = Array.from(document.querySelectorAll('[role=\"tab\"], [role=\"button\"], span, div'));" +
                            "  let tab = tabs.find(t => {" +
                            "    let txt = (t.innerText || '').trim();" +
                            "    return txt === 'Có thể bạn biết' || txt === 'People You May Know';" +
                            "  });" +
                            "  if (tab) { tab.click(); return true; }" +
                            "  return false;" +
                            "}");
                    log.info("[FB-Responder] 'Có thể bạn biết' tab clicked: {}", tabClicked);

                    // Wait generously for sidebar skeleton loading to finish and actual conversation items to appear
                    page.waitForTimeout(5000);

                    // Explicitly wait for actual conversation anchor links to appear (not skeleton placeholders)
                    try {
                        page.waitForSelector(
                                "a[href*='/messages/requests/t/'], a[href*='/messages/t/']",
                                new Page.WaitForSelectorOptions().setTimeout(8000));
                    } catch (Exception ignored) {}
                    page.waitForTimeout(2000);

                    // Screenshot to visually verify sidebar after tab click and load
                    page.screenshot(new Page.ScreenshotOptions().setPath(java.nio.file.Paths.get("/tmp/fb_cothethanbieet_tab.png")));

                    totalReplies += inspectAndReply(page, cfg);
                } catch (Exception e) {
                    log.warn("[FB-Responder] Scanning 'Có thể bạn biết' tab encountered notice: {}", e.getMessage());
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
                    "  let sidebar = document.querySelector('[role=\"navigation\"], div[aria-label*=\"\u0110o\u1ea1n chat\"], div[aria-label*=\"Tin nh\u1eafn\"], div[aria-label*=\"Chats\"], div[aria-label*=\"Tin nh\u1eafn \u0111ang ch\u1edd\"], div[aria-label*=\"Message requests\"]');" +
                    "  if (sidebar) { sidebar.scrollTop = 0; sidebar.scrollBy(0, 400); }" +
                    "}");
        } catch (Exception ignored) {}

        // Wait for sidebar conversation links to finish hydrating in React DOM
        try {
            page.waitForSelector("a[href*='/messages/t/'], a[href*='/messages/requests/t/'], a[href*='/messages/requests/']",
                    new Page.WaitForSelectorOptions().setTimeout(5000));
        } catch (Exception ignored) {}
        page.waitForTimeout(1500);

        // Query all DM + E2EE + Message Requests + Spam conversation items (links or unlinked cards) from document and sidebar.
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> threadItems = (List<Map<String, Object>>) page.evaluate("() => {" +
                "  let conversationItems = [];" +
                "  let seenKeys = new Set();" +
                "  let rootUrls = ['/messages/', '/messages/t/', '/messages/requests/', '/messages/requests/spam/', '/messages/e2ee/requests/', '/messages/e2ee/requests/spam/'];" +
                "  let allLinks = Array.from(document.querySelectorAll('a[href*=\"/messages/t/\"], a[href*=\"/messages/e2ee/t/\"], a[href*=\"/messages/requests/t/\"], a[href*=\"/messages/e2ee/requests/t/\"], a[href*=\"/messages/read/\"]'));" +
                "  allLinks.forEach(a => {" +
                "    let href = a.href || '';" +
                "    if (href && !rootUrls.some(r => href.endsWith(r) || href.endsWith(r.slice(0, -1)))) {" +
                "      if (!seenKeys.has(href)) {" +
                "        seenKeys.add(href);" +
                "        conversationItems.push({ href: href, isLink: true, text: (a.innerText || '').substring(0, 40) });" +
                "      }" +
                "    }" +
                "  });" +
                "  let main = document.querySelector('[role=\"main\"]');" +
                "  let mainLeft = main ? main.getBoundingClientRect().left : 380;" +
                "  let items = Array.from(document.querySelectorAll('[role=\"row\"], [role=\"button\"]'));" +
                "  items.forEach((el, idx) => {" +
                "    let rect = el.getBoundingClientRect();" +
                "    if (rect.width > 50 && rect.height > 18 && rect.left < mainLeft - 20 && rect.top > 80 && rect.top < 900) {" +
                "      let txt = (el.innerText || '').trim();" +
                "      let a = el.querySelector('a[href*=\"/messages/\"]');" +
                "      let href = a ? a.href : null;" +
                "      if (href && rootUrls.some(r => href.endsWith(r) || href.endsWith(r.slice(0, -1)))) href = null;" +
                "      let key = href || (txt.length > 5 ? txt.substring(0, 30) : null);" +
                "      if (key && !seenKeys.has(key)) {" +
                "        seenKeys.add(key);" +
                "        let lower = txt.toLowerCase();" +
                "        if (!lower.includes('c\u00f3 th\u1ec3 b\u1ea1n bi\u1ebft') && !lower.includes('spam') && !lower.includes('xem t\u1ea5t c\u1ea3') && !lower.includes('tin nh\u1eafn \u0111ang ch\u1edd') && !lower.includes('messenger')) {" +
                "          conversationItems.push({ href: href, isLink: !!href, index: idx, text: txt.substring(0, 40) });" +
                "        }" +
                "      }" +
                "    }" +
                "  });" +
                "  return conversationItems;" +
                "}");

        Object diagItems = page.evaluate("() => {" +
                "  let allLinks = Array.from(document.querySelectorAll('a[href*=\"/messages/\"]'));" +
                "  return JSON.stringify(allLinks.map(a => ({ href: a.href, text: (a.innerText || '').replace(/\\n/g, ' ').substring(0, 40) })).slice(0, 10));" +
                "}");
        log.info("[FB-Responder] Sidebar Items Diag for '{}': {}", page.url(), diagItems);

        log.info("[FB-Responder] Found {} conversation items in sidebar.", threadItems != null ? threadItems.size() : 0);

        if (threadItems == null || threadItems.isEmpty()) {
            // Take a diagnostic screenshot + dump ALL anchor links to understand what Facebook rendered
            try {
                page.screenshot(new Page.ScreenshotOptions().setPath(java.nio.file.Paths.get("/tmp/fb_e2ee_diag.png")));
                Object domDiag = page.evaluate("() => {" +
                        "  let allA = Array.from(document.querySelectorAll('a[href]')).map(a => ({ href: a.href, text: (a.innerText||'').substring(0,40) }));" +
                        "  let url = window.location.href;" +
                        "  let title = document.title;" +
                        "  let bodySnippet = (document.body.innerText || '').substring(0, 300);" +
                        "  return JSON.stringify({ url, title, bodySnippet, linkCount: allA.length, links: allA.slice(0, 25) });" +
                        "}");
                log.warn("[FB-Responder] No thread items. Full DOM diag for '{}': {}", page.url(), domDiag);
            } catch (Exception ignored) {}
            return 0;
        }

        // Scan up to 20 threads to reach past group chats at the top of the inbox
        int maxCheck = Math.min(threadItems.size(), 20);
        for (int i = 0; i < maxCheck; i++) {
            try {
                Map<String, Object> item = threadItems.get(i);
                if (item == null) continue;

                boolean isLink = Boolean.TRUE.equals(item.get("isLink"));
                String href = (String) item.get("href");

                if (isLink && href != null && !href.isBlank()) {
                    try {
                        page.navigate(href, new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(12000));
                    } catch (Exception e) {
                        log.warn("[FB-Responder] Navigation to '{}' failed/timed out: {}", href, e.getMessage());
                    }
                } else {
                    Number rowIdxNum = (Number) item.get("rowIndex");
                    if (rowIdxNum != null) {
                        int rIdx = rowIdxNum.intValue();
                        page.evaluate("(idx) => {" +
                                "  let rows = Array.from(document.querySelectorAll('[role=\"navigation\"] [role=\"row\"], [role=\"navigation\"] [role=\"button\"]'));" +
                                "  if (rows[idx]) rows[idx].click();" +
                                "}", rIdx);
                    }
                }

                // Wait for message bubbles to finish mounting in DOM (do NOT include header, which mounts immediately)
                try {
                    page.waitForSelector("[role='main'] [role='grid'], [role='main'] [role='list'], [role='main'] [role='log'], [role='main'] div[dir='auto']",
                            new Page.WaitForSelectorOptions().setTimeout(6000));
                } catch (Exception ignored) {}

                // Wait for E2EE decryption/loading spinner to clear
                try {
                    page.waitForFunction("() => {" +
                            "  let main = document.querySelector('[role=\"main\"]') || document.querySelector('[role=\"region\"]');" +
                            "  if (!main) return true;" +
                            "  let spinner = main.querySelector('[role=\"progressbar\"], [aria-busy=\"true\"], svg[aria-label*=\"Đang tải\"], svg[aria-label*=\"Loading\"]');" +
                            "  return !spinner;" +
                            "}", new Page.WaitForFunctionOptions().setTimeout(10000));
                } catch (Exception ignored) {}
                page.waitForTimeout(1500);

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

                String threadUrl = page.url();
                boolean isRequestThread = threadUrl.contains("/messages/requests/")
                        || threadUrl.contains("/messages/e2ee/requests/");

                // ── STEP 1: Accept (for request threads only) ────────────────────────────
                // E2EE and regular request threads hide all message bubbles behind the Accept gate.
                // Counting BEFORE accept always returns 0, so we MUST accept first.
                boolean wasAccepted = false;
                if (isRequestThread) {
                    try {
                        // Wait for the page to stabilize (loading spinner gone) before looking for the Accept button.
                        // Facebook renders the Accept UI asynchronously; clicking too early finds nothing.
                        try {
                            page.waitForFunction("() => !document.querySelector('[aria-busy=\"true\"], [data-visualcompletion=\"loading-state\"]')",
                                    new Page.WaitForFunctionOptions().setTimeout(8000));
                        } catch (Exception ignored) {}
                        page.waitForTimeout(2000); // additional buffer for React hydration

                        page.screenshot(new Page.ScreenshotOptions()
                                .setPath(java.nio.file.Paths.get("/tmp/fb_before_accept.png")));
                        log.info("[FB-Responder] Request thread detected for '{}'. Attempting Accept...", senderName);

                        // Strategy 1: Find button/div[role=button] whose textContent contains "Chấp nhận" or "Accept".
                        // Facebook renders text inside deeply nested React spans — use textContent, not innerText on leaves.
                        Boolean accepted = (Boolean) page.evaluate("() => {" +
                                "  const ACCEPT_TEXT = ['Ch\u1ea5p nh\u1eadn', 'Accept', 'OK'];" +
                                "  let candidates = Array.from(document.querySelectorAll('div[role=\"button\"], button, a[role=\"button\"]'));" +
                                "  let btn = candidates.find(el => {" +
                                "    let t = (el.textContent || '').trim();" +
                                "    return ACCEPT_TEXT.some(a => t === a || t.startsWith(a));" +
                                "  });" +
                                // Strategy 2: broader innerText search on any element
                                "  if (!btn) {" +
                                "    btn = Array.from(document.querySelectorAll('*')).find(el => {" +
                                "      let t = (el.innerText || el.textContent || '').trim();" +
                                "      return ACCEPT_TEXT.includes(t) && el.offsetParent !== null;" +
                                "    });" +
                                "  }" +
                                // Strategy 3: aria-label
                                "  if (!btn) {" +
                                "    btn = document.querySelector('[aria-label=\"Ch\u1ea5p nh\u1eadn\"], [aria-label=\"Accept\"]');" +
                                "  }" +
                                "  if (btn) {" +
                                "    btn.scrollIntoView();" +
                                "    btn.click();" +
                                "    return true;" +
                                "  }" +
                                // Diagnostic: log all button texts for debugging
                                "  let diag = candidates.slice(0,20).map(el => (el.textContent||'').trim().substring(0,30));" +
                                "  console.log('FB-Accept-Diag buttons:', JSON.stringify(diag));" +
                                "  return false;" +
                                "}");

                        // Strategy 4: Playwright locator as final fallback
                        if (Boolean.FALSE.equals(accepted)) {
                            try {
                                // Try role=button with name
                                var btn = page.getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("Ch\u1ea5p nh\u1eadn"));
                                if (btn.count() > 0 && btn.first().isVisible()) {
                                    btn.first().click();
                                    accepted = true;
                                }
                            } catch (Exception ex) {}
                        }
                        if (Boolean.FALSE.equals(accepted)) {
                            try {
                                var btn = page.getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("Accept"));
                                if (btn.count() > 0 && btn.first().isVisible()) {
                                    btn.first().click();
                                    accepted = true;
                                }
                            } catch (Exception ex) {}
                        }

                        // Dump DOM diagnostic to log for debugging
                        Object domDump = page.evaluate("() => {" +
                                "  let btns = Array.from(document.querySelectorAll('div[role=\"button\"], button'));" +
                                "  return btns.slice(0,15).map(e => ({ tag: e.tagName, txt: (e.textContent||'').trim().substring(0,40), aria: e.getAttribute('aria-label') }));" +
                                "}");
                        log.info("[FB-Responder] Accept DOM dump for '{}': {}", senderName, domDump);
                        log.info("[FB-Responder] Accept button clicked for '{}': {}", senderName, accepted);
                        wasAccepted = Boolean.TRUE.equals(accepted);

                        if (wasAccepted) {
                            // Wait for Facebook to re-render the full conversation after Accept
                            page.waitForTimeout(4000);
                            page.screenshot(new Page.ScreenshotOptions()
                                    .setPath(java.nio.file.Paths.get("/tmp/fb_after_accept.png")));
                            log.info("[FB-Responder] After-accept screenshot saved. URL: {}", page.url());
                        }
                    } catch (Exception ex) {
                        log.warn("[FB-Responder] Error clicking Accept for '{}': {}", senderName, ex.getMessage());
                    }
                }

                // ── STEP 2: Count unreplied messages ─────────────────────────────────────
                // For request threads: count AFTER accept so all bubbles are visible.
                // For regular DMs: count normally (bubbles always visible).
                int unrepliedCount = countUnrepliedIncomingMessages(page);
                log.info("[FB-Responder] DM with '{}': {} unreplied incoming message(s) (post-accept={}).",
                        senderName, unrepliedCount, wasAccepted);

                // ── STEP 3: Threshold check → reply ──────────────────────────────────────
                // For request threads that were accepted but count=0, use minimum count of 1
                // so we always reply when a user has been accepted (they clearly sent something).
                int effectiveCount = unrepliedCount;
                if (isRequestThread && wasAccepted && effectiveCount < 1) {
                    effectiveCount = 1; // fallback: at minimum 1 message triggered the accept
                    log.info("[FB-Responder] Count=0 after accept for '{}'; using effectiveCount=1.", senderName);
                }

                if (effectiveCount >= cfg.getThreshold()) {
                    log.info("[FB-Responder] Triggering AI Away reply for '{}' (Count: {} >= Threshold: {})",
                            senderName, effectiveCount, cfg.getThreshold());
                    String awayReply = generateAwayMessage(senderName, effectiveCount, cfg.getCustomMessage());
                    boolean sent = sendMessengerReply(page, awayReply);
                    if (sent) {
                        autoRepliesSent++;
                        log.info("[FB-Responder] AUTO-REPLY SENT to '{}': {}", senderName, awayReply);
                        page.screenshot(new Page.ScreenshotOptions()
                                .setPath(java.nio.file.Paths.get("/tmp/fb_reply_sent.png")));
                    }
                } else {
                    log.info("[FB-Responder] '{}' count {} below threshold {}. No reply sent.",
                            senderName, effectiveCount, cfg.getThreshold());
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
            Boolean pinScreenPresent = (Boolean) page.evaluate(
                    "() => {" +
                    "  let dialog = document.querySelector('[role=\"dialog\"]');" +
                    "  if (!dialog) return false;" +
                    "  let t = (dialog.innerText || dialog.textContent || '').toLowerCase();" +
                    "  return t.includes('nh\u1eadp m\u00e3 pin') || t.includes('kh\u00f4i ph\u1ee5c \u0111o\u1ea1n chat') || t.includes('restore') || t.includes('pin');" +
                    "}");

            if (!Boolean.TRUE.equals(pinScreenPresent)) {
                return;
            }

            log.info("[FB-Responder] E2EE PIN modal detected in [role=dialog]. Target PIN: '090325'...");

            // 1. Click specifically on the first input inside [role=dialog] (NOT sidebar search input!)
            Boolean focused = (Boolean) page.evaluate(
                    "() => {" +
                    "  let dialog = document.querySelector('[role=\"dialog\"]');" +
                    "  if (!dialog) return false;" +
                    "  let inputs = Array.from(dialog.querySelectorAll('input'));" +
                    "  if (inputs.length > 0) {" +
                    "    inputs[0].focus();" +
                    "    inputs[0].click();" +
                    "    return true;" +
                    "  }" +
                    "  return false;" +
                    "}");

            page.waitForTimeout(300);

            // 2. Playwright keyboard type "090325" into the focused dialog input
            if (Boolean.TRUE.equals(focused)) {
                page.keyboard().type("090325", new Keyboard.TypeOptions().setDelay(150));
                page.waitForTimeout(500);
                page.keyboard().press("Enter");
            }

            // 3. React Native Setter fallback scoped strictly to [role=dialog] inputs
            Boolean jsFilled = (Boolean) page.evaluate(
                    "() => {" +
                    "  let dialog = document.querySelector('[role=\"dialog\"]');" +
                    "  if (!dialog) return false;" +
                    "  const pin = '090325';" +
                    "  const setReactValue = (input, val) => {" +
                    "    try {" +
                    "      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;" +
                    "      nativeInputValueSetter.call(input, val);" +
                    "    } catch (e) { input.value = val; }" +
                    "    input.dispatchEvent(new Event('input', { bubbles: true }));" +
                    "    input.dispatchEvent(new Event('change', { bubbles: true }));" +
                    "  };" +
                    "  let inputs = Array.from(dialog.querySelectorAll('input'));" +
                    "  if (inputs.length >= 6) {" +
                    "    inputs.slice(0, 6).forEach((inp, idx) => {" +
                    "      inp.focus();" +
                    "      setReactValue(inp, pin[idx] || '0');" +
                    "    });" +
                    "    return true;" +
                    "  } else if (inputs.length > 0) {" +
                    "    let inp = inputs[0];" +
                    "    inp.focus();" +
                    "    setReactValue(inp, pin);" +
                    "    return true;" +
                    "  }" +
                    "  return false;" +
                    "}");

            log.info("[FB-Responder] Dialog PIN 090325 filled (JS: {}). Submitting...", jsFilled);
            page.waitForTimeout(1000);
            page.keyboard().press("Enter");

            // 4. Click any submit/confirm button inside [role=dialog]
            page.evaluate(
                    "() => {" +
                    "  let dialog = document.querySelector('[role=\"dialog\"]');" +
                    "  if (!dialog) return;" +
                    "  let btns = Array.from(dialog.querySelectorAll('div[role=\"button\"], button'));" +
                    "  let sub = btns.find(b => {" +
                    "    let t = (b.textContent || '').trim().toLowerCase();" +
                    "    return t.includes('ti\u1ebfp theo') || t.includes('x\u00e1c nh\u1eadn') || t.includes('restore') || t.includes('continue');" +
                    "  });" +
                    "  if (sub) sub.click();" +
                    "}");

            page.waitForTimeout(4000);
            log.info("[FB-Responder] PIN 090325 dialog submission completed.");
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
                "  let main = document.querySelector('[role=\"main\"]') || document.querySelector('[role=\"region\"]') || document.body;" +

                // Strategy 1: Use Facebook's accessibility aria-labels on message bubble containers.
                // Confirmed patterns from production:
                //   Outgoing: 'tin nhắn do bạn gửi lúc HH:MM: ...'
                //   Outgoing group header: 'lúc HH:MM, bạn: ...'
                //   Incoming individual: 'tin nhắn do [Name] gửi lúc HH:MM: ...'
                //   Incoming group header: 'lúc HH:MM, [Name]: ...'
                "  let bubbles = Array.from(main.querySelectorAll('[aria-label]')).filter(el => {" +
                "    let lbl = (el.getAttribute('aria-label') || '').toLowerCase();" +
                "    return (lbl.startsWith('tin nh\u1eafn do ') && lbl.includes(' g\u1eedi l\u00fac ')) ||" +
                "           /^l\u00fac \\d{1,2}:\\d{2},.+:/.test(lbl);" +
                "  });" +
                "  if (bubbles.length > 0) {" +
                "    let details = [];" +
                "    let count = 0;" +
                "    for (let i = bubbles.length - 1; i >= 0; i--) {" +
                "      let el = bubbles[i];" +
                "      let lbl = (el.getAttribute('aria-label') || '').toLowerCase();" +
                "      let text = (el.innerText || '').trim();" +
                "      let isOut = lbl.startsWith('tin nh\u1eafn do b\u1ea1n') ||" +
                "                  /^l\u00fac \\d{1,2}:\\d{2}, b\u1ea1n:/.test(lbl);" +
                "      details.push({ txt: text.substring(0, 40), isOut, lbl: lbl.substring(0, 50) });" +
                "      if (isOut) break;" +
                "      count++;" +
                "    }" +
                "    return JSON.stringify({ count, totalRows: bubbles.length, strategy: 'aria-label', details: details.slice(0, 10) });" +
                "  }" +

                // Strategy 2: Fallback — scope to chat grid/list container to exclude right info panel.
                // The right panel (Quyền riêng tư, Tắt thông báo...) contains dir=auto divs that caused
                // false positives when querying the entire main element.
                "  let chatScope = main.querySelector('[role=\"grid\"], [role=\"list\"], [role=\"log\"]') || main;" +
                "  let editables = Array.from(chatScope.querySelectorAll('[contenteditable=\"true\"]'));" +
                "  let allAuto = Array.from(chatScope.querySelectorAll('div[dir=\"auto\"]'));" +
                "  if (allAuto.length === 0) allAuto = Array.from(chatScope.querySelectorAll('span[dir=\"auto\"]'));" +
                "  let rows = allAuto.filter(el => {" +
                "    if (el.closest('[role=\"navigation\"], [role=\"complementary\"], aside')) return false;" +
                "    let txt = (el.innerText || '').trim();" +
                "    if (!txt || txt.length === 0) return false;" +
                "    if (editables.some(ed => ed.contains(el))) return false;" +
                "    if (allAuto.some(other => other !== el && other.contains(el))) return false;" +
                "    return true;" +
                "  });" +
                "  function isOutgoing(el) {" +
                "    let cur = el;" +
                "    for (let depth = 0; depth < 10; depth++) {" +
                "      if (!cur || cur === main) break;" +
                "      let lbl = (cur.getAttribute('aria-label') || '').toLowerCase();" +
                "      if (lbl.startsWith('tin nh\u1eafn do b\u1ea1n') || lbl.startsWith('b\u1ea1n l\u00fac')) return true;" +
                "      cur = cur.parentElement;" +
                "    }" +
                "    return false;" +
                "  }" +
                "  let details = [];" +
                "  let count = 0;" +
                "  for (let i = rows.length - 1; i >= 0; i--) {" +
                "    let row = rows[i];" +
                "    let text = (row.innerText || '').trim();" +
                "    if (!text) continue;" +
                "    let lowerText = text.toLowerCase();" +
                "    let isNotice = lowerText.includes('mu\u1ed1n g\u1eedi tin nh\u1eafn') ||" +
                "                   lowerText.includes('m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i') ||" +
                "                   lowerText.includes('t\u00ecm hi\u1ec3u th\u00eam') ||" +
                "                   lowerText.includes('n\u1ebfu b\u1ea1n ch\u1ea5p nh\u1eadn');" +
                "    let isOut = isOutgoing(row);" +
                "    details.push({ txt: text.substring(0, 30), isNotice, isOut });" +
                "    if (isNotice) continue;" +
                "    if (isOut) break;" +
                "    count++;" +
                "  }" +
                "  return JSON.stringify({ count, totalRows: rows.length, strategy: 'dir-auto', details: details.slice(0, 10) });" +
                "}");

        log.info("[FB-Responder] Unreplied Count Diag for '{}': {}", page.url(), countResult);

        try {
            if (countResult != null) {
                com.fasterxml.jackson.databind.JsonNode node = new com.fasterxml.jackson.databind.ObjectMapper().readTree(countResult.toString());
                int totalRows = node.has("totalRows") ? node.get("totalRows").asInt() : 0;
                int count = node.has("count") ? node.get("count").asInt() : 0;

                // Retry once if totalRows is 0 (E2EE React component mounted slightly late)
                if (totalRows == 0) {
                    page.waitForTimeout(3000);
                    Object retryResult = page.evaluate("() => {" +
                            "  let main = document.querySelector('[role=\"main\"]') || document.querySelector('[role=\"region\"]') || document.body;" +
                            "  let bubbles = Array.from(main.querySelectorAll('[aria-label]')).filter(el => {" +
                            "    let lbl = (el.getAttribute('aria-label') || '').toLowerCase();" +
                            "    return (lbl.startsWith('tin nh\u1eafn do ') && lbl.includes(' g\u1eedi l\u00fac ')) || /^l\u00fac \\d{1,2}:\\d{2},.+:/.test(lbl);" +
                            "  });" +
                            "  if (bubbles.length > 0) {" +
                            "    let count = 0;" +
                            "    for (let i = bubbles.length - 1; i >= 0; i--) {" +
                            "      let lbl = (bubbles[i].getAttribute('aria-label') || '').toLowerCase();" +
                            "      if (lbl.startsWith('tin nh\u1eafn do b\u1ea1n') || /^l\u00fac \\d{1,2}:\\d{2}, b\u1ea1n:/.test(lbl)) break;" +
                            "      count++;" +
                            "    }" +
                            "    return JSON.stringify({ count, totalRows: bubbles.length });" +
                            "  }" +
                            "  let chatScope = main.querySelector('[role=\"grid\"], [role=\"list\"], [role=\"log\"]') || main;" +
                            "  let editables = Array.from(chatScope.querySelectorAll('[contenteditable=\"true\"]'));" +
                            "  let allAuto = Array.from(chatScope.querySelectorAll('div[dir=\"auto\"]'));" +
                            "  if (allAuto.length === 0) allAuto = Array.from(chatScope.querySelectorAll('span[dir=\"auto\"]'));" +
                            "  let rows = allAuto.filter(el => {" +
                            "    if (el.closest('[role=\"navigation\"], [role=\"complementary\"], aside')) return false;" +
                            "    let txt = (el.innerText || '').trim();" +
                            "    if (!txt || txt.length === 0) return false;" +
                            "    if (editables.some(ed => ed.contains(el))) return false;" +
                            "    if (allAuto.some(other => other !== el && other.contains(el))) return false;" +
                            "    return true;" +
                            "  });" +
                            "  let count = 0;" +
                            "  for (let i = rows.length - 1; i >= 0; i--) {" +
                            "    let text = (rows[i].innerText || '').trim().toLowerCase();" +
                            "    if (text.includes('m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i') || text.includes('t\u00ecm hi\u1ec3u th\u00eam')) continue;" +
                            "    count++;" +
                            "  }" +
                            "  return JSON.stringify({ count, totalRows: rows.length });" +
                            "}");
                    if (retryResult != null) {
                        com.fasterxml.jackson.databind.JsonNode retryNode = new com.fasterxml.jackson.databind.ObjectMapper().readTree(retryResult.toString());
                        log.info("[FB-Responder] Count retry result for '{}': {}", page.url(), retryResult);
                        if (retryNode.has("count")) return retryNode.get("count").asInt();
                    }
                }

                return count;
            }
        } catch (Exception ignored) {}
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
            // Find the bottom-most LEAF-NODE contenteditable input box inside [role='main'].
            // Wrapper containers (like [aria-label*='Tin nhắn trong cuộc trò chuyện']) contain nested editables,
            // so filtering for leaf nodes (elements with 0 child editables) selects the actual text input box.
            // NOTE: Step 0 (clicking the Accept button) is intentionally handled UPSTREAM in inspectAndReply,
            // with a 4-second wait for DOM to re-render before this function is called. Having it here too
            // caused a DOM reset mid-flow that triggered the Lexical reconciler twice, producing duplicate text.
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

            // Step 1: Click, focus, and CLEAR the editor to ensure a clean slate.
            // Clearing is critical — if the editor has residual state (e.g., from a failed previous scan),
            // keyboard.type() would APPEND to existing content, producing garbage messages.
            try {
                targetInput.click();
                targetInput.focus();
            } catch (Exception ignored) {}
            page.waitForTimeout(300);
            page.keyboard().press("Control+A");
            page.waitForTimeout(100);
            page.keyboard().press("Delete");
            page.waitForTimeout(200);

            // Step 2: Type text using keyboard.type() — the single reliable method for Facebook's Lexical editor.
            //
            // WHY NOT execCommand + keyboard.insertText combo:
            //   - execCommand('insertText') dispatches text into the DOM synchronously.
            //   - keyboard.insertText() does the same via Playwright's CDP layer.
            //   - Using BOTH creates a race: execCommand fires Lexical's beforeinput handler which queues
            //     a state update, then keyboard.insertText fires AGAIN before Lexical flushes, resulting
            //     in the same text being committed twice → duplicate message.
            //
            // keyboard.type() sends individual keydown/keypress/keyup events per character — matching
            // exactly what a human types. Lexical and DraftJS both handle this correctly without duplication.
            page.keyboard().type(text, new Keyboard.TypeOptions().setDelay(15));
            page.waitForTimeout(500);

            // Verify text is now present in editor before submitting
            String typedText = (String) targetInput.evaluate("el => (el.innerText || '').trim()");
            log.info("[FB-Responder] Editor content before submit: '{}'", typedText != null && typedText.length() > 30 ? typedText.substring(0, 30) : typedText);

            // If text is empty even after typing — last resort: use execCommand
            if (typedText == null || typedText.isEmpty()) {
                log.warn("[FB-Responder] keyboard.type() did not populate text. Falling back to execCommand...");
                targetInput.evaluate("(el, txt) => { el.focus(); document.execCommand('insertText', false, txt); }", text);
                page.waitForTimeout(400);
                typedText = (String) targetInput.evaluate("el => (el.innerText || '').trim()");
            }

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

    public Map<String, String> captureChatScreenshots() {
        FacebookConfig cfg = configRepository.getConfig().orElse(null);
        if (cfg == null || cfg.getCookiesJson() == null || cfg.getCookiesJson().isBlank()) {
            return Map.of("status", "error", "message", "No cookies configured");
        }

        try (Playwright playwright = Playwright.create()) {
            BrowserType.LaunchOptions options = new BrowserType.LaunchOptions().setHeadless(true);
            if (Paths.get("/usr/bin/chromium").toFile().exists()) {
                options.setExecutablePath(Paths.get("/usr/bin/chromium"));
            } else if (Paths.get("/usr/bin/chromium-browser").toFile().exists()) {
                options.setExecutablePath(Paths.get("/usr/bin/chromium-browser"));
            }

            Browser browser = playwright.chromium().launch(options);
            BrowserContext context = browser.newContext(new Browser.NewContextOptions().setViewportSize(1920, 1080));
            applyCookies(context, cfg.getCookiesJson());
            Page page = context.newPage();

            // First navigate to root inbox to hydrate React state
            page.navigate("https://www.facebook.com/messages/", new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(30000));
            page.waitForTimeout(5000);

            // Chat 1: Trần Văn Mạnh
            try {
                page.navigate("https://www.facebook.com/messages/t/100045592363397/", new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(30000));
                page.waitForTimeout(5000);
                handleE2eePinScreen(page);
                page.waitForTimeout(2000);
                page.screenshot(new Page.ScreenshotOptions().setPath(Paths.get("/tmp/chat_tran_van_manh.png")));
            } catch (Exception ex) {
                log.warn("[FB-Screenshot] Failed chat 1: {}", ex.getMessage());
            }

            // Chat 2: Mạnh Văn Trần
            try {
                page.navigate("https://www.facebook.com/messages/e2ee/t/2127577941122457/", new Page.NavigateOptions().setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(30000));
                page.waitForTimeout(6000);
                handleE2eePinScreen(page);
                page.waitForTimeout(2000);
                page.screenshot(new Page.ScreenshotOptions().setPath(Paths.get("/tmp/chat_manh_van_tran.png")));
            } catch (Exception ex) {
                log.warn("[FB-Screenshot] Failed chat 2: {}", ex.getMessage());
            }

            browser.close();
            return Map.of("status", "success", "message", "Captured screenshots for both chats");
        } catch (Exception e) {
            log.error("[FB-Screenshot] Failed to capture chat screenshots: {}", e.getMessage(), e);
            return Map.of("status", "error", "message", e.getMessage());
        }
    }
}

