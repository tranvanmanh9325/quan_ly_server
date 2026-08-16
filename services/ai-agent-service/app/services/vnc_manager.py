import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from typing import Optional
import psycopg
from psycopg.rows import dict_row
from playwright.async_api import async_playwright, BrowserContext, Page
from app.config import settings

logger = logging.getLogger("app.services.vnc_manager")

# Maximum idle time allowed before auto-reaping the VNC session (10 minutes)
MAX_IDLE_SECONDS = 600

class VncManager:
    """
    High-Performance & Low-Resource VNC Manager:
    1. Spawns Xvfb virtual display with minimal memory footprint on :99
    2. Spawns Openbox window manager
    3. Spawns x11vnc with multi-threaded ZRLE compression, 60 FPS pacing, and zero CPU spinlock
    4. Spawns websockify gateway on port 6080 serving noVNC
    5. Launches Playwright Chromium with persistent user-data-dir and optimized memory flags
    6. Features an Auto-Reaper Watchdog to automatically free all memory/CPU if idle > 10m
    7. Extracts authenticated session cookies & stores them into PostgreSQL table facebook_config.
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

    async def _idle_watchdog(self):
        """Background daemon that auto-reaps the session if no activity for MAX_IDLE_SECONDS."""
        logger.info("[VNC-Manager] Idle watchdog started (timeout: %ds).", MAX_IDLE_SECONDS)
        try:
            while self._is_running:
                await asyncio.sleep(15)
                if self._is_running and (time.time() - self._last_active_time > MAX_IDLE_SECONDS):
                    logger.warning("[VNC-Manager] Session idle for >%ds; auto-reaping resources...", MAX_IDLE_SECONDS)
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

    async def start_session(self) -> dict:
        """Starts the full X11 + VNC + Chromium interactive environment with low-resource flags."""
        async with self._lock:
            # If session is truly active and ports are open, return success
            if self.is_running() and self._check_port_listening(6080) and self._check_port_listening(5900):
                self.touch()
                logger.info("[VNC-Manager] Session already running and healthy; returning active state.")
                return {"status": "success", "message": "Phiên VNC đang hoạt động."}

            # If state was inconsistent or processes died, clean up completely first
            if self._is_running or self._context or self._xvfb_proc:
                logger.info("[VNC-Manager] Cleaning up inconsistent session before fresh start...")
                await self._cleanup_internal()

            logger.info("[VNC-Manager] Starting optimized interactive VNC browser session...")
            try:
                # 1. Kill any stale Xvfb / x11vnc / websockify instances & clean locks
                self._kill_stale_processes()
                await asyncio.sleep(0.3)

                # 2. Start Xvfb (1280x800x24 - aligned to 4-byte pixels)
                self._xvfb_proc = subprocess.Popen(
                    ["Xvfb", self._display, "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset", "+extension", "GLX"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(0.5)

                # 3. Start Openbox Window Manager
                env = os.environ.copy()
                env["DISPLAY"] = self._display
                self._openbox_proc = subprocess.Popen(
                    ["openbox", "--sm-disable"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(0.3)

                # 4. Start x11vnc with high-efficiency polling:
                #    -threads: Multi-threaded ZRLE encoding (standalone flag)
                #    -nap, -wait 16, -defer 16: Smooth 60 FPS pacing, zero CPU spinlock
                self._x11vnc_proc = subprocess.Popen(
                    [
                        "x11vnc",
                        "-display", self._display,
                        "-forever",
                        "-nopw",
                        "-shared",
                        "-rfbport", "5900",
                        "-listen", "127.0.0.1",
                        "-noxdamage",
                        "-nap",
                        "-wait", "16",
                        "-defer", "16",
                        "-ncache", "10",
                        "-nowf",
                        "-threads"
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                # Wait for x11vnc to be ready on port 5900
                for _ in range(25):
                    await asyncio.sleep(0.2)
                    if self._check_port_listening(5900):
                        break

                # 5. Start websockify serving /usr/share/novnc on port 6080
                novnc_web = "/usr/share/novnc" if os.path.exists("/usr/share/novnc") else None
                websockify_cmd = ["websockify"]
                if novnc_web:
                    websockify_cmd.extend(["--web", novnc_web])
                websockify_cmd.extend(["6080", "127.0.0.1:5900"])

                self._websockify_proc = subprocess.Popen(
                    websockify_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                # Wait for websockify to be ready on port 6080
                for _ in range(25):
                    await asyncio.sleep(0.2)
                    if self._check_port_listening(6080):
                        break

                # 6. Launch Playwright Chromium with resource-optimized flags
                profile_dir = "/app/browser_data"
                os.makedirs(profile_dir, exist_ok=True)

                # Clean up stale Chromium locks
                for item in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    lock_path = os.path.join(profile_dir, item)
                    if os.path.islink(lock_path) or os.path.exists(lock_path):
                        try:
                            os.remove(lock_path)
                        except Exception:
                            pass

                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    channel="chromium",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-infobars",
                        "--window-position=0,0",
                        "--window-size=1280,800",
                        "--start-maximized",
                        # Resource optimization flags: cut RAM in half and eliminate background CPU waste
                        "--renderer-process-limit=2",
                        "--js-flags=--max-old-space-size=256",
                        "--disable-gpu-vsync",
                        "--disable-smooth-scrolling",
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--disable-extensions",
                        "--no-first-run",
                        "--metrics-recording-only",
                    ],
                    viewport=None,
                    env=env,
                )

                # Open Facebook messages page
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = await self._context.new_page()

                # Navigate in background
                asyncio.create_task(self._safe_navigate(self._page, "https://www.facebook.com/messages/"))

                self._is_running = True
                self.touch()

                # Start watchdog
                if self._watchdog_task and not self._watchdog_task.done():
                    self._watchdog_task.cancel()
                self._watchdog_task = asyncio.create_task(self._idle_watchdog())

                logger.info("[VNC-Manager] Optimized interactive VNC session successfully launched.")
                return {"status": "success", "message": "Trình duyệt Server đã khởi động thành công."}

            except Exception as e:
                logger.error("[VNC-Manager] Failed to launch VNC session: %s", e, exc_info=True)
                await self._cleanup_internal()
                return {"status": "error", "message": f"Không thể khởi động trình duyệt Server: {e}"}

    async def _safe_navigate(self, page: Page, url: str):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.warning("[VNC-Manager] Navigation to %s finished with note: %s", url, e)

    async def save_session(self) -> dict:
        """Extracts cookies from active context, saves to PostgreSQL facebook_config, and cleans up."""
        async with self._lock:
            if not self._context:
                return {"status": "error", "message": "Không có phiên trình duyệt nào đang mở để lưu."}

            try:
                cookies = await self._context.cookies()
                logger.info("[VNC-Manager] Extracted %d cookies from active browser session.", len(cookies))

                # Check if c_user exists
                c_user = next((c.get("value") for c in cookies if c.get("name") == "c_user"), None)
                if not c_user:
                    logger.warning("[VNC-Manager] No 'c_user' cookie found. User might not be logged in yet.")

                cookies_json = json.dumps(cookies)

                # Save to PostgreSQL table facebook_config
                async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            INSERT INTO facebook_config (id, cookies_json, last_status, enabled, threshold, cooldown_minutes, custom_message, created_at, updated_at)
                            VALUES (1, %s, %s, true, 3, 2, '', NOW(), NOW())
                            ON CONFLICT (id) DO UPDATE
                            SET cookies_json = EXCLUDED.cookies_json,
                                last_status = EXCLUDED.last_status,
                                updated_at = NOW()
                        """, (cookies_json, "Đã lưu phiên từ Server Chromium"))
                        await conn.commit()

                # Clean up session and free 100% resources
                await self._cleanup_internal()

                msg = f"Đã lưu thành công phiên đăng nhập ({len(cookies)} cookies" + (f", User ID: {c_user}" if c_user else "") + ")!"
                logger.info("[VNC-Manager] %s", msg)
                return {"status": "success", "message": msg}

            except Exception as e:
                logger.error("[VNC-Manager] Failed to save session: %s", e, exc_info=True)
                return {"status": "error", "message": f"Lỗi khi trích xuất và lưu phiên: {e}"}

    async def close_session(self):
        """Closes browser and stops all VNC processes."""
        async with self._lock:
            await self._cleanup_internal()

    async def _cleanup_internal(self):
        self._is_running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        self._context = None
        self._page = None

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None

        self._kill_stale_processes()
        logger.info("[VNC-Manager] VNC stack stopped and all system resources freed.")

    def _kill_stale_processes(self):
        # 1. Terminate tracked subprocesses
        for proc in [self._websockify_proc, self._x11vnc_proc, self._openbox_proc, self._xvfb_proc]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._websockify_proc = None
        self._x11vnc_proc = None
        self._openbox_proc = None
        self._xvfb_proc = None

        # 2. Native /proc scan kill for zero-dependency cleanup
        my_pid = os.getpid()
        if os.path.exists("/proc"):
            for pid_dir in os.listdir("/proc"):
                if pid_dir.isdigit():
                    pid = int(pid_dir)
                    if pid == my_pid:
                        continue
                    try:
                        with open(f"/proc/{pid}/cmdline", "rb") as f:
                            cmdline = f.read().decode("utf-8", errors="ignore")
                            if any(target in cmdline for target in ["Xvfb", "x11vnc", "websockify", "openbox"]):
                                import signal
                                os.kill(pid, signal.SIGKILL)
                    except Exception:
                        pass

        # 3. Clean up lock files for display :99
        for lock in ["/tmp/.X99-lock", "/tmp/.X11-unix/X99"]:
            if os.path.exists(lock):
                try:
                    if os.path.isdir(lock):
                        shutil.rmtree(lock)
                    else:
                        os.remove(lock)
                except Exception:
                    pass

vnc_manager = VncManager()
