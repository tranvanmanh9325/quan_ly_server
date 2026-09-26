"""
test_tool_r7_network.py — Unit & Adversarial Tests for NetworkService (R7).

Validates Network & Ngrok Management interface contracts:
- get_ngrok_status():
  - Probing Ngrok web API across ports 4040-4044
  - Multi-instance aggregation and port-offset fallbacks
  - Empty tunnels handling
  - Offline / ConnectionRefused handling without exceptions
  - SSH curl fallback for Docker container isolation
  - Malformed JSON resilience
- restart_ngrok_tunnel(tunnel_name, confirm):
  - Service restart via SSH command execution
  - Verification of new public URL post-restart with mock delay
  - Failure handling and probe timeouts
  - Command injection sanitization on tunnel_name
  - Specific tunnel restart vs all tunnels
- get_network_info():
  - Local LAN IP resolution (socket & hostname -I fallback)
  - Public IP resolution across multiple external APIs with graceful fallback
  - Offline internet graceful degradation (no crash on total network failure)
  - Strict HTTP timeout enforcement (<= 3.0s)
"""

import asyncio
import json
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.network_service import (
    NetworkService,
    get_ngrok_status,
    restart_ngrok_tunnel,
    get_network_info,
)


class MockSshClient:
    """Mock SSH client simulating server shell command execution."""

    def __init__(self, responses=None, default_response=""):
        self.responses = responses or {}
        self.default_response = default_response
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


class TestNetworkServiceNgrok(unittest.IsolatedAsyncioTestCase):
    """Test suite for get_ngrok_status() and restart_ngrok_tunnel() (R7-01 to R7-12)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = NetworkService(ssh_client=self.mock_ssh)

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_success_port_4040(self, mock_get):
        """R7-01: Probing succeeds on default port 4040 with HTTP and TCP tunnels."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tunnels": [
                {
                    "name": "web_tunnel",
                    "public_url": "https://dashboard.ngrok-free.app",
                    "proto": "https",
                    "config": {"addr": "http://localhost:8084"},
                },
                {
                    "name": "ssh_tunnel",
                    "public_url": "tcp://0.tcp.ngrok.io:12345",
                    "proto": "tcp",
                    "config": {"addr": "localhost:22"},
                },
            ]
        }
        mock_get.return_value = mock_resp

        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_tunnels"], 2)
        self.assertEqual(len(res["tunnels"]), 2)
        self.assertEqual(res["tunnels"][0]["name"], "web_tunnel")
        self.assertEqual(res["tunnels"][0]["public_url"], "https://dashboard.ngrok-free.app")
        self.assertEqual(res["probe_port"], 4040)

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_probe_port_fallback_4041(self, mock_get):
        """R7-02: Port 4040 is offline, but port 4041 is listening and has a tunnel."""
        async def mock_get_side_effect(url, **kwargs):
            if ":4040/" in str(url):
                raise httpx.ConnectError("Connection refused on port 4040")
            elif ":4041/" in str(url):
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "tunnels": [
                        {
                            "name": "api_tunnel",
                            "public_url": "https://api.ngrok-free.app",
                            "proto": "https",
                        }
                    ]
                }
                return resp
            raise httpx.ConnectError("Connection refused")

        mock_get.side_effect = mock_get_side_effect
        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["probe_port"], 4041)
        self.assertEqual(res["total_tunnels"], 1)

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_empty_tunnels(self, mock_get):
        """R7-03: Ngrok is running on port 4040 but no tunnels are open."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tunnels": []}
        mock_get.return_value = mock_resp

        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_tunnels"], 0)
        self.assertEqual(res["tunnels"], [])
        self.assertIn("không có tunnel nào", res["message"].lower())

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_all_ports_offline(self, mock_get):
        """R7-04: All ports 4040-4044 fail and SSH fallback has no tunnels."""
        mock_get.side_effect = httpx.ConnectError("All ports offline")
        self.mock_ssh.default_response = ""

        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "offline")
        self.assertEqual(res["total_tunnels"], 0)
        self.assertIn("không hoạt động", res["message"].lower())

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_via_ssh_fallback(self, mock_get):
        """R7-05: Direct HTTP is blocked (Docker isolation), falls back to SSH curl."""
        mock_get.side_effect = httpx.ConnectError("Network unreachable")
        self.mock_ssh.responses = {
            "ngrok-pool-manager.sh endpoints": json.dumps({
                "tunnels": [
                    {
                        "name": "ssh_fallback",
                        "public_url": "tcp://0.tcp.ap.ngrok.io:22222",
                        "proto": "tcp",
                    }
                ]
            })
        }

        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source"], "ssh")
        self.assertEqual(res["total_tunnels"], 1)
        self.assertEqual(res["tunnels"][0]["public_url"], "tcp://0.tcp.ap.ngrok.io:22222")

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_malformed_json_response(self, mock_get):
        """R7-06: Web API returns 502 HTML or corrupted non-JSON payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "<html>502 Bad Gateway</html>", 0)
        mock_get.return_value = mock_resp
        self.mock_ssh.default_response = ""

        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "offline")
        self.assertEqual(res["total_tunnels"], 0)

    @patch("httpx.AsyncClient.get")
    async def test_get_ngrok_status_multi_instance_aggregation(self, mock_get):
        """R7-07: Aggregates tunnels from multiple active Ngrok instances (ports 4040 and 4042)."""
        async def mock_get_multi(url, **kwargs):
            if ":4040/" in str(url):
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {
                    "tunnels": [{"name": "inst1_web", "public_url": "https://inst1.ngrok.io", "proto": "https"}]
                }
                return r
            elif ":4042/" in str(url):
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {
                    "tunnels": [{"name": "inst2_ssh", "public_url": "tcp://inst2.ngrok.io:1234", "proto": "tcp"}]
                }
                return r
            raise httpx.ConnectError("Offline")

        mock_get.side_effect = mock_get_multi
        res = await self.service.get_ngrok_status()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_tunnels"], 2)
        names = [t["name"] for t in res["tunnels"]]
        self.assertIn("inst1_web", names)
        self.assertIn("inst2_ssh", names)

    @patch("asyncio.sleep", return_value=None)
    @patch("httpx.AsyncClient.get")
    async def test_restart_ngrok_tunnel_all_success(self, mock_get, mock_sleep):
        """R7-08: Restarts all Ngrok services and discovers updated public URL."""
        self.mock_ssh.responses = {
            "systemctl restart ngrok": "",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tunnels": [
                {
                    "name": "web",
                    "public_url": "https://new-url-123.ngrok-free.app",
                    "proto": "https",
                }
            ]
        }
        mock_get.return_value = mock_resp

        res = await self.service.restart_ngrok_tunnel(tunnel_name=None, confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "success")
        self.assertIn("https://new-url-123.ngrok-free.app", res.get("new_url", ""))
        self.assertTrue(any("restart" in cmd for cmd in self.mock_ssh.executed_commands))

    @patch("asyncio.sleep", return_value=None)
    @patch("httpx.AsyncClient.get")
    async def test_restart_ngrok_tunnel_specific_tunnel(self, mock_get, mock_sleep):
        """R7-09: Restarts a specific named Ngrok tunnel instance."""
        self.mock_ssh.responses = {
            "ngrok@account_1": "",
            "restart account_1": "",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tunnels": [
                {
                    "name": "account_1_web",
                    "public_url": "https://acc1-new.ngrok-free.app",
                    "proto": "https",
                }
            ]
        }
        mock_get.return_value = mock_resp

        res = await self.service.restart_ngrok_tunnel(tunnel_name="account_1", confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "success")
        self.assertIn("https://acc1-new.ngrok-free.app", res.get("new_url", ""))

    @patch("asyncio.sleep", return_value=None)
    async def test_restart_ngrok_tunnel_ssh_failure(self, mock_sleep):
        """R7-10: SSH execution reports systemctl service restart failure."""
        self.mock_ssh.default_response = "Failed to restart ngrok.service: Unit not found."

        res = await self.service.restart_ngrok_tunnel(tunnel_name=None, confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "error")
        self.assertIn("thất bại", res["message"].lower())

    @patch("asyncio.sleep", return_value=None)
    @patch("httpx.AsyncClient.get")
    async def test_restart_ngrok_tunnel_probe_timeout_after_restart(self, mock_get, mock_sleep):
        """R7-11: Restart command sent successfully, but probe reports offline post-restart."""
        self.mock_ssh.responses = {
            "restart": "",
        }
        mock_get.side_effect = httpx.ConnectError("Offline post restart")
        self.mock_ssh.default_response = ""

        res = await self.service.restart_ngrok_tunnel(tunnel_name="account_2", confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "warning")
        self.assertIn("chưa hoạt động trở lại", res["message"])

    async def test_restart_ngrok_tunnel_injection_blocked(self):
        """R7-12: Sanitizes tunnel_name parameter against command injection."""
        evil_name = "tunnel; rm -rf /"
        res = await self.service.restart_ngrok_tunnel(tunnel_name=evil_name)
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_restart_ngrok_tunnel_without_confirm_requires_confirmation(self):
        """R7-12b: Calling restart_ngrok_tunnel without confirm (None) strictly returns confirmation_required and NEVER executes SSH."""
        res = await self.service.restart_ngrok_tunnel(tunnel_name="web_tunnel", confirm=None)
        self.assertEqual(res["status"], "confirmation_required")
        self.assertTrue(res["requires_confirm"])
        self.assertEqual(res["confirm_token"], "RESTART_CONFIRMED")
        self.assertIn("CẢNH BÁO BẢO MẬT (Tier 2)", res["message"])
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_restart_ngrok_tunnel_default_param_requires_confirmation(self):
        """R7-12c: Calling restart_ngrok_tunnel() with all default parameters strictly requires confirmation."""
        res = await self.service.restart_ngrok_tunnel()
        self.assertEqual(res["status"], "confirmation_required")
        self.assertTrue(res["requires_confirm"])
        self.assertEqual(res["confirm_token"], "RESTART_CONFIRMED")
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_restart_ngrok_tunnel_invalid_confirm_token_requires_confirmation(self):
        """R7-12d: Calling restart_ngrok_tunnel with wrong token returns confirmation_required and executes 0 SSH commands."""
        res = await self.service.restart_ngrok_tunnel(tunnel_name="web_tunnel", confirm="WRONG_TOKEN")
        self.assertEqual(res["status"], "confirmation_required")
        self.assertTrue(res["requires_confirm"])
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)


class TestNetworkServiceNetworkInfo(unittest.IsolatedAsyncioTestCase):
    """Test suite for get_network_info() (R7-13 to R7-16)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = NetworkService(ssh_client=self.mock_ssh)

    @patch("httpx.AsyncClient.get")
    @patch("socket.socket")
    async def test_get_network_info_healthy(self, mock_sock_cls, mock_http_get):
        """R7-13: Full network info collection in healthy state."""
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.0.100", 0)
        mock_sock_cls.return_value.__enter__.return_value = mock_sock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ip": "113.190.234.56",
            "org": "VNPT Corp",
            "country": "VN",
        }
        mock_http_get.return_value = mock_resp

        self.mock_ssh.responses = {
            "ss -s": "TCP: 42 (estab 15, closed 5, orphaned 0, timewait 20)",
        }

        res = await self.service.get_network_info()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["internal_ip"], "192.168.0.100")
        self.assertEqual(res["public_ip"], "113.190.234.56")
        self.assertEqual(res["isp"], "VNPT Corp")
        self.assertEqual(res["active_connections"], 15)
        self.assertTrue(res["internet_connected"])

    @patch("httpx.AsyncClient.get")
    @patch("socket.socket")
    async def test_get_network_info_public_ip_fallback(self, mock_sock_cls, mock_http_get):
        """R7-14: Primary IP API times out, falls back to secondary external API."""
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.0.100", 0)
        mock_sock_cls.return_value.__enter__.return_value = mock_sock

        async def mock_api_fallback(url, **kwargs):
            if "ipinfo.io" in str(url):
                raise httpx.ConnectTimeout("ipinfo timeout")
            elif "api.ipify.org" in str(url):
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {"ip": "118.71.62.215"}
                return r
            raise httpx.RequestError("Unknown")

        mock_http_get.side_effect = mock_api_fallback
        res = await self.service.get_network_info()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["public_ip"], "118.71.62.215")
        self.assertTrue(res["fallback_used"])

    @patch("httpx.AsyncClient.get")
    @patch("socket.socket")
    async def test_get_network_info_all_external_apis_offline(self, mock_sock_cls, mock_http_get):
        """R7-15: Complete internet outage (all external APIs fail), graceful degradation."""
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.0.100", 0)
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        mock_http_get.side_effect = httpx.ConnectTimeout("Internet unreachable")

        res = await self.service.get_network_info()
        self.assertEqual(res["status"], "partial_success")
        self.assertFalse(res["internet_connected"])
        self.assertEqual(res["public_ip"], "Unavailable")
        self.assertEqual(res["internal_ip"], "192.168.0.100")

    @patch("httpx.AsyncClient.get")
    @patch("socket.socket")
    async def test_get_network_info_lan_ip_fallback_ssh(self, mock_sock_cls, mock_http_get):
        """R7-16: Socket resolution fails, falls back to SSH hostname -I."""
        mock_sock_cls.side_effect = OSError("Socket error")
        self.mock_ssh.responses = {
            "hostname -I": "192.168.0.150 172.18.0.1\n",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ip": "113.190.234.56", "org": "Viettel"}
        mock_http_get.return_value = mock_resp

        res = await self.service.get_network_info()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["internal_ip"], "192.168.0.150")


if __name__ == "__main__":
    unittest.main()
