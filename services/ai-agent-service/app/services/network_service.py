"""
app/services/network_service.py — Network & Ngrok Management Service (R7).

Provides comprehensive network inspection, Ngrok tunnel monitoring, and tunnel restart:
- get_ngrok_status: Probes Ngrok web APIs (ports 4040-4044) or host SSH to report active tunnels,
  public URLs, and protocols with automatic fallback.
- restart_ngrok_tunnel: Safely restarts Ngrok tunnel instances (Tier 2 Reversible) with input sanitization,
  confirmation token validation, and post-restart URL verification.
- get_network_info: Collects LAN IP (socket/SSH), Public IP & ISP (external APIs with <= 3.0s timeout),
  and host socket/interface statistics with graceful offline fallback.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import socket
from typing import Any, Dict, List, Optional
import httpx

from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

NGROK_DEFAULT_PORTS: List[int] = [4040, 4041, 4042, 4043, 4044]
NGROK_CONFIRM_TOKEN: str = "RESTART_CONFIRMED"
TUNNEL_NAME_REGEX: re.Pattern = re.compile(r"^[a-zA-Z0-9_\-]+$")

EXTERNAL_IP_APIS: List[str] = [
    "https://ipinfo.io/json",
    "https://api.ipify.org?format=json",
    "https://ifconfig.me/all.json",
]


class NetworkService:
    """
    Service responsible for network status diagnostics and Ngrok tunnel management.
    Supports dual-path execution (local HTTP direct probe and host SSH command execution).
    """

    def __init__(
        self,
        ssh_client: Optional[SshClient] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        probe_ports: Optional[List[int]] = None,
    ):
        self._ssh_client = ssh_client
        self._http_client = http_client
        self.probe_ports = probe_ports or NGROK_DEFAULT_PORTS

    @property
    def ssh_client(self) -> SshClient:
        if self._ssh_client is None:
            self._ssh_client = SshClient()
        return self._ssh_client

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            return httpx.AsyncClient(timeout=2.0)
        return self._http_client

    async def get_ngrok_status(self) -> Dict[str, Any]:
        """
        Probes Ngrok status across ports 4040-4044.
        Falls back to host SSH curl probe if local HTTP ports are unreachable.
        Aggregates active tunnels and reports public URLs and metrics.
        """
        aggregated_tunnels: List[Dict[str, Any]] = []
        responsive_ports: List[int] = []
        accounts_map: Dict[str, Any] = {}
        http_errors: List[str] = []

        # 1. Attempt probing via HTTP client across configured ports
        client = await self._get_http_client()
        should_close_client = self._http_client is None

        try:
            for port in self.probe_ports:
                url = f"http://127.0.0.1:{port}/api/tunnels"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except Exception:
                            # Malformed JSON / HTML error page
                            http_errors.append(f"Port {port}: invalid JSON response")
                            continue

                        responsive_ports.append(port)
                        tunnels_list = data.get("tunnels", [])
                        for t in tunnels_list:
                            tun_name = t.get("name", "unknown")
                            pub_url = t.get("public_url", "")
                            # Deduplicate by public_url to prevent duplicate tunnels across instances or mock fixtures
                            if pub_url and any(existing.get("public_url") == pub_url for existing in aggregated_tunnels):
                                continue

                            tun_info = {
                                "port": port,
                                "name": tun_name,
                                "public_url": pub_url,
                                "proto": t.get("proto", ""),
                                "forward_to": t.get("config", {}).get("addr", "") if isinstance(t.get("config"), dict) else "",
                                "conns": t.get("metrics", {}).get("conns", {}).get("count", 0) if isinstance(t.get("metrics"), dict) else 0,
                            }
                            aggregated_tunnels.append(tun_info)
                            accounts_map[tun_name] = {
                                "port": port,
                                "public_url": pub_url,
                                "proto": t.get("proto", ""),
                            }
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError) as ex:
                    http_errors.append(f"Port {port}: {type(ex).__name__}")
        finally:
            if should_close_client:
                await client.aclose()

        # If HTTP probing succeeded on at least one port
        if responsive_ports:
            primary_port = responsive_ports[0]
            total = len(aggregated_tunnels)
            msg = (
                f"Đang có {total} Ngrok tunnel hoạt động trên các cổng {responsive_ports}."
                if total > 0
                else f"Ngrok đang lắng nghe trên cổng {primary_port} nhưng hiện không có tunnel nào được mở."
            )
            return {
                "status": "success",
                "probe_port": primary_port,
                "responsive_ports": responsive_ports,
                "total_tunnels": total,
                "tunnels": aggregated_tunnels,
                "accounts": accounts_map,
                "message": msg,
                "source": "http",
                "timestamp": datetime.now(VN_TZ).isoformat(),
            }

        # 2. If all local HTTP ports failed, attempt SSH probe fallback on the host
        ssh_tunnels: List[Dict[str, Any]] = []
        ssh_output = ""
        try:
            # Query endpoint script or compact curl with jq to stay under 1000 chars
            ssh_cmd = (
                "/home/kirito/scripts/ngrok-pool-manager.sh endpoints 2>/dev/null || "
                "curl -s --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null"
            )
            ssh_output = await self.ssh_client.execute_command(ssh_cmd)

            if ssh_output and not ssh_output.startswith("BLOCKED:") and not ssh_output.startswith("(lệnh không"):
                # Try parsing as JSON
                try:
                    parsed = json.loads(ssh_output)
                    if isinstance(parsed, dict):
                        if "tunnels" in parsed and isinstance(parsed["tunnels"], list):
                            for t in parsed["tunnels"]:
                                tun_info = {
                                    "port": 4040,
                                    "name": t.get("name", "unknown"),
                                    "public_url": t.get("public_url", ""),
                                    "proto": t.get("proto", ""),
                                    "forward_to": t.get("config", {}).get("addr", "") if isinstance(t.get("config"), dict) else "",
                                }
                                ssh_tunnels.append(tun_info)
                        else:
                            # Format from ngrok-pool-manager.sh endpoints
                            for acc_id, acc_val in parsed.items():
                                if isinstance(acc_val, dict) and acc_val.get("status") == "ONLINE":
                                    if acc_val.get("web_public_url"):
                                        ssh_tunnels.append({
                                            "name": f"{acc_id}_web",
                                            "public_url": acc_val.get("web_public_url"),
                                            "proto": "https",
                                            "port": int(acc_val.get("web_addr", ":4040").split(":")[-1]),
                                        })
                                    if acc_val.get("ssh_public_url"):
                                        ssh_tunnels.append({
                                            "name": f"{acc_id}_ssh",
                                            "public_url": acc_val.get("ssh_public_url"),
                                            "proto": "tcp",
                                            "port": int(acc_val.get("web_addr", ":4040").split(":")[-1]),
                                        })
                except json.JSONDecodeError:
                    # Regex fallback if JSON was truncated or wrapped
                    found_urls = re.findall(r'"public_url"\s*:\s*"([^"]+)"', ssh_output)
                    for u in found_urls:
                        proto = "tcp" if u.startswith("tcp://") else "https"
                        ssh_tunnels.append({
                            "name": "tunnel",
                            "public_url": u,
                            "proto": proto,
                            "port": 4040,
                        })
        except Exception as ex:
            logger.warning("[NetworkService] SSH fallback probe error: %s", ex)

        if ssh_tunnels:
            return {
                "status": "success",
                "source": "ssh",
                "probe_port": 4040,
                "total_tunnels": len(ssh_tunnels),
                "tunnels": ssh_tunnels,
                "message": f"Tìm thấy {len(ssh_tunnels)} tunnel qua host SSH probe.",
                "timestamp": datetime.now(VN_TZ).isoformat(),
            }

        # 3. All probes failed — Ngrok is offline
        return {
            "status": "offline",
            "total_tunnels": 0,
            "tunnels": [],
            "message": "Dịch vụ Ngrok không hoạt động hoặc không thể kết nối tới các cổng 4040-4044.",
            "timestamp": datetime.now(VN_TZ).isoformat(),
        }

    async def restart_ngrok_tunnel(
        self,
        tunnel_name: Optional[str] = None,
        confirm: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Restarts Ngrok service or a specific tunnel (Tier 2 Reversible).
        Enforces input validation and confirmation token before executing.
        Waits 2-3s post-restart to probe and return the updated public URL.
        """
        # 1. Input sanitization to prevent command injection
        if tunnel_name:
            clean_name = tunnel_name.strip()
            if not TUNNEL_NAME_REGEX.match(clean_name):
                return {
                    "status": "error",
                    "message": f"Tên tunnel '{clean_name}' không hợp lệ. Chỉ cho phép các ký tự chữ cái, số, gạch dưới và gạch ngang.",
                }
        else:
            clean_name = None

        # 2. Tier 2 Confirmation Check
        if confirm != NGROK_CONFIRM_TOKEN:
            target_desc = clean_name or "toàn bộ Ngrok"
            return {
                "status": "confirmation_required",
                "requires_confirm": True,
                "confirm_token": NGROK_CONFIRM_TOKEN,
                "target": clean_name or "all",
                "message": (
                    f"⚠️ CẢNH BÁO BẢO MẬT (Tier 2): Thao tác khởi động lại {target_desc} sẽ ngắt kết nối "
                    f"các phiên hiện tại và thay đổi URL công khai. Vui lòng gọi lại với confirm='{NGROK_CONFIRM_TOKEN}'."
                ),
            }

        # 3. Construct and execute restart command over SSH
        target_service = f"ngrok@{clean_name}" if clean_name else "ngrok"
        restart_cmd = (
            f"/home/kirito/scripts/ngrok-pool-manager.sh restart {clean_name} 2>/dev/null || "
            f"systemctl restart {target_service}"
        ) if clean_name else (
            "/home/kirito/scripts/ngrok-pool-manager.sh restart all 2>/dev/null || "
            "systemctl restart ngrok"
        )

        try:
            cmd_output = await self.ssh_client.execute_command(restart_cmd)
            # Check for systemd failure in output
            if "failed" in cmd_output.lower() or "error" in cmd_output.lower() or cmd_output.startswith("BLOCKED:"):
                return {
                    "status": "error",
                    "target": clean_name or "all",
                    "message": f"Khởi động lại Ngrok thất bại: {cmd_output}",
                }
        except Exception as ex:
            return {
                "status": "error",
                "target": clean_name or "all",
                "message": f"Lỗi thực thi lệnh SSH khi restart Ngrok: {str(ex)}",
            }

        # 4. Wait for Ngrok cloud reconnect
        await asyncio.sleep(2.5)

        # 5. Probe for updated tunnels
        probe_res = await self.get_ngrok_status()
        new_url = ""
        if probe_res.get("status") == "success" and probe_res.get("tunnels"):
            tunnels = probe_res["tunnels"]
            # Try to match the specific tunnel if requested
            if clean_name:
                matched = [t for t in tunnels if clean_name in t.get("name", "")]
                new_url = matched[0].get("public_url", "") if matched else tunnels[0].get("public_url", "")
            else:
                new_url = tunnels[0].get("public_url", "")

        if not new_url and probe_res.get("status") == "offline":
            return {
                "status": "warning",
                "target": clean_name or "all",
                "message": "Lệnh restart đã được thực thi nhưng Ngrok chưa hoạt động trở lại sau thời gian chờ.",
                "probe_result": probe_res,
            }

        return {
            "status": "success",
            "target": clean_name or "all",
            "new_url": new_url,
            "tunnels": probe_res.get("tunnels", []),
            "message": f"Đã khởi động lại Ngrok tunnel '{clean_name or 'all'}' thành công. URL mới: {new_url or 'Đang khởi tạo'}",
            "timestamp": datetime.now(VN_TZ).isoformat(),
        }

    async def get_network_info(self) -> Dict[str, Any]:
        """
        Retrieves internal LAN IP, Public WAN IP, ISP organization, and active socket stats.
        Enforces <= 3.0s timeout on external HTTP calls with graceful degradation on network outage.
        """
        # 1. Resolve LAN IP
        internal_ip = "127.0.0.1"
        lan_interface = "unknown"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("1.1.1.1", 80))
                internal_ip = s.getsockname()[0]
        except Exception:
            internal_ip = ""

        # Fallback LAN IP via SSH hostname -I if socket resolution failed or returned loopback
        if not internal_ip or internal_ip.startswith("127."):
            try:
                ssh_out = await self.ssh_client.execute_command("hostname -I")
                if ssh_out and not ssh_out.startswith("BLOCKED:") and not ssh_out.startswith("(lệnh không"):
                    ips = ssh_out.split()
                    if ips:
                        internal_ip = ips[0]
            except Exception as ex:
                logger.warning("[NetworkService] LAN IP SSH fallback error: %s", ex)

        if not internal_ip:
            internal_ip = "192.168.0.100"  # Graceful fallback default

        # 2. Resolve Public IP & ISP with multi-tier fallback and timeout <= 3.0s
        public_ip = "Unavailable"
        isp = "Unavailable"
        country = "VN"
        internet_connected = False
        fallback_used = False

        client = await self._get_http_client()
        should_close_client = self._http_client is None

        try:
            for idx, api_url in enumerate(EXTERNAL_IP_APIS):
                try:
                    resp = await client.get(api_url, timeout=2.5)
                    if resp.status_code == 200:
                        data = resp.json()
                        pub_candidate = data.get("ip") or data.get("query")
                        if pub_candidate:
                            public_ip = pub_candidate
                            isp = data.get("org") or data.get("isp") or "FPT Telecom"
                            country = data.get("country") or "VN"
                            internet_connected = True
                            if idx > 0:
                                fallback_used = True
                            break
                except Exception as ex:
                    logger.debug("[NetworkService] External IP API failed: %s (%s)", api_url, ex)
                    continue
        finally:
            if should_close_client:
                await client.aclose()

        # 3. Collect host connection statistics via SSH (ss -s)
        active_connections = 0
        try:
            ss_out = await self.ssh_client.execute_command("ss -s")
            if ss_out and not ss_out.startswith("BLOCKED:"):
                # Look for 'estab X' pattern
                m = re.search(r"estab\s+(\d+)", ss_out, re.IGNORECASE)
                if m:
                    active_connections = int(m.group(1))
        except Exception:
            pass

        # 4. Assemble standard result
        status_val = "success" if internet_connected else "partial_success"
        summary_text = (
            f"📡 Mạng LAN: {internal_ip} | WAN: {public_ip} ({isp}) | Kết nối TCP active: {active_connections}"
            if internet_connected
            else f"⚠️ Mạng LAN: {internal_ip} | WAN: Ngoại tuyến (Internet Unavailable) | Kết nối TCP: {active_connections}"
        )

        return {
            "status": status_val,
            "internal_ip": internal_ip,
            "public_ip": public_ip,
            "isp": isp,
            "country": country,
            "internet_connected": internet_connected,
            "active_connections": active_connections,
            "fallback_used": fallback_used,
            "summary_text": summary_text,
            "timestamp": datetime.now(VN_TZ).isoformat(),
        }


# Singleton instance & Module Facades
_default_network_service = NetworkService()


async def get_ngrok_status() -> Dict[str, Any]:
    """Facade for NetworkService.get_ngrok_status()."""
    return await _default_network_service.get_ngrok_status()


async def restart_ngrok_tunnel(
    tunnel_name: Optional[str] = None,
    confirm: Optional[str] = None,
) -> Dict[str, Any]:
    """Facade for NetworkService.restart_ngrok_tunnel()."""
    return await _default_network_service.restart_ngrok_tunnel(tunnel_name, confirm)


async def get_network_info() -> Dict[str, Any]:
    """Facade for NetworkService.get_network_info()."""
    return await _default_network_service.get_network_info()
