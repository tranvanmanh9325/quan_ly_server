"""
services/ai-agent-service/app/services/honeypot_service.py
Deception Layer — Fake SSH (Port 2222) & Fake Telnet (Port 23) Honeypot Service.

Features:
- Fake SSH Server (Port 2222): OpenSSH banner, login/password capture, troll payload after 3 failed attempts.
- Fake Telnet Server (Port 23): Ubuntu banner, RFC 854 IAC strip FSM, login/password capture, troll payload after 3 failed attempts.
- DoS Protection: max 50 concurrent connections (asyncio.Semaphore), 15s socket timeout, 1024B line buffer limit.
- Resilient Dual-Tier Storage: PostgreSQL pool + SQLite WAL fallback (PRAGMA journal_mode=WAL, busy_timeout=5000) with asyncio.Lock.
- Real-Time In-Memory Aggregator: < 1ms get_stats() queries.
- Clean Lifecycle & Shutdown: 0 ResourceWarning unclosed transport/socket.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import logging
import os
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("app.services.honeypot")

# Vietnam Timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

# ── 1. TELNET IAC FILTER (RFC 854) ────────────────────────────────────────────

def strip_telnet_iac(data: bytes) -> bytes:
    """
    Strips Telnet IAC (Interpret As Command - RFC 854) sequences safely.
    Handles:
    - Escaped IAC: 0xFF 0xFF -> 0xFF
    - 3-byte option negotiations: 0xFF (DO|DONT|WILL|WONT) <opt>
    - Subnegotiations: 0xFF 0xFA ... 0xFF 0xF0
    - 2-byte commands: 0xFF <cmd>
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0xFF:
            if i + 1 >= n:
                break
            cmd = data[i + 1]
            if cmd == 0xFF:  # Escaped IAC (literal 0xFF byte)
                out.append(0xFF)
                i += 2
            elif cmd in (0xFB, 0xFC, 0xFD, 0xFE):  # WILL, WONT, DO, DONT (3 bytes)
                i += 3
            elif cmd == 0xFA:  # Subnegotiation (IAC SB ... IAC SE: 0xFF 0xF0)
                se_idx = data.find(b"\xff\xf0", i + 2)
                if se_idx != -1:
                    i = se_idx + 2
                else:
                    break
            else:  # Generic 2-byte IAC command
                i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def _is_postgres_available() -> bool:
    """Checks if async PostgreSQL can be safely used without blocking the event loop."""
    if os.name == "nt":
        try:
            loop = asyncio.get_running_loop()
            if "Proactor" in type(loop).__name__:
                return False
        except RuntimeError:
            return False
    if os.getenv("HONEYPOT_DISABLE_POSTGRES", "").lower() in ("1", "true", "yes"):
        return False
    return True


# ── 2. CONFIGURATION & MODELS ─────────────────────────────────────────────────

@dataclass
class HoneypotConfig:
    bind_host: str = "0.0.0.0"
    ssh_port: int = 2222
    telnet_port: int = 23
    max_connections: int = 50
    socket_timeout: float = 15.0
    max_line_length: int = 1024
    auth_delay: float = 0.5
    db_path: str = "data/security/honeypot_fallback.db"
    use_postgres: Optional[bool] = None

    ssh_banner: bytes = b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.10\r\n"
    telnet_banner: bytes = (
        b"\r\nUbuntu 22.04.4 LTS (GNU/Linux 5.15.0-107-generic x86_64)\r\n"
        b" * Documentation:  https://help.ubuntu.com\r\n"
        b" * Management:     https://landscape.canonical.com\r\n"
        b" * Support:        https://ubuntu.com/pro\r\n\r\n"
    )
    troll_payload: bytes = (
        "\r\n💀 Kẻ thất bại. Lần sau cố gắng hơn nhé! - Tiểu Bảo Bảo Security Team 😂\r\n\r\n"
    ).encode("utf-8")


@dataclass(slots=True)
class HoneypotCredentialRecord:
    id: Optional[int]
    ip: str
    service: str  # 'ssh' or 'telnet'
    username: str
    password: str
    attempt_count: int = 1
    captured_at: float = field(default_factory=time.time)
    raw_session: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        dt = datetime.fromtimestamp(self.captured_at, tz=timezone.utc).astimezone(VN_TZ)
        return {
            "id": self.id,
            "ip": self.ip,
            "service": self.service,
            "username": self.username,
            "password": self.password,
            "attempt_count": self.attempt_count,
            "captured_at": dt.isoformat(),
            "epoch_timestamp": self.captured_at,
            "raw_session": self.raw_session,
        }


# ── 3. STORAGE LAYER ─────────────────────────────────────────────────────────

class HoneypotStorageRepository:
    """
    Dual-Tier Resilient Persistence for Honeypot Credentials:
    1. Primary: PostgreSQL async connection pool via app.core.db.get_db_dict_cursor
    2. Fallback: Local SQLite database with WAL mode and serialized asyncio.Lock
    3. Safety Net: In-memory circular buffer deque(maxlen=2000)
    """

    def __init__(
        self,
        db_path: str = "data/security/honeypot_fallback.db",
        use_postgres: Optional[bool] = None,
    ):
        self.db_path = db_path
        self._use_postgres = _is_postgres_available() if use_postgres is None else use_postgres
        self._write_lock = asyncio.Lock()
        self._mem_records: deque[Dict[str, Any]] = deque(maxlen=2000)
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        try:
            if self.db_path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA busy_timeout=5000;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS honeypot_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip TEXT NOT NULL,
                        service TEXT NOT NULL,
                        username TEXT,
                        password TEXT,
                        attempt_count INTEGER NOT NULL DEFAULT 1,
                        captured_at REAL NOT NULL,
                        raw_session TEXT
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_honeypot_fb_captured_at ON honeypot_credentials(captured_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_honeypot_fb_ip ON honeypot_credentials(ip);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_honeypot_fb_service ON honeypot_credentials(service);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_honeypot_fb_username ON honeypot_credentials(username);")
                conn.commit()
            finally:
                conn.close()
        except Exception as ex:
            logger.warning("[HoneypotStorage] SQLite init failed on %s (%s). Using :memory:", self.db_path, ex)
            self.db_path = ":memory:"
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA busy_timeout=5000;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS honeypot_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip TEXT NOT NULL,
                        service TEXT NOT NULL,
                        username TEXT,
                        password TEXT,
                        attempt_count INTEGER NOT NULL DEFAULT 1,
                        captured_at REAL NOT NULL,
                        raw_session TEXT
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    async def save_credential(self, record: HoneypotCredentialRecord) -> Optional[int]:
        # Always save to memory ring buffer
        dict_rep = record.to_dict()
        self._mem_records.appendleft(dict_rep)

        # 1. Try PostgreSQL if enabled
        if self._use_postgres:
            try:
                from app.core.db import get_db_dict_cursor
                async with get_db_dict_cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO honeypot_credentials (ip, service, username, password, attempt_count, captured_at, raw_session)
                        VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), %s)
                        RETURNING id;
                        """,
                        (
                            record.ip,
                            record.service,
                            record.username[:128],
                            record.password[:256],
                            record.attempt_count,
                            record.captured_at,
                            record.raw_session,
                        ),
                    )
                    row = await cur.fetchone()
                    if row and "id" in row:
                        record.id = int(row["id"])
                        dict_rep["id"] = record.id
                        return record.id
            except Exception as pg_ex:
                logger.debug("[HoneypotStorage] PostgreSQL save skipped/failed: %s. Using SQLite.", pg_ex)

        # 2. Fallback SQLite
        def _sync_sqlite_save() -> int:
            conn = self._get_sqlite_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO honeypot_credentials (ip, service, username, password, attempt_count, captured_at, raw_session)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.ip,
                        record.service,
                        record.username[:128],
                        record.password[:256],
                        record.attempt_count,
                        record.captured_at,
                        record.raw_session,
                    ),
                )
                conn.commit()
                return cur.lastrowid or 0
            finally:
                conn.close()

        async with self._write_lock:
            try:
                row_id = await asyncio.to_thread(_sync_sqlite_save)
                record.id = row_id
                dict_rep["id"] = row_id
                return row_id
            except Exception as sq_ex:
                logger.error("[HoneypotStorage] SQLite fallback save failed: %s", sq_ex)
                return None

    async def get_credentials(self, limit: int = 50, service: Optional[str] = None) -> List[Dict[str, Any]]:
        # 1. Try PostgreSQL if enabled
        if self._use_postgres:
            try:
                from app.core.db import get_db_dict_cursor
                async with get_db_dict_cursor() as cur:
                    if service:
                        await cur.execute(
                            """
                            SELECT id, ip, service, username, password, attempt_count,
                                   EXTRACT(EPOCH FROM captured_at) AS epoch_ts, raw_session
                            FROM honeypot_credentials
                            WHERE service = %s
                            ORDER BY id DESC
                            LIMIT %s;
                            """,
                            (service, limit),
                        )
                    else:
                        await cur.execute(
                            """
                            SELECT id, ip, service, username, password, attempt_count,
                                   EXTRACT(EPOCH FROM captured_at) AS epoch_ts, raw_session
                            FROM honeypot_credentials
                            ORDER BY id DESC
                            LIMIT %s;
                            """,
                            (limit,),
                        )
                    rows = await cur.fetchall()
                    if rows:
                        results = []
                        for r in rows:
                            epoch = float(r.get("epoch_ts") or time.time())
                            dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(VN_TZ)
                            results.append({
                                "id": r["id"],
                                "ip": r["ip"],
                                "service": r["service"],
                                "username": r["username"],
                                "password": r["password"],
                                "attempt_count": r["attempt_count"],
                                "captured_at": dt.isoformat(),
                                "epoch_timestamp": epoch,
                                "raw_session": r.get("raw_session"),
                            })
                        return results
            except Exception as pg_ex:
                logger.debug("[HoneypotStorage] PostgreSQL read skipped/failed: %s. Using SQLite.", pg_ex)

        # 2. Fallback SQLite
        def _sync_sqlite_load() -> List[Dict[str, Any]]:
            conn = self._get_sqlite_conn()
            res = []
            try:
                cur = conn.cursor()
                if service:
                    cur.execute(
                        """
                        SELECT id, ip, service, username, password, attempt_count, captured_at, raw_session
                        FROM honeypot_credentials
                        WHERE service = ?
                        ORDER BY id DESC
                        LIMIT ?;
                        """,
                        (service, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, ip, service, username, password, attempt_count, captured_at, raw_session
                        FROM honeypot_credentials
                        ORDER BY id DESC
                        LIMIT ?;
                        """,
                        (limit,),
                    )
                for row in cur.fetchall():
                    epoch = float(row[6])
                    dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(VN_TZ)
                    res.append({
                        "id": row[0],
                        "ip": row[1],
                        "service": row[2],
                        "username": row[3],
                        "password": row[4],
                        "attempt_count": row[5],
                        "captured_at": dt.isoformat(),
                        "epoch_timestamp": epoch,
                        "raw_session": row[7],
                    })
            finally:
                conn.close()
            return res

        try:
            sqlite_res = await asyncio.to_thread(_sync_sqlite_load)
            if sqlite_res:
                return sqlite_res
        except Exception as sq_ex:
            logger.error("[HoneypotStorage] SQLite load error: %s", sq_ex)

        # 3. Fallback In-Memory Deque
        filtered = [
            r for r in self._mem_records
            if service is None or r.get("service") == service
        ]
        return list(filtered)[:limit]


# ── 4. HONEYPOT SERVICE ──────────────────────────────────────────────────────

class HoneypotService:
    """
    Autonomous Deception Layer — Honeypot 'Kẻ Thất Bại' Service.
    Orchestrates SSH (Port 2222) and Telnet (Port 23) Fake Listeners,
    Harvests Credentials into Dual-Tier DB, and provides Clean Lifespan Management.
    """
    _instance: Optional["HoneypotService"] = None

    def __init__(
        self,
        config: Optional[HoneypotConfig] = None,
        repository: Optional[HoneypotStorageRepository] = None,
        on_harvest_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        on_block_ip_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        security_monitor: Optional[Any] = None,
        alert_engine: Optional[Any] = None,
    ):
        self.config = config or HoneypotConfig()
        self.repository = repository or HoneypotStorageRepository(
            db_path=self.config.db_path,
            use_postgres=self.config.use_postgres,
        )
        self.alert_engine = alert_engine
        self.on_harvest_callback = on_harvest_callback
        if self.on_harvest_callback is None and alert_engine and hasattr(alert_engine, "handle_honeypot_harvest"):
            self.on_harvest_callback = alert_engine.handle_honeypot_harvest

        self.on_block_ip_callback = on_block_ip_callback
        self.security_monitor = security_monitor

        # Lifecycle State
        self._running: bool = False
        self._start_time: float = 0.0
        self._lock = asyncio.Lock()

        # Listeners & Concurrency Protection
        self._ssh_server: Optional[asyncio.Server] = None
        self._telnet_server: Optional[asyncio.Server] = None
        self._semaphore = asyncio.Semaphore(self.config.max_connections)

        # Tracking for Clean Shutdown (0 ResourceWarning)
        self._active_writers: Set[asyncio.StreamWriter] = set()
        self._active_tasks: Set[asyncio.Task] = set()

        # Fast-Path In-Memory State Aggregation (< 1ms queries)
        self._total_probes: int = 0
        self._total_credentials: int = 0
        self._service_counts: Counter[str] = Counter()
        self._top_usernames: Counter[str] = Counter()
        self._top_passwords: Counter[str] = Counter()
        self._unique_ips: Set[str] = set()
        self._hourly_probes: deque[float] = deque(maxlen=10000)

    def set_alert_engine(self, alert_engine: Any) -> None:
        """Injects or updates the Telegram Security Alert Engine instance."""
        self.alert_engine = alert_engine
        if hasattr(alert_engine, "handle_honeypot_harvest") and self.on_harvest_callback is None:
            self.on_harvest_callback = alert_engine.handle_honeypot_harvest

    @classmethod
    def get_instance(cls, **kwargs) -> "HoneypotService":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Starts Fake SSH (Port 2222) and Fake Telnet (Port 23) listeners asynchronously.
        Idempotent: safe to invoke repeatedly.
        Resilient: handles OSError gracefully (unprivileged port on Windows/non-root).
        """
        async with self._lock:
            if self._running:
                logger.debug("[HoneypotService] start() called but already running.")
                return

            self._running = True
            self._start_time = time.time()
            logger.info("[HoneypotService] Starting Honeypot 'Kẻ Thất Bại' listeners...")

            # 1. Start Fake SSH Listener
            try:
                self._ssh_server = await asyncio.start_server(
                    self._handle_ssh_connection,
                    host=self.config.bind_host,
                    port=self.config.ssh_port,
                    limit=self.config.max_line_length,
                )
                logger.info(
                    "[HoneypotService] Fake SSH Listener running on %s:%d ✓",
                    self.config.bind_host, self.config.ssh_port
                )
            except OSError as ex:
                logger.warning(
                    "[HoneypotService] Could not bind Fake SSH on %s:%d: %s (non-fatal)",
                    self.config.bind_host, self.config.ssh_port, ex
                )
                self._ssh_server = None

            # 2. Start Fake Telnet Listener
            try:
                self._telnet_server = await asyncio.start_server(
                    self._handle_telnet_connection,
                    host=self.config.bind_host,
                    port=self.config.telnet_port,
                    limit=self.config.max_line_length,
                )
                logger.info(
                    "[HoneypotService] Fake Telnet Listener running on %s:%d ✓",
                    self.config.bind_host, self.config.telnet_port
                )
            except OSError as ex:
                logger.warning(
                    "[HoneypotService] Could not bind Fake Telnet on %s:%d: %s (non-fatal)",
                    self.config.bind_host, self.config.telnet_port, ex
                )
                self._telnet_server = None

    async def stop(self) -> None:
        """
        Stops all listeners, drains and closes active client transports,
        cancels all connection tasks, and guarantees 0 ResourceWarning.
        Idempotent: safe to invoke repeatedly.
        """
        async with self._lock:
            if not self._running:
                return
            self._running = False
            logger.info("[HoneypotService] Stopping Honeypot listeners and active connections...")

            # 1. Close SSH server socket
            if self._ssh_server is not None:
                self._ssh_server.close()
                try:
                    await self._ssh_server.wait_closed()
                except Exception as ex:
                    logger.debug("[HoneypotService] SSH wait_closed: %s", ex)
                self._ssh_server = None

            # 2. Close Telnet server socket
            if self._telnet_server is not None:
                self._telnet_server.close()
                try:
                    await self._telnet_server.wait_closed()
                except Exception as ex:
                    logger.debug("[HoneypotService] Telnet wait_closed: %s", ex)
                self._telnet_server = None

            # 3. Close all active client transports
            for writer in list(self._active_writers):
                try:
                    if not writer.is_closing():
                        writer.close()
                        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except (Exception, asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            self._active_writers.clear()

            # 4. Cancel and gather active connection tasks
            tasks_to_cancel = [t for t in self._active_tasks if not t.done()]
            for t in tasks_to_cancel:
                t.cancel()
            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self._active_tasks.clear()

            logger.info("[HoneypotService] Honeypot service stopped cleanly (0 ResourceWarning) ✓")

    # ── Connection Handlers ──────────────────────────────────────────────────

    async def _handle_ssh_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task:
            self._active_tasks.add(task)
        self._active_writers.add(writer)

        peer = writer.get_extra_info("peername")
        client_ip = peer[0] if peer else "unknown"
        port = self.config.ssh_port

        # DoS Concurrency Protection: drop immediately if capacity exceeded
        if self._semaphore.locked():
            logger.warning("[Honeypot-SSH] Max connections (%d) reached. Dropping %s", self.config.max_connections, client_ip)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            finally:
                self._active_writers.discard(writer)
                if task:
                    self._active_tasks.discard(task)
            return

        async with self._semaphore:
            credentials_tried: List[Tuple[str, str]] = []
            try:
                # 1. Send Ubuntu OpenSSH Banner
                writer.write(self.config.ssh_banner)
                await writer.drain()

                # 2. Authentication Loop (Max 3 attempts)
                for attempt in range(1, 4):
                    # Prompt Username
                    writer.write(b"login: ")
                    await writer.drain()

                    raw_user = await asyncio.wait_for(reader.readline(), timeout=self.config.socket_timeout)
                    if not raw_user:
                        break
                    username = raw_user.decode("utf-8", errors="replace").strip()

                    # Prompt Password
                    writer.write(b"Password: ")
                    await writer.drain()

                    raw_pass = await asyncio.wait_for(reader.readline(), timeout=self.config.socket_timeout)
                    if not raw_pass:
                        break
                    password = raw_pass.decode("utf-8", errors="replace").strip()

                    # Harvest credential
                    credentials_tried.append((username, password))
                    await self.log_credential(
                        ip=client_ip,
                        service="ssh",
                        username=username,
                        password=password,
                        attempt_count=attempt,
                        raw_session=f"port={port};peer={peer}",
                    )

                    if attempt < 3:
                        writer.write(b"\r\nAccess denied\r\n\r\n")
                        await writer.drain()
                        if self.config.auth_delay > 0:
                            await asyncio.sleep(self.config.auth_delay)
                    else:
                        # 3rd failed attempt -> Troll Payload
                        writer.write(self.config.troll_payload)
                        await writer.drain()
                        break

            except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            except Exception as ex:
                logger.debug("[Honeypot-SSH] Error handling %s: %s", client_ip, ex)
            finally:
                try:
                    if not writer.is_closing():
                        writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                self._active_writers.discard(writer)
                if task:
                    self._active_tasks.discard(task)

            # Post-session triggers
            if credentials_tried:
                await self._trigger_session_alerts(client_ip, port, "ssh", credentials_tried)

    async def _handle_telnet_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task:
            self._active_tasks.add(task)
        self._active_writers.add(writer)

        peer = writer.get_extra_info("peername")
        client_ip = peer[0] if peer else "unknown"
        port = self.config.telnet_port

        if self._semaphore.locked():
            logger.warning("[Honeypot-Telnet] Max connections (%d) reached. Dropping %s", self.config.max_connections, client_ip)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            finally:
                self._active_writers.discard(writer)
                if task:
                    self._active_tasks.discard(task)
            return

        async with self._semaphore:
            credentials_tried: List[Tuple[str, str]] = []
            try:
                # 1. Send Ubuntu Welcome Banner
                writer.write(self.config.telnet_banner)
                await writer.drain()

                # 2. Authentication Loop (Max 3 attempts)
                for attempt in range(1, 4):
                    # Prompt Login
                    writer.write(b"kirito-server login: ")
                    await writer.drain()

                    raw_user = await asyncio.wait_for(reader.readline(), timeout=self.config.socket_timeout)
                    if not raw_user:
                        break
                    clean_user = strip_telnet_iac(raw_user)
                    username = clean_user.decode("utf-8", errors="replace").strip()

                    # Prompt Password
                    writer.write(b"Password: ")
                    await writer.drain()

                    raw_pass = await asyncio.wait_for(reader.readline(), timeout=self.config.socket_timeout)
                    if not raw_pass:
                        break
                    clean_pass = strip_telnet_iac(raw_pass)
                    password = clean_pass.decode("utf-8", errors="replace").strip()

                    # Harvest credential
                    credentials_tried.append((username, password))
                    await self.log_credential(
                        ip=client_ip,
                        service="telnet",
                        username=username,
                        password=password,
                        attempt_count=attempt,
                        raw_session=f"port={port};peer={peer}",
                    )

                    if attempt < 3:
                        writer.write(b"\r\nLogin incorrect\r\n\r\n")
                        await writer.drain()
                        if self.config.auth_delay > 0:
                            await asyncio.sleep(self.config.auth_delay)
                    else:
                        # 3rd failed attempt -> Troll Payload
                        writer.write(self.config.troll_payload)
                        await writer.drain()
                        break

            except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            except Exception as ex:
                logger.debug("[Honeypot-Telnet] Error handling %s: %s", client_ip, ex)
            finally:
                try:
                    if not writer.is_closing():
                        writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                self._active_writers.discard(writer)
                if task:
                    self._active_tasks.discard(task)

            # Post-session triggers
            if credentials_tried:
                await self._trigger_session_alerts(client_ip, port, "telnet", credentials_tried)

    # ── Notification & Defense Hooks ─────────────────────────────────────────

    async def _trigger_session_alerts(
        self,
        ip: str,
        port: int,
        service: str,
        creds: List[Tuple[str, str]],
    ) -> None:
        # 1. Harvest Callback (Telegram or external collector)
        if self.on_harvest_callback:
            try:
                res = self.on_harvest_callback({
                    "ip": ip,
                    "port": port,
                    "service": service,
                    "credentials": creds,
                    "attempts": len(creds),
                })
                if asyncio.iscoroutine(res):
                    await res
            except Exception as ex:
                logger.error("[Honeypot] Error in on_harvest_callback: %s", ex)

        # Direct Alert Engine fallback if on_harvest_callback was customized
        if (
            self.alert_engine
            and hasattr(self.alert_engine, "handle_honeypot_harvest")
            and self.on_harvest_callback != self.alert_engine.handle_honeypot_harvest
        ):
            try:
                res_ae = self.alert_engine.handle_honeypot_harvest({
                    "ip": ip,
                    "port": port,
                    "service": service,
                    "credentials": creds,
                    "attempts": len(creds),
                })
                if asyncio.iscoroutine(res_ae):
                    await res_ae
            except Exception as ae_ex:
                logger.error("[Honeypot] Error in alert_engine.handle_honeypot_harvest: %s", ae_ex)

        # 2. Auto-block IP Callback if 3 failed attempts reached
        if len(creds) >= 3:
            reason = f"Honeypot trap: 3 failed attempts on Fake {service.upper()} (Port {port})"
            if self.on_block_ip_callback:
                try:
                    res = self.on_block_ip_callback(ip, reason)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as ex:
                    logger.error("[Honeypot] Error in on_block_ip_callback: %s", ex)

            # Auto-hook with SecurityMonitorService if registered
            sec_mon = self.security_monitor
            if sec_mon is None:
                try:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_mon = SecurityMonitorService.get_instance()
                except Exception:
                    sec_mon = None

            if sec_mon is not None and hasattr(sec_mon, "block_ip"):
                try:
                    if hasattr(sec_mon, "is_whitelisted") and not sec_mon.is_whitelisted(ip):
                        await sec_mon.block_ip(
                            ip=ip,
                            reason=reason,
                            duration_seconds=86400,
                            threat_level="HIGH",
                        )
                except Exception as sm_ex:
                    logger.debug("[Honeypot] Security monitor auto-block skipped: %s", sm_ex)

    # ── Public APIs ──────────────────────────────────────────────────────────

    async def log_credential(
        self,
        ip: str,
        service: str,
        username: str,
        password: str,
        attempt_count: int = 1,
        raw_session: Optional[str] = None,
    ) -> None:
        """
        Records a harvested credential attempt, updates in-memory metrics,
        and saves into Dual-Tier persistent storage.
        """
        clean_ip = ip.strip()
        if clean_ip.startswith("::ffff:"):
            clean_ip = clean_ip[7:]

        now = time.time()
        record = HoneypotCredentialRecord(
            id=None,
            ip=clean_ip,
            service=service.lower().strip(),
            username=username.strip() if username else "",
            password=password.strip() if password else "",
            attempt_count=attempt_count,
            captured_at=now,
            raw_session=raw_session,
        )

        # 1. Persist to storage
        await self.repository.save_credential(record)

        # 2. Update Fast-Path In-Memory State Aggregation
        self._total_probes += 1
        self._total_credentials += 1
        self._service_counts[record.service] += 1
        self._unique_ips.add(clean_ip)
        if record.username:
            self._top_usernames[record.username] += 1
        if record.password:
            self._top_passwords[record.password] += 1
        self._hourly_probes.append(now)

        logger.info(
            "[HoneypotHarvest] [%s] Captured creds from %s (Attempt %d): %s / %s",
            record.service.upper(), clean_ip, attempt_count, record.username,
            "*" * len(record.password) if record.password else "<empty>"
        )

    async def get_honeypot_log(
        self,
        limit: int = 50,
        service: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves up to `limit` harvested credentials ordered chronologically (newest first).
        Optionally filters by service ('ssh' or 'telnet').
        """
        safe_limit = max(1, min(limit, 500))
        svc_filter = service.lower().strip() if service else None
        return await self.repository.get_credentials(limit=safe_limit, service=svc_filter)

    def get_stats(self) -> Dict[str, Any]:
        """
        Fast-path O(1) synchronous state aggregation for AI Agent tools and Dashboards.
        Returns:
            Dict containing:
            - status ('running' | 'stopped')
            - uptime_seconds
            - listeners status (ssh, telnet)
            - active_connections
            - total_probes, total_credentials
            - service_breakdown
            - unique_ips_count
            - top_usernames (top 10)
            - top_passwords (top 10)
            - probes_last_hour
        """
        now = time.time()
        uptime = (now - self._start_time) if self._running else 0.0

        cutoff = now - 3600.0
        while self._hourly_probes and self._hourly_probes[0] < cutoff:
            self._hourly_probes.popleft()
        probes_last_hour = len(self._hourly_probes)

        return {
            "status": "running" if self._running else "stopped",
            "uptime_seconds": round(uptime, 1),
            "listeners": {
                "ssh": {
                    "port": self.config.ssh_port,
                    "active": self._ssh_server is not None and self._ssh_server.is_serving(),
                },
                "telnet": {
                    "port": self.config.telnet_port,
                    "active": self._telnet_server is not None and self._telnet_server.is_serving(),
                },
            },
            "active_connections": len(self._active_writers),
            "total_probes": self._total_probes,
            "total_credentials": self._total_credentials,
            "service_breakdown": {
                "ssh": self._service_counts.get("ssh", 0),
                "telnet": self._service_counts.get("telnet", 0),
            },
            "unique_ips_count": len(self._unique_ips),
            "top_usernames": [
                {"username": u, "count": c}
                for u, c in self._top_usernames.most_common(10)
            ],
            "top_passwords": [
                {"password": p, "count": c}
                for p, c in self._top_passwords.most_common(10)
            ],
            "probes_last_hour": probes_last_hour,
        }
