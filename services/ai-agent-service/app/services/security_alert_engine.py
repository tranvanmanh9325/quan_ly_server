"""
services/ai-agent-service/app/services/security_alert_engine.py
Milestone 3 (R2 & R4): Real-Time Telegram Security Alert Engine.

Features:
- High-Performance Telegram Alerting Engine with HTML formatting.
- 4 Threat Levels with visual emojis: LOW (🟡), MEDIUM (🟠), HIGH (🔴), CRITICAL (💀).
- Attack Vector Mapping, rDNS resolution (non-blocking with cache), sample payload display.
- Emergency Bypass for CRITICAL threat events (instant push notification).
- 5-Minute Sliding Batching Digest Window (300s) to eliminate alert spam.
- Specialized Honeypot Trap Alert (Mẫu 2) for fake SSH :2222 and Telnet :23 captures.
- Clean Lifecycle (start/stop) with 0 ResourceWarning / unclosed asyncio task leaks.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import html
import logging
import re
import socket
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.config import settings
from app.core.http_client import http_client_manager
from app.core.telegram_formatter import TelegramFormatter

logger = logging.getLogger("app.services.security_alert_engine")

VN_TZ = timezone(timedelta(hours=7))

# Mapping vector attacks to descriptive titles
ATTACK_TYPE_LABELS: Dict[str, str] = {
    "ssh_brute_force": "🔐 SSH Brute Force",
    "sqli": "💉 Web Attack (SQL Injection)",
    "path_traversal": "📂 Web Attack (Path Traversal)",
    "xss": "⚡ Web Attack (Cross-Site Scripting)",
    "scanner_probe": "🤖 Web Scanner Probe",
    "scanner_path": "🔍 Web Recon Probing",
    "port_scan": "📡 Port Scan Burst",
    "ddos_rate_abuse": "🌊 DDoS / API Abuse",
    "honeypot_ssh": "🪤 Honeypot Trap (Fake SSH:2222)",
    "honeypot_telnet": "🪤 Honeypot Trap (Fake Telnet:23)",
}

THREAT_EMOJIS: Dict[str, str] = {
    "LOW": "🟡 LOW",
    "MEDIUM": "🟠 MEDIUM",
    "HIGH": "🔴 HIGH",
    "CRITICAL": "💀 CRITICAL",
}

THREAT_WEIGHTS: Dict[str, int] = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


@dataclass(slots=True)
class PendingAlertDigest:
    ip: str
    highest_threat_level: str
    first_seen: float
    last_seen: float
    event_counts: Counter[str] = field(default_factory=Counter)
    sample_payloads: List[str] = field(default_factory=list)
    credentials: List[Tuple[str, str]] = field(default_factory=list)
    actions_taken: Set[str] = field(default_factory=set)
    rdns_hostname: Optional[str] = None
    has_sent_critical_instant: bool = False


class SecurityAlertEngine:
    """
    Singleton Real-Time Security Alert Engine with Rate-Limiting & 5-Minute Digest.
    Receives intrusion events from SecurityMonitorService & HoneypotService,
    formats rich HTML Telegram alerts, and manages background flushes.
    """

    _instance: Optional["SecurityAlertEngine"] = None

    def __init__(
        self,
        telegram_bot: Optional[Any] = None,
        digest_window_seconds: float = 300.0,
        max_pending_digests: int = 1000,
        flush_interval_seconds: float = 10.0,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        http_client: Optional[Any] = None,
    ):
        self.telegram_bot = telegram_bot
        self.digest_window_seconds = digest_window_seconds
        self.max_pending_digests = max_pending_digests
        self.flush_interval_seconds = flush_interval_seconds
        self.token = token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")
        self._http_client = http_client

        self._pending_digests: Dict[str, PendingAlertDigest] = {}
        self._rdns_cache: Dict[str, Optional[str]] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None

        # Tracking for test assertions and monitoring
        self.sent_messages_history: List[str] = []

    @classmethod
    def get_instance(cls, **kwargs) -> "SecurityAlertEngine":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle Management
    # ──────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Starts the background flusher loop."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info(
                "[SecurityAlertEngine] Alert engine started (Digest window: %ds, Flush loop: %ds) ✓",
                int(self.digest_window_seconds),
                int(self.flush_interval_seconds),
            )

    async def stop(self) -> None:
        """Stops the engine cleanly and drains remaining pending digests."""
        async with self._lock:
            if not self._running:
                return
            self._running = False

            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()
                try:
                    await self._flush_task
                except asyncio.CancelledError:
                    pass
                self._flush_task = None

        # Drain remaining pending digests on shutdown without holding lock across network I/O
        await self._flush_all_pending()
        logger.info("[SecurityAlertEngine] Alert engine stopped cleanly (0 unclosed tasks) ✓")

    # ──────────────────────────────────────────────────────────────────────────
    # Event Ingestion Hooks
    # ──────────────────────────────────────────────────────────────────────────

    async def enqueue_threat_event(self, event: Any) -> None:
        """
        Receives ThreatEvent from SecurityMonitorService.
        Bypasses digest immediately if threat_level == CRITICAL.
        Otherwise batches into pending digest window.
        """
        ip = getattr(event, "ip", "unknown")
        raw_threat = getattr(event, "threat_level", "LOW")
        threat_str = raw_threat.value if hasattr(raw_threat, "value") else str(raw_threat).upper()
        if threat_str not in THREAT_WEIGHTS:
            threat_str = "LOW"

        attack_type = getattr(event, "attack_type", "unknown")
        raw_payload = getattr(event, "raw_payload", "")
        action_taken = getattr(event, "action_taken", "none")
        now = time.time()

        # Non-blocking rDNS lookup
        rdns = await self._resolve_rdns(ip)
        is_critical = threat_str == "CRITICAL"

        to_send_instant_msg: Optional[str] = None

        async with self._lock:
            digest = self._pending_digests.get(ip)
            if not digest:
                if len(self._pending_digests) >= self.max_pending_digests:
                    # Enforce bounded capacity to protect memory
                    oldest_ip = min(self._pending_digests, key=lambda k: self._pending_digests[k].first_seen)
                    oldest_digest = self._pending_digests.pop(oldest_ip, None)
                    if oldest_digest:
                        asyncio.create_task(self._safe_send_digest(oldest_digest))

                digest = PendingAlertDigest(
                    ip=ip,
                    highest_threat_level=threat_str,
                    first_seen=now,
                    last_seen=now,
                    rdns_hostname=rdns,
                )
                self._pending_digests[ip] = digest

            digest.last_seen = now
            digest.event_counts[attack_type] += 1
            if action_taken and action_taken != "none":
                digest.actions_taken.add(action_taken)

            if raw_payload and raw_payload not in digest.sample_payloads and len(digest.sample_payloads) < 3:
                digest.sample_payloads.append(raw_payload)

            # Escalate highest threat level if this event is more severe
            if THREAT_WEIGHTS.get(threat_str, 1) > THREAT_WEIGHTS.get(digest.highest_threat_level, 1):
                digest.highest_threat_level = threat_str

            # Emergency CRITICAL Bypass: Send instant alert if never sent before for this batch
            if is_critical and not digest.has_sent_critical_instant:
                digest.has_sent_critical_instant = True
                to_send_instant_msg = self._build_single_alert_message(event, rdns, threat_str)

        if to_send_instant_msg:
            await self._send_telegram(to_send_instant_msg)

    async def handle_honeypot_harvest(self, data: Dict[str, Any]) -> None:
        """
        Receives honeypot credential captures from HoneypotService.
        Triggers instant Honeypot Trap Alert (Mẫu 2) when attempts >= 3 or credentials present.
        """
        ip = str(data.get("ip", "unknown")).strip()
        service = str(data.get("service", "ssh")).strip().lower()
        creds = data.get("credentials", [])
        attempts = int(data.get("attempts", len(creds)))
        port = int(data.get("port", 2222 if service == "ssh" else 23))

        rdns = await self._resolve_rdns(ip)
        now = time.time()

        # Send instant Honeypot Trap notification
        msg = self._build_honeypot_trap_message(ip, port, service, creds, rdns, attempts)
        await self._send_telegram(msg)

        # Batch into digest for 5-minute summary tracking
        async with self._lock:
            digest = self._pending_digests.get(ip)
            if not digest:
                digest = PendingAlertDigest(
                    ip=ip,
                    highest_threat_level="CRITICAL",
                    first_seen=now,
                    last_seen=now,
                    rdns_hostname=rdns,
                    has_sent_critical_instant=True,
                )
                self._pending_digests[ip] = digest

            digest.last_seen = now
            digest.event_counts[f"honeypot_{service}"] += max(1, attempts)
            digest.actions_taken.add("honeypot_trap")
            digest.highest_threat_level = "CRITICAL"
            digest.has_sent_critical_instant = True
            for c in creds:
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    digest.credentials.append((str(c[0]), str(c[1])))
                elif isinstance(c, dict):
                    digest.credentials.append((str(c.get("username", "")), str(c.get("password", ""))))

    # ──────────────────────────────────────────────────────────────────────────
    # Background Flusher & Digest Processing
    # ──────────────────────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Periodic background task that checks and flushes expired digests."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval_seconds)
                await self._flush_expired_digests()
            except asyncio.CancelledError:
                break
            except Exception as ex:
                logger.error("[SecurityAlertEngine] Error in flush loop: %s", ex, exc_info=True)

    async def _flush_expired_digests(self) -> None:
        """Finds all IP digests older than digest_window_seconds and flushes them."""
        now = time.time()
        to_flush: List[PendingAlertDigest] = []

        async with self._lock:
            expired_ips = [
                ip for ip, d in self._pending_digests.items()
                if (now - d.first_seen) >= self.digest_window_seconds
            ]
            for ip in expired_ips:
                d = self._pending_digests.pop(ip, None)
                if d:
                    to_flush.append(d)

        for digest in to_flush:
            await self._safe_send_digest(digest)

    async def _flush_all_pending(self) -> None:
        """Flushes all pending digests regardless of age (used during shutdown)."""
        to_flush: List[PendingAlertDigest] = []
        async with self._lock:
            to_flush = list(self._pending_digests.values())
            self._pending_digests.clear()

        for digest in to_flush:
            await self._safe_send_digest(digest)

    async def _safe_send_digest(self, digest: PendingAlertDigest) -> None:
        """Evaluates whether to send a digest message and sends it safely."""
        total_hits = sum(digest.event_counts.values())

        # If only 1 event and that event already triggered an instant Critical alert, avoid duplicate
        if total_hits <= 1 and digest.has_sent_critical_instant:
            return

        if total_hits <= 0:
            return

        msg = self._build_digest_message(digest)
        await self._send_telegram(msg)

    # ──────────────────────────────────────────────────────────────────────────
    # Network Dispatch & Telegram Sender
    # ──────────────────────────────────────────────────────────────────────────

    async def _send_telegram(self, html_text: str) -> bool:
        """
        Sends HTML formatted message to Telegram.
        1. Uses TelegramBot instance if available.
        2. Falls back to shared httpx.AsyncClient or custom injected client.
        3. Falls back to plain text if Telegram API complains about entity parsing.
        """
        if not html_text:
            return False

        self.sent_messages_history.append(html_text)

        # Priority 1: TelegramBot instance
        if self.telegram_bot and hasattr(self.telegram_bot, "send_message"):
            target_chat = getattr(self.telegram_bot, "chat_id", self.chat_id)
            if target_chat:
                try:
                    res = await self.telegram_bot.send_message(target_chat, html_text, parse_mode="HTML")
                    if res:
                        return True
                except Exception as tb_ex:
                    logger.warning("[SecurityAlertEngine] TelegramBot send_message failed: %s, trying HTTP fallback", tb_ex)

        # Priority 2: Direct HTTP client via Telegram Bot API
        token = self.token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat_id = self.chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")

        if not token or not chat_id:
            logger.debug("[SecurityAlertEngine] Telegram credentials empty. Alert logged locally.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        client = self._http_client or http_client_manager.get_client()
        formatted_html = TelegramFormatter.format_for_telegram(html_text)

        payload = {
            "chat_id": chat_id,
            "text": formatted_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            res = await client.post(url, json=payload, timeout=10.0)
            if res.status_code == 200:
                return True

            # Fallback to plain text if Telegram's HTML entity parser fails
            if "parse" in res.text.lower() or "entities" in res.text.lower():
                plain_text = re.sub(r"</?[a-zA-Z0-9]+.*?>", "", formatted_html)
                fallback_payload = {
                    "chat_id": chat_id,
                    "text": plain_text,
                    "disable_web_page_preview": True,
                }
                res2 = await client.post(url, json=fallback_payload, timeout=10.0)
                return res2.status_code == 200

            logger.error("[SecurityAlertEngine] Telegram API returned HTTP %s: %s", res.status_code, res.text)
        except Exception as ex:
            logger.error("[SecurityAlertEngine] Network error sending Telegram alert: %s", ex)

        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Asynchronous Non-Blocking rDNS Resolver
    # ──────────────────────────────────────────────────────────────────────────

    async def _resolve_rdns(self, ip: str) -> Optional[str]:
        """Resolves reverse DNS PTR record safely with timeout and LRU caching."""
        if not ip or ip in ("unknown", "127.0.0.1", "::1"):
            return None

        if ip in self._rdns_cache:
            return self._rdns_cache[ip]

        # Enforce cache size limit
        if len(self._rdns_cache) > 2000:
            self._rdns_cache.clear()

        loop = asyncio.get_running_loop()
        try:
            hostname, _, _ = await asyncio.wait_for(
                loop.run_in_executor(None, socket.gethostbyaddr, ip),
                timeout=1.0,
            )
            clean_host = hostname.strip().lower()
            self._rdns_cache[ip] = clean_host
            return clean_host
        except Exception:
            self._rdns_cache[ip] = None
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Message Templating (HTML Mẫu 1, 2, 3)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_single_alert_message(
        self,
        event: Any,
        rdns: Optional[str] = None,
        threat_override: Optional[str] = None,
    ) -> str:
        """
        MẪU 1: Cảnh báo khẩn cấp tức thời (Single / Critical Alert).
        """
        ip = getattr(event, "ip", "unknown")
        raw_threat = threat_override or getattr(event, "threat_level", "LOW")
        threat_str = raw_threat.value if hasattr(raw_threat, "value") else str(raw_threat).upper()
        threat_badge = THREAT_EMOJIS.get(threat_str, f"⚠️ {threat_str}")

        attack_type = getattr(event, "attack_type", "unknown")
        attack_label = ATTACK_TYPE_LABELS.get(attack_type, f"🛡️ {attack_type}")
        raw_payload = getattr(event, "raw_payload", "")
        action_taken = getattr(event, "action_taken", "none")
        epoch_ts = getattr(event, "timestamp", time.time())

        dt = datetime.fromtimestamp(epoch_ts, tz=timezone.utc).astimezone(VN_TZ)
        time_str = dt.strftime("%H:%M:%S %d/%m/%Y (ICT)")

        rdns_part = f" <i>({html.escape(rdns)})</i>" if rdns else ""

        # Map action taken to friendly description
        action_desc = "Đang theo dõi lưu lượng"
        if action_taken == "iptables_drop" or "blocked" in action_taken:
            action_desc = "Đã tự động khóa IP trên Firewall máy chủ (iptables DROP, TTL 24h) 🔒"
        elif action_taken == "rate_limited":
            action_desc = "Đã áp dụng giới hạn tốc độ lưu lượng (Rate Limited: 10 req/s) ⏱️"
        elif action_taken == "whitelisted_veto":
            action_desc = "Bảo vệ VETO: IP thuộc danh sách Whitelist an toàn (Không chặn) 🛡️"

        payload_block = ""
        if raw_payload:
            escaped_payload = html.escape(str(raw_payload).strip()[:400])
            payload_block = f"\n📝 <b>Payload mẫu bị chặn:</b>\n<pre><code>{escaped_payload}</code></pre>\n"

        abuse_link = f"https://www.abuseipdb.com/check/{ip}"

        lines = [
            "🚨 <b>CẢNH BÁO AN NINH MÁY CHỦ — TIỂU BẢO BẢO GUARDIAN</b>\n",
            f"<b>Mức độ đe dọa:</b> <code>{threat_badge}</code>",
            f"🎯 <b>Vector tấn công:</b> <code>{attack_label}</code>",
            f"🌐 <b>IP Kẻ tấn công:</b> <code>{ip}</code>{rdns_part}",
            f"⏱️ <b>Thời gian phát hiện:</b> <code>{time_str}</code>",
            payload_block,
            f"🛡️ <b>Hành động tự động đã thực thi:</b>\n✅ <code>{action_desc}</code>\n",
            "💡 <b>Gợi ý cho Quản trị viên:</b>",
            f"• Kiểm tra iptables: <code>sudo iptables -L -n | grep {ip}</code>",
            f"• Tra cứu danh tiếng IP: <a href=\"{abuse_link}\">Tra cứu trên AbuseIPDB</a>",
        ]
        return "\n".join(lines).strip()

    def _build_honeypot_trap_message(
        self,
        ip: str,
        port: int,
        service: str,
        creds: List[Any],
        rdns: Optional[str] = None,
        attempts: int = 3,
    ) -> str:
        """
        MẪU 2: Cảnh báo bẫy Honeypot 'Kẻ Thất Bại' (Honeypot Trap Alert).
        """
        now = time.time()
        dt = datetime.fromtimestamp(now, tz=timezone.utc).astimezone(VN_TZ)
        time_str = dt.strftime("%H:%M:%S %d/%m/%Y (ICT)")

        rdns_part = f" <i>({html.escape(rdns)})</i>" if rdns else ""
        service_label = f"Fake SSH Listener (Port {port})" if service == "ssh" else f"Fake Telnet Listener (Port {port})"

        cred_lines: List[str] = []
        for idx, item in enumerate(creds[:5], 1):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                u, p = str(item[0]), str(item[1])
            elif isinstance(item, dict):
                u, p = str(item.get("username", "")), str(item.get("password", ""))
            else:
                u, p = str(item), ""
            cred_lines.append(f"{idx}. <code>{html.escape(u)}</code> : <code>{html.escape(p)}</code>")

        if not cred_lines:
            cred_lines.append("• <i>(Không có credentials văn bản rõ)</i>")

        abuse_link = f"https://www.abuseipdb.com/check/{ip}"

        lines = [
            "🪤 <b>BẪY HONEYPOT \"KẺ THẤT BẠI\" ĐÃ KÍCH HOẠT</b>\n",
            "💀 <b>Mức độ đe dọa:</b> <code>CRITICAL (Honeypot Breach Attempt)</code>",
            f"🎯 <b>Cổng giả lập:</b> <code>{service_label}</code>",
            f"🌐 <b>IP Kẻ xâm nhập:</b> <code>{ip}</code>{rdns_part}",
            f"⏱️ <b>Thời gian bắt giữ:</b> <code>{time_str}</code>",
            f"📊 <b>Số lần thử đăng nhập:</b> <code>{attempts} / 3 lần thất bại</code>\n",
            "🔑 <b>Thông tin đăng nhập hacker đã thử:</b>",
            "\n".join(cred_lines),
            "\n🎭 <b>Phản hồi trêu ngươi:</b>",
            "<i>\"💀 Kẻ thất bại. Lần sau cố gắng hơn nhé! - Tiểu Bảo Bảo Security Team 😂\"</i>\n",
            "🛡️ <b>Hành động phòng thủ:</b>",
            "✅ <code>Đã ngắt kết nối socket & tự động khóa IP 24h trên Firewall máy chủ 🔒</code>\n",
            "💡 <b>Gợi ý cho Quản trị viên:</b>",
            f"• Lệnh kiểm tra: <code>sudo iptables -L -n | grep {ip}</code>",
            f"• Tra cứu AbuseIPDB: <a href=\"{abuse_link}\">Tra cứu AbuseIPDB</a>",
        ]
        return "\n".join(lines).strip()

    def _build_digest_message(self, digest: PendingAlertDigest) -> str:
        """
        MẪU 3: Báo cáo tổng hợp định kỳ 5 phút (Digest Alert).
        """
        ip = digest.ip
        rdns_part = f" <i>({html.escape(digest.rdns_hostname)})</i>" if digest.rdns_hostname else ""
        total_events = sum(digest.event_counts.values())

        threat_badge = THREAT_EMOJIS.get(digest.highest_threat_level, f"🔴 {digest.highest_threat_level}")

        dt_first = datetime.fromtimestamp(digest.first_seen, tz=timezone.utc).astimezone(VN_TZ)
        dt_last = datetime.fromtimestamp(digest.last_seen, tz=timezone.utc).astimezone(VN_TZ)
        time_range = f"{dt_first.strftime('%H:%M:%S')} ➔ {dt_last.strftime('%H:%M:%S %d/%m/%Y')}"

        type_breakdown: List[str] = []
        for atype, cnt in digest.event_counts.most_common():
            label = ATTACK_TYPE_LABELS.get(atype, atype)
            type_breakdown.append(f"• <code>{label}</code>: {cnt} lần")

        payload_lines: List[str] = []
        for p in digest.sample_payloads[:3]:
            escaped_p = html.escape(str(p).strip().replace("\n", " ")[:120])
            payload_lines.append(f"• <code>{escaped_p}</code>")

        action_summary = "Đang theo dõi lưu lượng trên máy chủ"
        if "iptables_drop" in digest.actions_taken or "honeypot_trap" in digest.actions_taken:
            action_summary = "Địa chỉ IP hiện đang bị khóa trên iptables (SECURITY_GUARDIAN chain, TTL 24h) 🔒"
        elif "rate_limited" in digest.actions_taken:
            action_summary = "Địa chỉ IP đang bị áp dụng chính sách giới hạn tốc độ (Rate Limited) ⏱️"

        payload_section = ""
        if payload_lines:
            payload_section = "\n📝 <b>Mẫu payload tiêu biểu ghi nhận:</b>\n" + "\n".join(payload_lines) + "\n"

        abuse_link = f"https://www.abuseipdb.com/check/{ip}"

        lines = [
            "🛡️ <b>TỔNG HỢP CẢNH BÁO AN NINH (DIGEST 5 PHÚT)</b>\n",
            "<i>Tiểu Bảo Bảo đã gom nhóm các cuộc tấn công từ IP trong 5 phút qua để tránh làm phiền anh:</i>\n",
            f"🌐 <b>IP Kẻ tấn công:</b> <code>{ip}</code>{rdns_part}",
            f"<b>Mức đe dọa cao nhất:</b> <code>{threat_badge}</code>",
            f"🔢 <b>Tổng số cuộc tấn công:</b> <code>{total_events} sự kiện</code>",
            f"⏱️ <b>Khoảng thời gian:</b> <code>{time_range}</code>\n",
            "📊 <b>Phân loại chi tiết các đợt tấn công:</b>",
            "\n".join(type_breakdown) if type_breakdown else "• <code>Không xác định</code>: 1 lần",
            payload_section,
            "🛡️ <b>Trạng thái phòng vệ máy chủ:</b>",
            f"✅ <code>{action_summary}</code>\n",
            "💡 <b>Gợi ý cho Quản trị viên:</b>",
            f"• Kiểm tra trạng thái: <code>sudo iptables -L -n | grep {ip}</code>",
            f"• Tra cứu lịch sử IP: <a href=\"{abuse_link}\">Tra cứu AbuseIPDB</a>",
        ]
        return "\n".join(lines).strip()
