import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Optional
import psycopg
from psycopg.rows import dict_row
from playwright.async_api import async_playwright, BrowserContext, Page
from app.config import settings

logger = logging.getLogger("app.services.vnc_manager")

class VncManager:
    """
    Manages live interactive VNC sessions on the server:
    1. Spawns Xvfb virtual display on :99
    2. Spawns Openbox window manager
    3. Spawns x11vnc VNC server
    4. Spawns websockify gateway on port 6080 serving noVNC
    5. Launches Playwright Chromium with persistent user-data-dir on DISPLAY=:99
    6. Allows user to interactively login on Facebook, handle 2FA, enter E2EE PIN
    7. Extracts authenticated session cookies & stores them into PostgreSQL database.
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

    def is_running(self) -> bool:
        return self._is_running and self._context is not None

    async def check_ready(self) -> bool:
        """Returns True if VNC websockify port 6080 is listening and page is alive."""
        if not self._is_running or not self._page:
            return False
        try:
            # Check if port 6080 is listening
            reader, writer = await asyncio.open_connection("127.0.0.1", 6080)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def start_session(self) -> dict:
        """Starts the full X11 + VNC + Chromium interactive environment."""
        async with self._lock:
            if self._is_running and self._context:
                logger.info("[VNC-Manager] Session already running; returning active state.")
                return {"status": "success", "message": "Phiên VNC đang hoạt động."}

            logger.info("[VNC-Manager] Starting interactive VNC browser session...")
            try:
                # 1. Kill any stale Xvfb / x11vnc / websockify instances
                self._kill_stale_processes()

                # Clean up lock files for display :99
                for lock in ["/tmp/.X99-lock", "/tmp/.X11-unix/X99"]:
                    if os.path.exists(lock):
                        try:
                            if os.path.isdir(lock):
                                shutil.rmtree(lock)
                            else:
                                os.remove(lock)
                        except Exception:
                            pass

                # 2. Start Xvfb
                self._xvfb_proc = subprocess.Popen(
                    ["Xvfb", self._display, "-screen", "0", "1366x768x24", "-nolisten", "tcp", "+extension", "GLX"],
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

                # 4. Start x11vnc
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
                        "-wait", "5"
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(0.5)

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
                await asyncio.sleep(0.5)

                # 6. Launch Playwright Chromium in headed mode on DISPLAY=:99
                profile_dir = "/app/browser_data"
                os.makedirs(profile_dir, exist_ok=True)

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
                        "--window-size=1366,768",
                        "--start-maximized",
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
                logger.info("[VNC-Manager] Interactive VNC session successfully launched on :99 / websockify:6080")
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
        """Extracts cookies from active context, saves to PostgreSQL, and cleans up."""
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

                # Save to PostgreSQL
                async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            INSERT INTO fb_auto_responder_config (id, cookies_json, last_status, updated_at)
                            VALUES (1, %s, %s, NOW())
                            ON CONFLICT (id) DO UPDATE
                            SET cookies_json = EXCLUDED.cookies_json,
                                last_status = EXCLUDED.last_status,
                                updated_at = NOW()
                        """, (cookies_json, "Đã lưu phiên từ Server Chromium"))
                        await conn.commit()

                # Clean up session
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
        logger.info("[VNC-Manager] VNC stack stopped and resources cleaned up.")

    def _kill_stale_processes(self):
        for proc in [self._websockify_proc, self._x11vnc_proc, self._openbox_proc, self._xvfb_proc]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._websockify_proc = None
        self._x11vnc_proc = None
        self._openbox_proc = None
        self._xvfb_proc = None

        # Fallback system-level kill
        try:
            subprocess.run(["pkill", "-f", "Xvfb :99"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-f", "x11vnc.*:99"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-f", "websockify.*6080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

vnc_manager = VncManager()
