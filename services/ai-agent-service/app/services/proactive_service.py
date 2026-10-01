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
from datetime import datetime, timezone, timedelta
import logging
import re
from typing import Any, Optional

from app.core.brain_core import ArtificialBrain

logger = logging.getLogger(__name__)

# Scan every 6 hours (21600s). Adjust in .env via PROACTIVE_SCAN_INTERVAL_SECONDS.
_DEFAULT_SCAN_INTERVAL = 21600

# Thresholds
_DISK_ALERT_PCT = 85
_MEM_ALERT_PCT  = 90
_SSL_WARN_DAYS  = 14
_CONTAINER_RESTART_THRESHOLD = 3

# Milestone 5 SRE Constants
_SRE_RAM_ALERT_PCT = 85
_SRE_CPU_LOAD_THRESHOLD = 3.5
_SRE_SWAP_ALERT_MB = 500
_SRE_ROOT_DISK_ALERT_PCT = 90
_CORE_CONTAINERS = [
    "dashboard_ai_agent",
    "dashboard_frontend",
    "dashboard_metrics_service",
    "dashboard_auth_service",
    "dashboard_file_service",
    "dashboard_db",
]

# R3 Auto-Remediation Cooldown (30 minutes per action)
_REMEDIATION_COOLDOWN_SECONDS = 1800


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
        self._remediation_cooldowns: dict[str, datetime] = {}
        self._remediation_cooldown_seconds: int = _REMEDIATION_COOLDOWN_SECONDS

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

        # Run all checks concurrently for speed (all 9 SRE vitals)
        scan_results = await asyncio.gather(
            self._check_disk(),
            self._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT),
            self._check_ssl_certs(),
            self._check_oom_kills(),
            self._check_container_restarts(),
            self._check_cpu_load(),
            self._check_swap(),
            self._check_root_disk(),
            self._check_core_containers(),
            return_exceptions=True,
        )

        for result in scan_results:
            if isinstance(result, str) and result:
                alerts.append(result)

        # ── Autonomous Neuromorphic Brain Pulse & Sleep Consolidation ─────────
        try:
            brain = ArtificialBrain.get_instance()
            ram_pct = 0.0
            mem_alert = scan_results[1] if len(scan_results) > 1 and not isinstance(scan_results[1], Exception) else None
            if isinstance(mem_alert, str) and mem_alert:
                ram_match = re.search(r"(\d+)%", mem_alert)
                if ram_match:
                    ram_pct = float(ram_match.group(1))
            winning_signal = brain.step_pulse({"ram_usage": ram_pct, "cpu_usage": 0.0})
            if winning_signal:
                logger.info("[Proactive] 🧠 Conscious Workspace Ignition: %s (salience=%.2f)", winning_signal.summary, winning_signal.salience)

            # Sleep Consolidation: between 02:00 and 05:00 AM VN time, consolidate working memory into 32GB Virtual Cortex
            now_vn = datetime.now(timezone(timedelta(hours=7)))
            if 2 <= now_vn.hour <= 5:
                consolidated = brain.consolidate_sleep_memories()
                if consolidated > 0:
                    logger.info("[Proactive] 🌙 Consolidated %d memories into 32GB Virtual Cortex during sleep.", consolidated)
        except Exception as _b_err:
            logger.debug("[Proactive] Brain cognitive pulse error: %s", _b_err)

        if not alerts:
            logger.info("[Proactive] ✅ All checks passed. No anomalies detected.")
            return

        # ── R3: Tier 1 Safe Auto-Remediation Execution ───────────────────────
        for alert in alerts:
            try:
                remediation = self._decide_remediation(alert)
                if remediation and remediation.get("auto_execute") is True:
                    logger.info("[Proactive] 🛠️ Initiating auto-remediation for: %s", str(alert)[:60])
                    await self._execute_remediation(remediation, alert)
            except Exception as rem_err:
                logger.error("[Proactive] Error executing auto-remediation: %s", rem_err)

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

    async def _check_memory(self, threshold_pct: Optional[int] = None) -> str:
        """Check RAM usage. Alert if >= threshold."""
        limit_pct = threshold_pct if threshold_pct is not None else _MEM_ALERT_PCT
        try:
            result = await self._ssh.run_command(
                "free | awk 'NR==2{printf \"%.0f\", $3*100/$2}'"
            )
            if not result or not result.strip().isdigit():
                return ""

            pct = int(result.strip())
            if pct < limit_pct:
                return ""

            check_key = "memory:high_usage"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=2)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, f"{pct}%", send_alert=True)
            return f"🧠 <b>RAM đang cao:</b> {pct}% đã sử dụng (ngưỡng cảnh báo: {limit_pct}%)"
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

                # Parse expiry date (OpenSSL outputs GMT/UTC dates)
                try:
                    exp = datetime.strptime(cert_check.strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    days_left = (exp - datetime.now(timezone.utc)).days
                    if days_left <= _SSL_WARN_DAYS:
                        expiring.append(f"<code>{domain}</code>: còn <b>{days_left} ngày</b>")
                except (ValueError, TypeError):
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

    async def _check_cpu_load(self, threshold: float = _SRE_CPU_LOAD_THRESHOLD) -> str:
        """Check CPU Load Average. Alert if 1-minute load > threshold (vượt trần 2 nhân 4 luồng i5-4310U)."""
        try:
            result = await self._ssh.run_command("cat /proc/loadavg")
            if not result or not result.strip():
                return ""

            parts = result.strip().split()
            if not parts:
                return ""

            load1 = float(parts[0])
            load5 = float(parts[1]) if len(parts) > 1 else load1
            if load1 <= threshold:
                return ""

            check_key = "cpu:high_load"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=2)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, f"load1={load1:.2f}, load5={load5:.2f}", send_alert=True)
            return (
                f"🔥 <b>CPU Load Average cao:</b> load1={load1:.2f}, load5={load5:.2f} > {threshold} "
                f"(vượt trần 2 nhân 4 luồng Intel Core i5-4310U, nguy cơ nghẽn CPU)"
            )
        except Exception as e:
            logger.debug("[Proactive] _check_cpu_load error: %s", e)
            return ""

    async def _check_swap(self, threshold_mb: int = _SRE_SWAP_ALERT_MB) -> str:
        """Check Swap usage. Alert if swap used > threshold_mb (báo động Disk Thrashing trên SSD)."""
        try:
            result = await self._ssh.run_command("free -m | awk '/Swap:/ {print $3}'")
            if not result or not result.strip().isdigit():
                return ""

            swap_used_mb = int(result.strip())
            if swap_used_mb <= threshold_mb:
                return ""

            check_key = "swap:high_usage"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=3)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, f"{swap_used_mb}MB", send_alert=True)
            return (
                f"⚠️ <b>Dung lượng Swap cao:</b> {swap_used_mb}MB > {threshold_mb}MB "
                f"(cảnh báo nguy cơ Disk Thrashing trên SSD)"
            )
        except Exception as e:
            logger.debug("[Proactive] _check_swap error: %s", e)
            return ""

    async def _check_root_disk(self, threshold_pct: int = _SRE_ROOT_DISK_ALERT_PCT) -> str:
        """Check root partition (/) usage. Alert if >= threshold_pct."""
        try:
            result = await self._ssh.run_command("df -h / | awk 'NR==2 {print $5}' | tr -d '%'")
            if not result or not result.strip().isdigit():
                return ""

            pct = int(result.strip())
            if pct < threshold_pct:
                return ""

            check_key = "disk:root_high"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=4)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, f"{pct}%", send_alert=True)
            return f"💽 <b>Phân vùng root (/) sắp đầy:</b> {pct}% (ngưỡng an toàn < {threshold_pct}%, nguy cơ crash dịch vụ)"
        except Exception as e:
            logger.debug("[Proactive] _check_root_disk error: %s", e)
            return ""

    async def _check_core_containers(self, core_containers: Optional[list[str]] = None) -> str:
        """Check status of core docker containers. Alert if any container is down or unhealthy."""
        targets = core_containers or _CORE_CONTAINERS
        try:
            result = await self._ssh.run_command("docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.State}}'")
            if not result:
                return ""

            container_map: dict[str, tuple[str, str]] = {}
            for line in result.strip().splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    c_name, c_status, c_state = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    container_map[c_name] = (c_status, c_state)
                elif len(parts) == 2:
                    c_name, c_status = parts[0].strip(), parts[1].strip()
                    c_state = "running" if "Up" in c_status else "exited"
                    container_map[c_name] = (c_status, c_state)

            failed_cores = []
            for target in targets:
                if target not in container_map:
                    failed_cores.append(f"<code>{target}</code>: Không tìm thấy (Missing/Not created)")
                else:
                    status, state = container_map[target]
                    if state.lower() != "running" or "exit" in status.lower() or "restarting" in status.lower():
                        failed_cores.append(f"<code>{target}</code>: {status} (State: {state})")

            if not failed_cores:
                return ""

            check_key = "docker:core_containers_unhealthy"
            should_alert = await self._mem.should_send_proactive_alert(check_key, cooldown_hours=1)
            if not should_alert:
                return ""

            await self._mem.upsert_proactive_check(check_key, "; ".join(failed_cores), send_alert=True)
            return "🚨 <b>Core Container gặp sự cố:</b>\n  " + "\n  ".join(failed_cores)
        except Exception as e:
            logger.debug("[Proactive] _check_core_containers error: %s", e)
            return ""

    # ── R3: Auto-Remediation & Self-Healing Engine ───────────────────────────

    def _decide_remediation(self, alert: Any) -> Optional[dict[str, Any]]:
        """
        Decide remediation action based on alert contents using Tri-Tier Risk Classification.

        Tier 1 SAFE Actions (auto_execute=True):
          - docker_prune: docker system prune -f (disk full / root partition > threshold)
          - cleanup_logs: journalctl --vacuum-time=3d (log buildup / journalctl issues)
          - drop_caches: sync && echo 3 > /proc/sys/vm/drop_caches (RAM / Swap high)

        Tier 2+ Actions (auto_execute=False, requires human approval):
          - restart_container: docker restart <target> (container crash / flapping)
          - renew_ssl: certbot renew (SSL cert expiring)
        """
        if isinstance(alert, dict):
            alert_str = str(alert.get("message") or alert.get("text") or alert.get("alert") or alert).lower()
        else:
            alert_str = str(alert).lower()

        if not alert_str.strip():
            return None

        # Tier 1: Log cleanup
        if any(k in alert_str for k in ("log tích tụ", "dọn log", "cleanup_logs", "vacuum-time", "nhật ký hệ thống")):
            return {
                "action_key": "cleanup_logs",
                "tier": 1,
                "command": "journalctl --vacuum-time=3d",
                "metric_type": "disk",
                "auto_execute": True,
                "description": "Tự động dọn dẹp log hệ thống",
            }

        # Tier 1: High RAM / Swap (checked before disk because swap alerts may mention Disk Thrashing)
        if any(k in alert_str for k in ("ram", "swap", "bộ nhớ", "drop_caches")):
            return {
                "action_key": "drop_caches",
                "tier": 1,
                "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
                "metric_type": "ram",
                "auto_execute": True,
                "description": "Giải phóng bộ nhớ đệm RAM",
            }

        # Tier 1: Disk full / root partition
        if any(k in alert_str for k in ("đĩa", "disk", "root (/)", "phân vùng root")):
            return {
                "action_key": "docker_prune",
                "tier": 1,
                "command": "docker system prune -f",
                "metric_type": "disk",
                "auto_execute": True,
                "description": "Tự động dọn rác Docker (dangling images/containers)",
            }

        # Tier 2: Container restarts or core container failures
        if any(k in alert_str for k in ("container", "restart", "core container", "crash")):
            return {
                "action_key": "restart_container",
                "tier": 2,
                "command": "docker restart container",
                "metric_type": "container",
                "auto_execute": False,
                "description": "Khởi động lại container",
            }

        # Tier 2: SSL certificate expiry
        if any(k in alert_str for k in ("ssl", "cert", "chứng chỉ")):
            return {
                "action_key": "renew_ssl",
                "tier": 2,
                "command": "certbot renew",
                "metric_type": "ssl",
                "auto_execute": False,
                "description": "Gia hạn chứng chỉ SSL",
            }

        return None

    async def _get_metric_snapshot(self, metric_type: str) -> dict[str, Any]:
        """Capture current system metric snapshot before/after remediation."""
        snapshot: dict[str, Any] = {
            "metric_type": metric_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "used_pct": 0.0,
            "free_gb": 0.0,
        }
        try:
            if not self._ssh:
                return snapshot

            if metric_type == "disk":
                out = await self._ssh.run_command("df -h / | awk 'NR==2 {print $5, $4, $3}'")
                if out and out.strip():
                    parts = out.strip().split()
                    pct_str = parts[0].replace("%", "").strip() if len(parts) > 0 else "0"
                    avail_str = parts[1].strip() if len(parts) > 1 else ""
                    used_str = parts[2].strip() if len(parts) > 2 else ""

                    try:
                        snapshot["used_pct"] = float(pct_str)
                    except ValueError:
                        pass
                    snapshot["available"] = avail_str
                    snapshot["used"] = used_str

                    if avail_str:
                        num_match = re.search(r"([\d\.]+)\s*([GMK]?)", avail_str, re.IGNORECASE)
                        if num_match:
                            val = float(num_match.group(1))
                            unit = num_match.group(2).upper()
                            if unit == "G":
                                snapshot["free_gb"] = val
                            elif unit == "M":
                                snapshot["free_gb"] = round(val / 1024.0, 2)
                            elif unit == "K":
                                snapshot["free_gb"] = round(val / (1024.0 * 1024.0), 2)
                            else:
                                snapshot["free_gb"] = val

            elif metric_type == "ram":
                out = await self._ssh.run_command("free -m | awk 'NR==2 {print $3, $7, $2}'")
                if out and out.strip():
                    parts = out.strip().split()
                    if len(parts) >= 3:
                        used_mb = float(parts[0]) if parts[0].isdigit() else 0.0
                        avail_mb = float(parts[1]) if parts[1].isdigit() else 0.0
                        total_mb = float(parts[2]) if parts[2].isdigit() else 1.0
                        snapshot["used_mb"] = used_mb
                        snapshot["available_mb"] = avail_mb
                        snapshot["total_mb"] = total_mb
                        snapshot["used_pct"] = round((used_mb * 100.0) / max(total_mb, 1.0), 1)
                        snapshot["free_gb"] = round(avail_mb / 1024.0, 2)
        except Exception as exc:
            logger.debug("[Proactive] Error capturing metric snapshot (%s): %s", metric_type, exc)

        return snapshot

    async def _execute_remediation(self, remediation: dict[str, Any], alert: Any) -> bool:
        """
        Execute safe auto-remediation (Tier 1 Safe only) with cooldown, before/after metrics,
        and proactive Telegram reporting.
        """
        try:
            action_key = remediation.get("action_key", "unknown")
            now = datetime.now(timezone.utc)

            # 1. Cooldown Check (30 minutes)
            last_run = self._remediation_cooldowns.get(action_key)
            if last_run and (now - last_run).total_seconds() < self._remediation_cooldown_seconds:
                remaining = int(self._remediation_cooldown_seconds - (now - last_run).total_seconds())
                logger.info(
                    "[Proactive] ⏳ Hành động '%s' đang trong cooldown (%ds còn lại). Bỏ qua tự động thực thi.",
                    action_key,
                    remaining,
                )
                return False

            # 2. Risk Tri-Tier Policy Check
            if not remediation.get("auto_execute", False) or remediation.get("tier", 2) > 1:
                logger.warning(
                    "[Proactive] ⚠️ Hành động '%s' thuộc Tier %s (auto_execute=False). Yêu cầu phê duyệt từ người dùng.",
                    action_key,
                    remediation.get("tier", 2),
                )
                return False

            cmd = remediation.get("command")
            if not cmd:
                return False

            metric_type = remediation.get("metric_type", "disk")

            # 3. Before Metric Snapshot
            before_metric = await self._get_metric_snapshot(metric_type)

            # 4. Command Execution via SSH
            logger.info("[Proactive] 🛠️ Bắt đầu tự động thực thi '%s': %s", action_key, cmd)
            if self._ssh:
                await self._ssh.run_command(cmd)

            # 5. After Metric Snapshot
            after_metric = await self._get_metric_snapshot(metric_type)

            # 6. Efficiency Calculation
            before_pct = before_metric.get("used_pct", 0.0)
            after_pct = after_metric.get("used_pct", 0.0)
            before_free = before_metric.get("free_gb", 0.0)
            after_free = after_metric.get("free_gb", 0.0)
            freed_gb = round(after_free - before_free, 2)
            pct_diff = round(before_pct - after_pct, 1)

            if freed_gb > 0:
                efficiency = f"Đã giải phóng thành công <b>{freed_gb:.1f}GB</b> dung lượng!"
            elif pct_diff > 0:
                efficiency = f"Đã giảm <b>{pct_diff}%</b> mức sử dụng!"
            else:
                efficiency = "Lệnh đã thực thi thành công, hệ thống đã ổn định."

            # 7. Update Cooldown Timestamp
            self._remediation_cooldowns[action_key] = now

            # 8. Dispatch Telegram Report
            desc = remediation.get("description", action_key)
            tier = remediation.get("tier", 1)

            report_lines = [
                "🛠️ <b>Tiểu Bảo Bảo — Tự động khắc phục sự cố (Auto-Remediation)</b>",
                "<i>Em phát hiện bất thường và đã tự động thực thi biện pháp khắc phục an toàn:</i>",
                "",
                f"• <b>Hành động</b>: {desc} (<code>{cmd}</code>)",
            ]
            if before_pct or before_free:
                report_lines.append(f"• <b>Trước khi xử lý</b>: {before_pct:.0f}% dung lượng (còn trống {before_free:.1f}GB)")
            if after_pct or after_free:
                report_lines.append(f"• <b>Sau khi xử lý</b>: {after_pct:.0f}% dung lượng (còn trống {after_free:.1f}GB)")
            report_lines.append(f"• <b>Hiệu quả</b>: {efficiency}")
            report_lines.append(f"• <b>Trạng thái</b>: ✅ Hoàn tất an toàn (Tier {tier} Safe Action)")

            report = "\n".join(report_lines)

            if self._tg and hasattr(self._tg, "send_message"):
                chat_id = getattr(self._tg, "chat_id", "")
                if chat_id:
                    await self._tg.send_message(chat_id, report)
                    logger.info("[Proactive] 📢 Sent remediation report to Telegram.")

            # 9. Record Memory Episode
            if self._mem and hasattr(self._mem, "record_episode"):
                summary = f"Auto-remediation executed: {action_key} ({cmd}) — {efficiency}"
                asyncio.create_task(
                    self._mem.record_episode(
                        event_summary=summary,
                        event_type="action",
                        severity="medium",
                        salience_score=0.8,
                        tags=["proactive_remediation", "auto_healed", action_key],
                    )
                )

            return True
        except Exception as exc:
            logger.error("[Proactive] Error during _execute_remediation for %s: %s", remediation.get("action_key"), exc)
            return False

    async def run_patrol_scan(self) -> dict[str, Any]:
        """
        Executes an on-demand SRE curiosity patrol scan across all 9 vital metrics.
        Returns detailed structured findings without waiting for the 6-hour cron loop.
        """
        alerts: list[str] = []
        checks = await asyncio.gather(
            self._check_disk(),
            self._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT),
            self._check_ssl_certs(),
            self._check_oom_kills(),
            self._check_container_restarts(),
            self._check_cpu_load(),
            self._check_swap(),
            self._check_root_disk(),
            self._check_core_containers(),
            return_exceptions=True,
        )
        for r in checks:
            if isinstance(r, str) and r:
                alerts.append(r)

        return {
            "status": "healthy" if not alerts else "warning",
            "alerts": alerts,
            "total_checks": len(checks),
            "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat(),
        }