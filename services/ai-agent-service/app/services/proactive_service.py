"""
ProactiveIntelligenceService — Phase 5B: Curiosity-Driven Server Health Scanner.

Inspired by the human brain's curiosity-driven exploration mechanism:
SRE engineers don't just react to alerts — they proactively scan for anomalies
BEFORE they become incidents. This service replicates that behavior.

Runs as a background asyncio loop. Every SCAN_INTERVAL_SECONDS it:
1. SSH into kirito-server and collect key metrics
2. Compare against known thresholds
3. If anomaly detected AND cooldown has passed → send Telegram alert

Anomalies checked:
  - Disk usage > 85% on any mount
  - SSL certificate expiring within 14 days
  - Container restart count > 3 in 1 hour
  - Memory usage > 90%
  - OOM-killed processes in last 24h
"""
import asyncio
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Scan every 6 hours (21600s). Adjust in .env via PROACTIVE_SCAN_INTERVAL_SECONDS.
_DEFAULT_SCAN_INTERVAL = 21600

# Thresholds
_DISK_ALERT_PCT = 85
_MEM_ALERT_PCT  = 90
_SSL_WARN_DAYS  = 14
_CONTAINER_RESTART_THRESHOLD = 3


class ProactiveIntelligenceService:
    """
    Background service that proactively scans server health like an SRE on duty.
    Wires into: ssh_client, memory_service, telegram_bot.
    """

    def __init__(
        self,
        ssh_client: Any,
        memory_service: Any,
        telegram_bot: Any,
        scan_interval: int = _DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._ssh = ssh_client
        self._mem = memory_service
        self._tg  = telegram_bot
        self._interval = scan_interval
        self._running = False

    async def start(self) -> None:
        """Start the background proactive scan loop."""
        self._running = True
        logger.info("[Proactive] 🔍 Curiosity-Driven Scanner started (interval=%ds).", self._interval)
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if self._running:
                    await self._run_scan_cycle()
            except asyncio.CancelledError:
                logger.info("[Proactive] Scanner loop cancelled.")
                break
            except Exception as e:
                logger.error("[Proactive] Unexpected error in scan cycle: %s", e)

    def stop(self) -> None:
        self._running = False

    # ──────────────────────────────────────────────────────────────────────────

    async def _run_scan_cycle(self) -> None:
        """Single scan cycle — runs all checks, sends alerts for anomalies."""
        logger.info("[Proactive] Running health scan cycle...")
        alerts: list[str] = []

        # Run all checks concurrently for speed
        disk_alert, mem_alert, ssl_alert, oom_alert, restart_alert = await asyncio.gather(
            self._check_disk(),
            self._check_memory(),
            self._check_ssl_certs(),
            self._check_oom_kills(),
            self._check_container_restarts(),
            return_exceptions=True,
        )

        for result in [disk_alert, mem_alert, ssl_alert, oom_alert, restart_alert]:
            if isinstance(result, str) and result:
                alerts.append(result)

        if not alerts:
            logger.info("[Proactive] ✅ All checks passed. No anomalies detected.")
            return

        # Compose and send Telegram alert
        msg = (
            "🔍 <b>Tiểu Bảo Bảo — Báo cáo quét chủ động</b>\n"
            f"<i>Em vừa quét sức khỏe hệ thống và phát hiện {len(alerts)} vấn đề:</i>\n\n"
            + "\n\n".join(f"• {a}" for a in alerts)
            + "\n\n<i>Anh Mạnh có muốn em xử lý ngay không?</i>"
        )

        if self._tg and hasattr(self._tg, "send_message"):
            chat_id = getattr(self._tg, "chat_id", "")
            if chat_id:
                await self._tg.send_message(chat_id, msg)
                logger.info("[Proactive] 📢 Sent %d alert(s) to Telegram.", len(alerts))

        # Record as high-salience episode
        if self._mem and len(alerts) > 0:
            summary = f"Proactive scan: {len(alerts)} anomaly(ies) detected — " + "; ".join(a[:80] for a in alerts[:3])
            asyncio.create_task(self._mem.record_episode(
                event_summary=summary,
                event_type="observation",
                severity="high" if len(alerts) >= 2 else "medium",
                salience_score=0.75 if len(alerts) >= 2 else 0.6,
                tags=["proactive_scan", "auto_detected"],
            ))

    # ── Individual Checks ────────────────────────────────────────────────────

    async def _check_disk(self) -> str:
        """Check disk usage on all mounts. Alert if any > threshold."""
        try:
            result = await self._ssh.run_command("df -h --output=pcent,target | tail -n +2")
            if not result:
                return ""

            critical_mounts = []
            for line in result.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    pct_str, mount = parts[0].rstrip("%"), parts[1]
                    if pct_str.isdigit() and int(pct_str) >= _DISK_ALERT_PCT:
                        critical_mounts.append(f"<code>{mount}</code>: {pct_str}%")

            if not critical_mounts:
                return ""

            check_key = "disk:high_usage"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=6)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, "; ".join(critical_mounts), send_alert=True)
            return f"💽 <b>Ổ đĩa sắp đầy:</b>\n  " + "\n  ".join(critical_mounts)
        except Exception as e:
            logger.debug("[Proactive] _check_disk error: %s", e)
            return ""

    async def _check_memory(self) -> str:
        """Check RAM usage. Alert if > threshold."""
        try:
            result = await self._ssh.run_command(
                "free | awk 'NR==2{printf \"%.0f\", $3*100/$2}'"
            )
            if not result or not result.strip().isdigit():
                return ""

            pct = int(result.strip())
            if pct < _MEM_ALERT_PCT:
                return ""

            check_key = "memory:high_usage"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=2)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, f"{pct}%", send_alert=True)
            return f"🧠 <b>RAM đang cao:</b> {pct}% đã sử dụng (ngưỡng cảnh báo: {_MEM_ALERT_PCT}%)"
        except Exception as e:
            logger.debug("[Proactive] _check_memory error: %s", e)
            return ""

    async def _check_ssl_certs(self) -> str:
        """Check SSL cert expiry for configured domains."""
        try:
            # Get list of domains from nginx config or a known list
            result = await self._ssh.run_command(
                "grep -rh 'server_name' /etc/nginx/sites-enabled/ 2>/dev/null "
                "| awk '{print $2}' | tr -d ';' | grep '\\.' | sort -u | head -10"
            )
            if not result or not result.strip():
                return ""

            domains = [d.strip() for d in result.splitlines() if d.strip() and "_" not in d]
            expiring = []

            for domain in domains[:5]:  # Cap at 5 to avoid long SSH chains
                cert_check = await self._ssh.run_command(
                    f"echo | timeout 5 openssl s_client -connect {domain}:443 -servername {domain} 2>/dev/null "
                    f"| openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2"
                )
                if not cert_check or not cert_check.strip():
                    continue

                # Parse expiry date
                from datetime import datetime
                try:
                    exp = datetime.strptime(cert_check.strip(), "%b %d %H:%M:%S %Y %Z")
                    days_left = (exp - datetime.utcnow()).days
                    if days_left <= _SSL_WARN_DAYS:
                        expiring.append(f"<code>{domain}</code>: còn <b>{days_left} ngày</b>")
                except ValueError:
                    pass

            if not expiring:
                return ""

            check_key = "ssl:expiring_soon"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=24)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, "; ".join(expiring), send_alert=True)
            return f"🔒 <b>SSL cert sắp hết hạn:</b>\n  " + "\n  ".join(expiring)
        except Exception as e:
            logger.debug("[Proactive] _check_ssl_certs error: %s", e)
            return ""

    async def _check_oom_kills(self) -> str:
        """Check for OOM-killed processes in last 24 hours."""
        try:
            result = await self._ssh.run_command(
                "journalctl -k --since '24h ago' 2>/dev/null | grep -i 'oom\\|killed process' | wc -l"
            )
            if not result or not result.strip().isdigit():
                return ""

            count = int(result.strip())
            if count == 0:
                return ""

            check_key = "oom:kills_24h"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=4)
            if not should_alert:
                return ""

            # Get last OOM victim for context
            victim = await self._ssh.run_command(
                "journalctl -k --since '24h ago' 2>/dev/null "
                "| grep -i 'killed process' | tail -1 | awk '{print $NF}'"
            )
            victim_str = f" (gần nhất: <code>{victim.strip()[:50]}</code>)" if victim and victim.strip() else ""

            await self._mem.upsert_proactive_check(check_key, str(count), send_alert=True)
            return (
                f"⚡ <b>OOM Kill phát hiện trong 24h qua:</b> {count} lần{victim_str}\n"
                f"  → Có thể cần tăng RAM limit cho container"
            )
        except Exception as e:
            logger.debug("[Proactive] _check_oom_kills error: %s", e)
            return ""

    async def _check_container_restarts(self) -> str:
        """Check for containers with high restart count."""
        try:
            result = await self._ssh.run_command(
                "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null "
                "| grep -i 'restart' | head -5"
            )
            if not result or not result.strip():
                # Also check restart count via inspect
                result2 = await self._ssh.run_command(
                    "docker ps -q 2>/dev/null | xargs -I{} docker inspect {} "
                    "--format '{{.Name}} {{.RestartCount}}' 2>/dev/null "
                    f"| awk '$2>={_CONTAINER_RESTART_THRESHOLD}'"
                )
                if not result2 or not result2.strip():
                    return ""
                result = result2

            check_key = "docker:high_restarts"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=4)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, result.strip()[:200], send_alert=True)
            containers = result.strip()[:300]
            return f"🐳 <b>Container đang restart bất thường:</b>\n<pre>{containers}</pre>"
        except Exception as e:
            logger.debug("[Proactive] _check_container_restarts error: %s", e)
            return ""
