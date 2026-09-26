"""
app/services/server_monitor_service.py — Autonomous Server Health Monitor & SRE Service (R2).

Manages 5-dimensional server diagnostics, service status probing, safe service restarting,
and error-aware log tailing:
- get_system_health_report: 5-dimensional server health report (CPU, RAM, Disk, Docker, Network).
- check_service_status: Probes docker container or systemd service state.
- restart_service: Safe service restart with required confirmation token for production services.
- tail_service_logs: Tails recent logs with intelligent error parsing and summarization.

Architecture:
- Reuses SshClient from `app.core.ssh_client` for zero-downtime execution over LAN/Ngrok tunnels.
- Strictly adheres to security boundary definitions in `app.core.security`.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

# Production services requiring strict confirmation before restart (Tier 2 Reversible)
PROTECTED_PRODUCTION_SERVICES: Set[str] = {
    "dashboard_ai_agent",
    "dashboard_server_api",
    "dashboard_client",
    "postgres",
    "postgresql",
    "redis",
    "traefik",
    "nginx",
}

# Regex for validating safe service names (prevents command injection)
SERVICE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.@]+$")

# Error and warning patterns for log parsing
LOG_ERROR_PATTERN = re.compile(
    r"\b(error|exception|fatal|panic|failed|critical|traceback|oom|segfault)\b",
    re.IGNORECASE,
)
LOG_WARN_PATTERN = re.compile(r"\b(warn|warning)\b", re.IGNORECASE)


class ServerMonitorService:
    """
    Autonomous Server Monitor & SRE Diagnostician.
    Connects to the host server via SshClient to gather system metrics,
    inspect containers, restart services, and parse log streams.
    """

    def __init__(self, ssh_client: Optional[SshClient] = None):
        self._ssh_client = ssh_client

    @property
    def ssh_client(self) -> SshClient:
        if self._ssh_client is None:
            self._ssh_client = SshClient()
        return self._ssh_client

    async def get_system_health_report(self) -> Dict[str, Any]:
        """
        Gathers a comprehensive 5-dimensional system health snapshot:
        1. CPU load averages (1m, 5m, 15m)
        2. RAM usage (total, used, free, available, percentage)
        3. Disk usage on root filesystem (size, used, avail, percentage)
        4. Docker container statuses (running/stopped/unhealthy)
        5. Network listening ports (ss -tuln)

        Returns a structured dictionary with both granular metrics and an AI summary.
        """
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_vn = timestamp_utc.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S (UTC+7)")

        # Fast composite shell probe: uses delimiters to collect all 5 dimensions in 1 SSH round-trip
        probe_cmd = (
            "cat /proc/loadavg; "
            "echo '===DELIM_RAM==='; free -m; "
            "echo '===DELIM_DISK==='; df -h /; "
            "echo '===DELIM_DOCKER==='; docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}'; "
            "echo '===DELIM_NET==='; ss -tuln"
        )

        try:
            raw_output = await self.ssh_client.execute_command(probe_cmd)
        except Exception as exc:
            logger.error("[ServerMonitor] SSH probe execution error: %s", exc)
            return {
                "status": "error",
                "message": f"Không thể kết nối SSH tới máy chủ: {str(exc)}",
                "timestamp": timestamp_utc.isoformat(),
            }

        if raw_output.startswith("BLOCKED:"):
            logger.error("[ServerMonitor] Command blocked by security filter: %s", raw_output)
            return {
                "status": "error",
                "message": raw_output,
                "timestamp": timestamp_utc.isoformat(),
            }

        # Parse sections separated by delimiters
        sections = raw_output.split("===DELIM_")
        raw_cpu = sections[0].strip() if len(sections) > 0 else ""
        raw_ram = ""
        raw_disk = ""
        raw_docker = ""
        raw_net = ""

        for sec in sections[1:]:
            if sec.startswith("RAM===\n"):
                raw_ram = sec[len("RAM===\n"):].strip()
            elif sec.startswith("DISK===\n"):
                raw_disk = sec[len("DISK===\n"):].strip()
            elif sec.startswith("DOCKER===\n"):
                raw_docker = sec[len("DOCKER===\n"):].strip()
            elif sec.startswith("NET===\n"):
                raw_net = sec[len("NET===\n"):].strip()

        # 1. Parse CPU loadavg
        cpu_metrics = self._parse_cpu(raw_cpu)

        # 2. Parse RAM (free -m)
        ram_metrics = self._parse_ram(raw_ram)

        # 3. Parse Disk (df -h /)
        disk_metrics = self._parse_disk(raw_disk)

        # 4. Parse Docker containers
        docker_metrics = self._parse_docker(raw_docker)

        # 5. Parse Network ports (ss -tuln)
        network_metrics = self._parse_network(raw_net)

        # Overall health evaluation
        overall_health = "HEALTHY"
        issues: List[str] = []

        ram_pct = ram_metrics.get("usage_percent", 0.0)
        if ram_pct >= 92.0:
            overall_health = "CRITICAL"
            issues.append(f"RAM nguy cấp ({ram_pct}%)")
        elif ram_pct >= 85.0:
            overall_health = "WARNING"
            issues.append(f"RAM cao ({ram_pct}%)")

        disk_pct = disk_metrics.get("usage_percent_val", 0)
        if disk_pct >= 90:
            overall_health = "CRITICAL"
            issues.append(f"Ổ cứng gần đầy ({disk_pct}%)")
        elif disk_pct >= 80:
            if overall_health != "CRITICAL":
                overall_health = "WARNING"
            issues.append(f"Ổ cứng chiếm {disk_pct}%")

        load_1m = cpu_metrics.get("load_1m", 0.0)
        if load_1m >= 8.0:
            overall_health = "CRITICAL"
            issues.append(f"CPU load rất cao ({load_1m})")
        elif load_1m >= 4.0:
            if overall_health != "CRITICAL":
                overall_health = "WARNING"
            issues.append(f"CPU load ({load_1m})")

        unhealthy_containers = [
            c["name"] for c in docker_metrics.get("containers", [])
            if "unhealthy" in c.get("status", "").lower()
        ]
        if unhealthy_containers:
            if overall_health != "CRITICAL":
                overall_health = "WARNING"
            issues.append(f"Container unhealthy: {', '.join(unhealthy_containers)}")

        running_names = [c["name"] for c in docker_metrics.get("containers", [])[:5]]
        running_names_str = f" ({', '.join(running_names)})" if running_names else ""

        # Construct human-readable summary
        summary_text = (
            f"📊 BÁO CÁO SỨC KHỎE MÁY CHỦ ({timestamp_vn}) — Trạng thái: [{overall_health}]\n"
            f"• CPU Load: 1m: {cpu_metrics.get('load_1m', 'N/A')} | 5m: {cpu_metrics.get('load_5m', 'N/A')} | 15m: {cpu_metrics.get('load_15m', 'N/A')}\n"
            f"• RAM: {ram_metrics.get('used_mb', 0)}MB / {ram_metrics.get('total_mb', 0)}MB ({ram_metrics.get('usage_percent', 0)}%) — Còn trống: {ram_metrics.get('available_mb', 0)}MB\n"
            f"• Ổ cứng (/): {disk_metrics.get('used', 'N/A')} / {disk_metrics.get('size', 'N/A')} ({disk_metrics.get('usage_percent', 'N/A')}) — Còn trống: {disk_metrics.get('avail', 'N/A')}\n"
            f"• Docker: {docker_metrics.get('total_running', 0)} containers đang chạy{running_names_str}"
            + (f" [CẢNH BÁO: {', '.join(unhealthy_containers)}]" if unhealthy_containers else "") + "\n"
            f"• Mạng: {len(network_metrics.get('listening_ports', []))} cổng đang lắng nghe: {', '.join(map(str, network_metrics.get('listening_ports', [])[:10]))}"
            + ("..." if len(network_metrics.get("listening_ports", [])) > 10 else "")
        )

        return {
            "status": "success",
            "overall_health": overall_health,
            "issues": issues,
            "timestamp": timestamp_utc.isoformat(),
            "timestamp_vn": timestamp_vn,
            "summary": summary_text,
            "cpu": cpu_metrics,
            "ram": ram_metrics,
            "disk": disk_metrics,
            "docker": docker_metrics,
            "network": network_metrics,
        }

    def _parse_cpu(self, raw: str) -> Dict[str, Any]:
        """Parses /proc/loadavg into float metrics."""
        parts = raw.split()
        if len(parts) >= 3:
            try:
                return {
                    "load_1m": float(parts[0]),
                    "load_5m": float(parts[1]),
                    "load_15m": float(parts[2]),
                    "raw": raw,
                }
            except ValueError:
                pass
        return {"load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0, "raw": raw}

    def _parse_ram(self, raw: str) -> Dict[str, Any]:
        """Parses `free -m` output for memory stats."""
        for line in raw.splitlines():
            line_clean = line.strip()
            if line_clean.startswith("Mem:"):
                parts = line_clean.split()
                if len(parts) >= 4:
                    try:
                        total = int(parts[1])
                        used = int(parts[2])
                        free = int(parts[3])
                        available = int(parts[6]) if len(parts) >= 7 else free
                        pct = round((used / total) * 100, 1) if total > 0 else 0.0
                        return {
                            "total_mb": total,
                            "used_mb": used,
                            "free_mb": free,
                            "available_mb": available,
                            "usage_percent": pct,
                            "raw": raw,
                        }
                    except (ValueError, IndexError):
                        pass
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "available_mb": 0,
            "usage_percent": 0.0,
            "raw": raw,
        }

    def _parse_disk(self, raw: str) -> Dict[str, Any]:
        """Parses `df -h /` output for disk statistics."""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 6:
                use_pct_str = parts[4]
                try:
                    pct_val = int(use_pct_str.rstrip("%"))
                except ValueError:
                    pct_val = 0
                return {
                    "filesystem": parts[0],
                    "size": parts[1],
                    "used": parts[2],
                    "avail": parts[3],
                    "usage_percent": use_pct_str,
                    "usage_percent_val": pct_val,
                    "mount": parts[5],
                    "raw": raw,
                }
        return {
            "filesystem": "unknown",
            "size": "N/A",
            "used": "N/A",
            "avail": "N/A",
            "usage_percent": "0%",
            "usage_percent_val": 0,
            "mount": "/",
            "raw": raw,
        }

    def _parse_docker(self, raw: str) -> Dict[str, Any]:
        """Parses `docker ps` tab-separated format into structured container models."""
        containers: List[Dict[str, str]] = []
        for line in raw.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("CONTAINER ID"):
                continue
            parts = line_str.split("\t")
            if len(parts) >= 2:
                containers.append(
                    {
                        "name": parts[0].strip(),
                        "status": parts[1].strip(),
                        "image": parts[2].strip() if len(parts) >= 3 else "",
                        "ports": parts[3].strip() if len(parts) >= 4 else "",
                    }
                )
        return {
            "total_running": len(containers),
            "containers": containers,
            "raw": raw,
        }

    def _parse_network(self, raw: str) -> Dict[str, Any]:
        """Parses `ss -tuln` output for listening TCP/UDP ports."""
        listening_ports: Set[int] = set()
        for line in raw.splitlines():
            line_clean = line.strip()
            if "LISTEN" in line_clean or "UNCONN" in line_clean:
                # Find port after the colon in Local Address:Port column
                match = re.search(r":(\d+)\s+", line_clean)
                if match:
                    try:
                        listening_ports.add(int(match.group(1)))
                    except ValueError:
                        pass
        return {
            "listening_ports": sorted(list(listening_ports)),
            "total_listening": len(listening_ports),
            "raw": raw,
        }

    async def check_service_status(self, service_name: str) -> Dict[str, Any]:
        """
        Inspects the runtime state of a specific Docker container or systemd service.
        Probes Docker first via `docker inspect`, falling back to `systemctl status`.
        """
        clean_name = str(service_name).strip()
        if not clean_name or not SERVICE_NAME_REGEX.match(clean_name):
            return {
                "status": "error",
                "message": f"Tên dịch vụ không hợp lệ: '{clean_name}'. Chỉ chấp nhận chữ cái, số, gạch nối, gạch dưới, chấm.",
            }

        # 1. Probe Docker container inspect
        docker_cmd = f"docker inspect --format '{{{{json .State}}}}' {clean_name}"
        try:
            docker_out = await self.ssh_client.execute_command(docker_cmd)
            docker_out_clean = docker_out.strip()

            if docker_out_clean.startswith("{") and "Running" in docker_out_clean:
                try:
                    state_json = json.loads(docker_out_clean)
                    is_running = bool(state_json.get("Running", False))
                    status_str = state_json.get("Status", "unknown")
                    started_at = state_json.get("StartedAt", "")
                    exit_code = state_json.get("ExitCode", 0)
                    oom_killed = state_json.get("OOMKilled", False)

                    return {
                        "status": "success",
                        "service_name": clean_name,
                        "service_type": "docker",
                        "is_active": is_running,
                        "state": status_str,
                        "details": {
                            "running": is_running,
                            "status": status_str,
                            "started_at": started_at,
                            "exit_code": exit_code,
                            "oom_killed": oom_killed,
                        },
                        "text": (
                            f"🐳 Docker Container '{clean_name}': "
                            f"{'Đang hoạt động (Running)' if is_running else 'Đã dừng (Stopped)'} "
                            f"[State: {status_str}, ExitCode: {exit_code}]"
                        ),
                    }
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            logger.debug("[ServerMonitor] Docker inspect check error for '%s': %s", clean_name, exc)

        # 2. Probe Systemd service
        systemd_cmd = f"systemctl is-active {clean_name}; systemctl show {clean_name} --property=ActiveState,SubState,LoadState,Description"
        try:
            systemd_out = await self.ssh_client.execute_command(systemd_cmd)
            systemd_clean = systemd_out.strip()

            if not systemd_clean.startswith("BLOCKED:") and "LoadState=not-found" not in systemd_clean:
                lines = systemd_clean.splitlines()
                is_active = lines[0].strip() == "active" if lines else False
                details: Dict[str, str] = {}
                for line in lines[1:]:
                    if "=" in line:
                        k, v = line.split("=", 1)
                        details[k.strip()] = v.strip()

                if details.get("LoadState") != "not-found":
                    return {
                        "status": "success",
                        "service_name": clean_name,
                        "service_type": "systemd",
                        "is_active": is_active,
                        "state": details.get("ActiveState", "unknown"),
                        "details": details,
                        "text": (
                            f"⚙️ Systemd Service '{clean_name}': "
                            f"{'Đang hoạt động (Active)' if is_active else 'Không hoạt động (Inactive)'} "
                            f"[SubState: {details.get('SubState', 'unknown')}, Load: {details.get('LoadState', 'unknown')}]"
                        ),
                    }
        except Exception as exc:
            logger.debug("[ServerMonitor] Systemd check error for '%s': %s", clean_name, exc)

        return {
            "status": "not_found",
            "service_name": clean_name,
            "message": f"Không tìm thấy dịch vụ hoặc container '{clean_name}' trên hệ thống (cả Docker lẫn Systemd).",
        }

    def is_production_service(self, service_name: str) -> bool:
        """Checks whether a service name matches protected production infrastructure."""
        s = service_name.lower().strip()
        if s in PROTECTED_PRODUCTION_SERVICES:
            return True
        if s.startswith("dashboard_"):
            return True
        for protected in ["postgres", "redis", "traefik", "nginx"]:
            if protected in s:
                return True
        return False

    async def restart_service(
        self,
        service_name: str,
        confirm: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Restarts a Docker container or Systemd service.
        Tier 2 Reversible action: Requires `confirm='RESTART_CONFIRMED'` for production services.
        """
        clean_name = str(service_name).strip()
        if not clean_name or not SERVICE_NAME_REGEX.match(clean_name):
            return {
                "status": "error",
                "message": f"Tên dịch vụ không hợp lệ: '{clean_name}'.",
            }

        # Enforce Confirmation Token for Production Containers/Services
        if self.is_production_service(clean_name):
            if confirm != "RESTART_CONFIRMED":
                logger.warning(
                    "[ServerMonitor] Vetoed restart attempt on production service '%s' without confirmation token.",
                    clean_name,
                )
                return {
                    "status": "confirmation_required",
                    "service_name": clean_name,
                    "requires_confirm": True,
                    "confirm_token": "RESTART_CONFIRMED",
                    "message": (
                        f"⚠️ CẢNH BÁO BẢO MẬT: Dịch vụ '{clean_name}' là thành phần Production trọng yếu. "
                        f"Khởi động lại có thể làm ngắt kết nối các người dùng đang hoạt động. "
                        f"Vui lòng xác nhận lại bằng tham số confirm='RESTART_CONFIRMED'."
                    ),
                }

        # Check if Docker container exists
        check_res = await self.check_service_status(clean_name)
        service_type = check_res.get("service_type")

        if service_type == "docker":
            restart_cmd = f"docker restart {clean_name}"
        elif service_type == "systemd":
            restart_cmd = f"systemctl restart {clean_name}"
        else:
            # Fallback: attempt docker restart first
            restart_cmd = f"docker restart {clean_name}"

        try:
            output = await self.ssh_client.execute_command(restart_cmd)
            output_clean = output.strip()

            if output_clean.startswith("BLOCKED:"):
                return {
                    "status": "blocked",
                    "service_name": clean_name,
                    "message": output_clean,
                }

            if clean_name in output_clean or output_clean == "" or "lệnh không có output" in output_clean:
                logger.info("[ServerMonitor] Service '%s' successfully restarted via %s", clean_name, service_type or "docker")
                return {
                    "status": "success",
                    "service_name": clean_name,
                    "service_type": service_type or "docker",
                    "action": "restart",
                    "message": f"Đã khởi động lại dịch vụ '{clean_name}' thành công.",
                    "raw": output_clean,
                }
            else:
                return {
                    "status": "error",
                    "service_name": clean_name,
                    "message": f"Lỗi khi khởi động lại dịch vụ '{clean_name}': {output_clean}",
                }
        except Exception as exc:
            logger.error("[ServerMonitor] Error restarting service '%s': %s", clean_name, exc)
            return {
                "status": "error",
                "service_name": clean_name,
                "message": f"Lỗi thực thi lệnh restart cho '{clean_name}': {str(exc)}",
            }

    async def tail_service_logs(self, service_name: str, lines: int = 50) -> Dict[str, Any]:
        """
        Reads the last `lines` log lines from a service/container and performs
        automated error parsing, categorization, and intelligent summarization.
        """
        clean_name = str(service_name).strip()
        if not clean_name or not SERVICE_NAME_REGEX.match(clean_name):
            return {
                "status": "error",
                "message": f"Tên dịch vụ không hợp lệ: '{clean_name}'.",
            }

        try:
            lines = min(max(1, int(lines)), 500)
        except (ValueError, TypeError):
            lines = 50

        # Try Docker logs first
        docker_cmd = f"docker logs --tail {lines} {clean_name} 2>&1"
        try:
            output = await self.ssh_client.execute_command(docker_cmd)
        except Exception as exc:
            return {
                "status": "error",
                "service_name": clean_name,
                "message": f"Không thể lấy log qua SSH: {str(exc)}",
            }

        if "No such container" in output or "Error response from daemon" in output:
            # Fallback to journalctl for systemd services
            journal_cmd = f"journalctl -u {clean_name} -n {lines} --no-pager 2>&1"
            try:
                output = await self.ssh_client.execute_command(journal_cmd)
            except Exception as exc:
                return {
                    "status": "error",
                    "service_name": clean_name,
                    "message": f"Lỗi khi lấy log systemd: {str(exc)}",
                }

        log_lines = [line for line in output.splitlines() if line.strip()]
        error_lines: List[str] = []
        warning_lines: List[str] = []

        for line in log_lines:
            if LOG_ERROR_PATTERN.search(line):
                error_lines.append(line.strip())
            elif LOG_WARN_PATTERN.search(line):
                warning_lines.append(line.strip())

        error_count = len(error_lines)
        warning_count = len(warning_lines)

        # Build intelligent error summary
        if error_count == 0 and warning_count == 0:
            summary = f"Hoàn toàn bình thường: Không phát hiện lỗi hoặc cảnh báo trong {len(log_lines)} dòng log gần nhất."
        elif error_count == 0 and warning_count > 0:
            summary = f"Tương đối ổn định: Có {warning_count} dòng cảnh báo (warning) nhưng không có lỗi nghiêm trọng (error/exception)."
        else:
            summary = (
                f"Phát hiện {error_count} dòng log chứa lỗi/exception và {warning_count} dòng cảnh báo. "
                f"Cần chú ý các lỗi gần nhất để xử lý kịp thời."
            )

        # Deduplicate error samples for preview
        unique_samples: List[str] = []
        seen = set()
        for err in reversed(error_lines):
            # Truncate each line for readability
            short = err[:160]
            if short not in seen:
                seen.add(short)
                unique_samples.append(short)
            if len(unique_samples) >= 5:
                break

        return {
            "status": "success",
            "service_name": clean_name,
            "lines_requested": lines,
            "total_lines": len(log_lines),
            "error_count": error_count,
            "warning_count": warning_count,
            "error_summary": summary,
            "error_samples": unique_samples,
            "logs": output,
        }


# Global singleton instance
_default_monitor_service = ServerMonitorService()


# Module-level API satisfying Interface Contracts
async def get_system_health_report() -> Dict[str, Any]:
    """
    Gathers a comprehensive 5-dimensional server health report.
    Interface contract: get_system_health_report() -> Dict[str, Any]
    """
    return await _default_monitor_service.get_system_health_report()


async def check_service_status(service_name: str) -> Dict[str, Any]:
    """
    Probes the status of a specific container or systemd service.
    Interface contract: check_service_status(service_name: str) -> Dict[str, Any]
    """
    return await _default_monitor_service.check_service_status(service_name=service_name)


async def restart_service(service_name: str, confirm: Optional[str] = None) -> Dict[str, Any]:
    """
    Restarts a service, enforcing confirmation token for production services.
    Interface contract: restart_service(service_name: str, confirm: Optional[str] = None) -> Dict[str, Any]
    """
    return await _default_monitor_service.restart_service(service_name=service_name, confirm=confirm)


async def tail_service_logs(service_name: str, lines: int = 50) -> Dict[str, Any]:
    """
    Reads the last log lines and provides automated error analysis and summarization.
    Interface contract: tail_service_logs(service_name: str, lines: int = 50) -> Dict[str, Any]
    """
    return await _default_monitor_service.tail_service_logs(service_name=service_name, lines=lines)


__all__ = [
    "ServerMonitorService",
    "get_system_health_report",
    "check_service_status",
    "restart_service",
    "tail_service_logs",
]
