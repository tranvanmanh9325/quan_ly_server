import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

from playwright.async_api import async_playwright, BrowserContext, Page
from app.config import settings
from app.core.db import get_db_connection, get_db_dict_cursor

logger = logging.getLogger("app.services.vnc_manager")

# Maximum idle time allowed before auto-reaping the VNC session (10 minutes)
MAX_IDLE_SECONDS = 600

# Consistent Desktop User-Agent to prevent anti-bot session invalidation
DESKTOP_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class VncManager:
    """
    High-Performance, Multi-Platform & Persistent VNC Browser Manager:
    1. Spawns Xvfb virtual display with minimal memory footprint on :99 (1280x800x16 in L3 Cache).
    2. Spawns Openbox window manager with borderless maximized window policy.
    3. Spawns x11vnc with multi-threaded event-driven capture and WAN latency pacing.
    4. Spawns websockify gateway on port 6080 serving noVNC.
    5. Platform Profile Isolation: Separates /app/browser_data/tiktok and /app/browser_data/facebook.
    6. Cookie Pre-Injection: Restores authenticated cookies from PostgreSQL upon startup.
    7. Guaranteed Auto-Save: Extracts and persists cookies across ALL exit paths (X button, Save button, timeout).
    8. Anti-Bot Stealth Layer: Neutralizes navigator.webdriver and provides consistent Chrome environment.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._display = ":99"
        self._xvfb_proc: Optional[subprocess.Popen] = None
        self._openbox_proc: Optional[subprocess.Popen] = None
        self._x11vnc_proc: Optional[subprocess.Popen] = None
        self._websockify_proc: Optional[subprocess.Popen] = None
        
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_running = False
        self._current_platform = "facebook"
        self._last_active_time = 0.0
        self._watchdog_task: Optional[asyncio.Task] = None

    def is_running(self) -> bool:
        if not self._is_running or not self._context:
            return False
        if self._xvfb_proc and self._xvfb_proc.poll() is not None:
            return False
        if self._websockify_proc and self._websockify_proc.poll() is not None:
            return False
        if self._x11vnc_proc and self._x11vnc_proc.poll() is not None:
            return False
        return True

    def touch(self):
        """Records user activity / heartbeat to prevent session auto-reaping."""
        self._last_active_time = time.time()

    async def check_ready(self) -> bool:
        """Returns True if VNC websockify port 6080 and x11vnc 5900 are listening and page is alive."""
        if not self.is_running() or not self._page:
            return False
        if not self._check_port_listening(6080) or not self._check_port_listening(5900):
            return False
        self.touch()
        return True

    def _get_profile_dir(self, platform: str) -> str:
        """Returns isolated user data directory for each platform."""
        plat = "tiktok" if platform.lower() == "tiktok" else "facebook"
        target = os.path.join("/app/browser_data", plat)
        os.makedirs(target, exist_ok=True)
        return target

    async def _idle_watchdog(self):
        """Background daemon that auto-reaps the session if no activity for MAX_IDLE_SECONDS."""
        logger.info("[VNC-Manager] Idle watchdog started (timeout: %ds).", MAX_IDLE_SECONDS)
        try:
            while self._is_running:
                await asyncio.sleep(15)
                if self._is_running and (time.time() - self._last_active_time > MAX_IDLE_SECONDS):
                    logger.warning("[VNC-Manager] Session idle for >%ds; auto-reaping resources with auto-save...", MAX_IDLE_SECONDS)
                    await self.close_session()
                    break
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _check_port_listening(port: int, host: str = "127.0.0.1") -> bool:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    async def _inject_cookies_from_db(self, context: BrowserContext, platform: str) -> int:
        """Pre-injects validated cookies from PostgreSQL database into the browser context."""
        plat = "tiktok" if platform.lower() == "tiktok" else "facebook"
        try:
            async with get_db_dict_cursor() as cur:
                if plat == "tiktok":
                    await cur.execute("SELECT cookies_json FROM tiktok_config WHERE id = 1 LIMIT 1")
                else:
                    await cur.execute("SELECT cookies_json FROM facebook_config WHERE id = 1 LIMIT 1")
                row = await cur.fetchone()
                if not row or not row.get("cookies_json"):
                    return 0

                cookies_raw = row["cookies_json"]
                if not cookies_raw or cookies_raw.strip() in ("", "[]"):
                    return 0

                cookies_list = json.loads(cookies_raw)
                if not isinstance(cookies_list, list):
                    return 0

                parsed = []
                for c in cookies_list:
                    if not isinstance(c, dict):
                        continue
                    name = c.get("name")
                    value = c.get("value")
                    domain = c.get("domain", "")
                    if not name or not value or not domain:
                        continue

                    # Filter domains according to platform
                    if plat == "tiktok":
                        if not any(k in domain for k in ("tiktok", "byteoversea", "ibytedtos")):
                            continue
                    else:
                        if not any(k in domain for k in ("facebook", "messenger")):
                            continue

                    raw_ss = str(c.get("sameSite", "Lax") or "Lax").lower()
                    if "strict" in raw_ss:
                        same_site = "Strict"
                    elif "none" in raw_ss or "no_restriction" in raw_ss:
                        same_site = "None"
                    else:
                        same_site = "Lax"

                    cookie_entry = {
                        "name": str(name),
                        "value": str(value),
                        "domain": str(domain),
                        "path": str(c.get("path", "/")),
                        "secure": bool(c.get("secure", True)),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "sameSite": same_site,
                    }
                    if c.get("expires") and float(c["expires"]) > 0:
                        cookie_entry["expires"] = float(c["expires"])

                    parsed.append(cookie_entry)

                if parsed:
                    await context.add_cookies(parsed)
                    logger.info("[VNC-Manager] Pre-injected %d verified %s cookies from DB into browser context.", len(parsed), plat.upper())
                    return len(parsed)
        except Exception as e:
            logger.warning("[VNC-Manager] Error pre-injecting cookies for %s: %s", plat, e)
        return 0

    async def _extract_and_save_session(self, platform: Optional[str] = None) -> dict:
        """Extracts cookies from active context, filters by domain, and persists to PostgreSQL."""
        if not self._context:
            return {"status": "skipped", "message": "No active context to save."}

        plat = "tiktok" if (platform or self._current_platform).lower() == "tiktok" else "facebook"
        try:
            all_cookies = await self._context.cookies()
            if not all_cookies:
                logger.info("[VNC-Manager] No cookies found in context for %s.", plat)
                return {"status": "empty", "message": "Không có cookies nào trong phiên."}

            # Filter domain to prevent cross-contamination
            filtered_cookies = []
            has_auth_token = False
            for c in all_cookies:
                domain = c.get("domain", "")
                name = c.get("name", "")
                if plat == "tiktok":
                    if any(k in domain for k in ("tiktok", "byteoversea", "ibytedtos")):
                        filtered_cookies.append(c)
                        if name in ("sessionid", "sessionid_ss", "sid_tt", "uid_tt"):
                            has_auth_token = True
                else:
                    if any(k in domain for k in ("facebook", "messenger")):
                        filtered_cookies.append(c)
                        if name in ("c_user", "xs", "datr"):
                            has_auth_token = True

            to_save = filtered_cookies if filtered_cookies else all_cookies
            cookies_json = json.dumps(to_save)

            auth_note = " (Xác thực đăng nhập thành công ✓)" if has_auth_token else " (Chưa phát hiện token đăng nhập)"
            status_text = f"Đã lưu phiên {plat.upper()} ({len(to_save)} cookies){auth_note}"

            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    if plat == "tiktok":
                        await cur.execute("""
                            INSERT INTO tiktok_config (id, cookies_json, last_status, enabled, streak_enabled, updated_at)
                            VALUES (1, %s, %s, true, true, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                cookies_json = EXCLUDED.cookies_json,
                                last_status = EXCLUDED.last_status,
                                updated_at = NOW()
                        """, (cookies_json, status_text))
                    else:
                        await cur.execute("""
                            INSERT INTO facebook_config (id, cookies_json, last_status, enabled, threshold, cooldown_minutes, custom_message, created_at, updated_at)
                            VALUES (1, %s, %s, true, 3, 2, '', NOW(), NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                cookies_json = EXCLUDED.cookies_json,
                                last_status = EXCLUDED.last_status,
                                updated_at = NOW()
                        """, (cookies_json, status_text))

            logger.info("[VNC-Manager] %s", status_text)
            return {"status": "success", "message": status_text, "cookies_count": len(to_save), "authenticated": has_auth_token}

        except Exception as e:
            logger.error("[VNC-Manager] Failed to extract & save session for %s: %s", plat, e)
            return {"status": "error", "message": f"Lỗi lưu phiên: {e}"}

    async def start_session(self, target_url: Optional[str] = None, platform: str = "facebook") -> dict:
        """Starts the full X11 + VNC + Chromium interactive environment with isolated profiles."""
        async with self._lock:
            self._current_platform = platform.lower()
            if not target_url:
                if self._current_platform == "tiktok":
                    target_url = "https://www.tiktok.com/messages"
                else:
                    target_url = "https://www.facebook.com/messages/"

            # If session is truly active and ports are open, navigate to target and return success
            if self.is_running() and self._check_port_listening(6080) and self._check_port_listening(5900):
                self.touch()
                if self._page:
                    asyncio.create_task(self._safe_navigate(self._page, target_url))
                logger.info("[VNC-Manager] Session already running; navigated to %s.", target_url)
                return {"status": "success", "message": f"Phiên VNC đang hoạt động ({platform.upper()})."}

            # If state was inconsistent or processes died, clean up completely first
            if self._is_running or self._context or self._xvfb_proc:
                logger.info("[VNC-Manager] Cleaning up inconsistent session before fresh start...")
                await self._cleanup_internal(skip_save=True)

            logger.info("[VNC-Manager] Starting optimized interactive VNC browser session for %s...", platform)
            try:
                # 1. Kill any stale Xvfb / x11vnc / websockify instances & clean locks
                self._kill_stale_processes()
                await asyncio.sleep(0.3)

                # 2. Start Xvfb
                self._xvfb_proc = subprocess.Popen(
                    [
                        "Xvfb", self._display,
                        "-screen", "0", "1280x800x16",
                        "-dpi", "96",
                        "-ac", "-nolisten", "tcp", "-noreset",
                        "+extension", "GLX", "+extension", "RANDR", "+extension", "RENDER",
                        "+extension", "DAMAGE", "+extension", "XFIXES"
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(0.5)

                # 3. Start Openbox
                openbox_dir = os.path.expanduser("~/.config/openbox")
                os.makedirs(openbox_dir, exist_ok=True)
                rc_path = os.path.join(openbox_dir, "rc.xml")
                if not os.path.exists(rc_path):
                    with open(rc_path, "w", encoding="utf-8") as f:
                        f.write('<?xml version="1.0" encoding="UTF-8"?><openbox_config xmlns="http://openbox.org/3.4/rc"><applications><application class="*"><decor>no</decor><maximized>yes</maximized></application></applications></openbox_config>')

                env_vars: dict[str, Union[str, float, bool]] = dict(os.environ)
                env_vars["DISPLAY"] = self._display
                self._openbox_proc = subprocess.Popen(
                    ["openbox", "--sm-disable"],
                    env=dict(os.environ, DISPLAY=self._display),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(0.3)

                # 4. Start x11vnc
                self._x11vnc_proc = subprocess.Popen(
                    [
                        "x11vnc",
                        "-display", self._display,
                        "-forever", "-nopw", "-shared",
                        "-rfbport", "5900",
                        "-listen", "127.0.0.1",
                        "-xdamage", "-cursor", "most", "-repeat",
                        "-defer", "20", "-wait", "15",
                        "-wirecopyrect", "-xwarppointer",
                        "-noxrecord", "-capslock", "-nowf", "-threads"
                    ],
                    env=dict(os.environ, DISPLAY=self._display),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                for _ in range(25):
                    await asyncio.sleep(0.2)
                    if self._check_port_listening(5900):
                        break

                # 5. Start websockify
                novnc_web = "/usr/share/novnc" if os.path.exists("/usr/share/novnc") else None
                websockify_cmd = ["websockify"]
                if novnc_web:
                    websockify_cmd.extend(["--web", novnc_web])
                websockify_cmd.extend(["--heartbeat", "30", "6080", "127.0.0.1:5900"])
                self._websockify_proc = subprocess.Popen(websockify_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                for _ in range(25):
                    await asyncio.sleep(0.2)
                    if self._check_port_listening(6080):
                        break

                # 6. Launch Playwright
                profile_dir = self._get_profile_dir(self._current_platform)
                for item in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    lock_path = os.path.join(profile_dir, item)
                    if os.path.islink(lock_path) or os.path.exists(lock_path):
                        try: os.remove(lock_path)
                        except Exception: pass

                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    channel="chromium",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox", "--disable-setuid-sandbox", "--disable-infobars",
                        "--window-position=0,0", "--window-size=1280,800", "--start-maximized",
                        "--disable-default-apps", "--disable-extensions", "--no-first-run",
                        "--no-default-browser-check", "--disable-session-crashed-bubble",
                        "--hide-crash-restore-bubble", "--enable-fast-unload",
                        "--disable-smooth-scrolling", "--autoplay-policy=user-gesture-required",
                        "--mute-audio", "--disable-background-media-suspend=false",
                        "--disable-gpu", "--disable-gpu-rasterization", "--disable-software-rasterizer",
                        "--force-device-scale-factor=1", "--renderer-process-limit=2",
                        "--js-flags=--max-old-space-size=512",
                        "--disable-features=Translate,OptimizationHints,MediaRouter,CalculateNativeWinOcclusion,InterestFeedContentSuggestions",
                        "--disable-background-networking", "--disable-component-update", "--disable-domain-reliability",
                    ],
                    user_agent=DESKTOP_USER_AGENT,
                    viewport=None,
                    env=env_vars,
                )

                await self._setup_media_neutralizer(self._context)

                # 7. Inject cookies
                injected_count = await self._inject_cookies_from_db(self._context, self._current_platform)
                logger.info("[VNC-Manager] Pre-navigation cookie injection finished (%d cookies loaded).", injected_count)

                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                asyncio.create_task(self._safe_navigate(self._page, target_url))

                self._is_running = True
                self.touch()

                if self._watchdog_task and not self._watchdog_task.done():
                    self._watchdog_task.cancel()
                self._watchdog_task = asyncio.create_task(self._idle_watchdog())

                logger.info("[VNC-Manager] Session successfully launched for %s.", platform.upper())
                return {"status": "success", "message": f"Trình duyệt Server ({platform.upper()}) đã khởi động thành công."}

            except Exception as e:
                logger.error("[VNC-Manager] Error starting session: %s", e, exc_info=True)
                await self._cleanup_internal(skip_save=True)
                return {"status": "error", "message": f"Lỗi khởi động VNC Session: {str(e)}"}

    async def _setup_media_neutralizer(self, context: BrowserContext):
        """Injects JS to neutralize HTMLMediaElement and hide video elements + stealth bot neutralization."""
        try:
            script = """
            (() => {
                try {
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = window.chrome || { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
                } catch(e) {}
                const neutralize = (el) => {
                    if (!el) return;
                    if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') {
                        try { el.muted = true; el.preload = 'none'; el.removeAttribute('src'); el.style.display = 'none'; el.pause(); } catch(e) {}
                    }
                    if (el.querySelectorAll) el.querySelectorAll('video, audio').forEach(neutralize);
                };
                const injectCss = () => {
                    if (document.getElementById('__vnc_perf_guard')) return;
                    const st = document.createElement('style');
                    st.id = '__vnc_perf_guard';
                    st.innerHTML = `video, audio { display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }`;
                    (document.head || document.documentElement).appendChild(st);
                };
                if (document.head || document.documentElement) injectCss();
                try {
                    const obs = new MutationObserver((muts) => {
                        for (const m of muts) m.addedNodes.forEach(neutralize);
                    });
                    obs.observe(document.documentElement, { childList: true, subtree: true });
                } catch(e) {}
            })();
            """
            await context.add_init_script(script)
            media_patterns = ["**/*.mp4*", "**/*.m4s*", "**/*.webm*", "**/*.ts*", "**/*.m3u8*"]
            for pattern in media_patterns:
                try: await context.route(pattern, lambda route: route.abort("blockedbyclient"))
                except Exception: pass
            logger.info("[VNC-Manager] Native stealth & video neutralization active.")
        except Exception as e:
            logger.warning("[VNC-Manager] Could not setup media neutralizer: %s", e)

    async def _safe_navigate(self, page: Page, url: str):
        try:
            logger.info("[VNC-Manager] Navigating to %s...", url)
            await page.goto(url, wait_until="commit", timeout=45000)
        except Exception as e:
            logger.warning("[VNC-Manager] Navigation to %s failed: %s", url, e)

    async def save_session(self, platform: Optional[str] = None) -> dict:
        """Extracts cookies, saves to PostgreSQL, and cleanly shuts down."""
        async with self._lock:
            target_platform = platform or self._current_platform or "facebook"
            result = await self._extract_and_save_session(target_platform)
            await self._cleanup_internal(skip_save=True)
            return result

    async def close_session(self):
        """Closes browser with guaranteed auto-save and stops all VNC processes."""
        async with self._lock:
            await self._cleanup_internal(skip_save=False)

    async def _cleanup_internal(self, skip_save: bool = False):
        self._is_running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if not skip_save and self._context:
            try: await self._extract_and_save_session(self._current_platform)
            except Exception as e: logger.warning("[VNC-Manager] Auto-save during cleanup failed: %s", e)
        try:
            if self._context: await self._context.close()
        except Exception: pass
        self._context = None
        self._page = None
        try:
            if self._playwright: await self._playwright.stop()
        except Exception: pass
        self._playwright = None
        self._kill_stale_processes()
        logger.info("[VNC-Manager] VNC stack stopped and all system resources freed.")

    def _kill_stale_processes(self):
        for proc in [self._websockify_proc, self._x11vnc_proc, self._openbox_proc, self._xvfb_proc]:
            if proc:
                try: proc.terminate(); proc.wait(timeout=0.5)
                except Exception:
                    try: proc.kill()
                    except Exception: pass
        self._websockify_proc = self._x11vnc_proc = self._openbox_proc = self._xvfb_proc = None
        my_pid = os.getpid()
        if os.path.exists("/proc"):
            for pid_dir in os.listdir("/proc"):
                if pid_dir.isdigit():
                    pid = int(pid_dir)
                    if pid == my_pid: continue
                    try:
                        with open(f"/proc/{pid}/cmdline", "rb") as f:
                            cmdline = f.read().decode("utf-8", errors="ignore")
                            if any(target in cmdline for target in ["Xvfb", "x11vnc", "websockify", "openbox"]):
                                os.kill(pid, 9)
                    except Exception: pass
        for lock in ["/tmp/.X99-lock", "/tmp/.X11-unix/X99"]:
            if os.path.exists(lock):
                try:
                    if os.path.isdir(lock): shutil.rmtree(lock)
                    else: os.remove(lock)
                except Exception: pass

vnc_manager = VncManager()
