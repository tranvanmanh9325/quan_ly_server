import json
import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.message_cache import FacebookMessageCache


class TestWeatherTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = MagicMock(spec=LlmRouter)
        self.ssh = MagicMock(spec=SshClient)
        self.ssh.execute_command = AsyncMock()
        self.cache = MagicMock(spec=FacebookMessageCache)
        self.agent = AiAgentService(self.router, self.ssh, self.cache)
        self.executor = AgentToolExecutor(self.ssh, self.cache)

    def test_weather_tool_scoping_intent(self):
        """Verify queries activate get_weather and get_server_location in scoped tools."""
        queries = [
            "xem thời tiết hôm nay như thế nào",
            "thời tiết bựa ni răng em",
            "hôm nay trời có mưa không",
            "nhiệt độ hiện tại",
            "bựa ni trời có mưa rào không",
            "dự báo thời tiết ngày mai",
        ]
        for q in queries:
            scoped = self.executor._resolve_scoped_tool_names(query=q)
            self.assertIn(
                "get_weather",
                scoped,
                f"Query '{q}' did not resolve 'get_weather' in tool scope!",
            )
            self.assertIn(
                "get_server_location",
                scoped,
                f"Query '{q}' did not resolve 'get_server_location' in tool scope!",
            )

    def test_weather_tool_in_core_cluster(self):
        """Verify get_weather and get_server_location are in core cluster as defense-in-depth."""
        core_tools = self.executor._TOOL_CLUSTER_CORE
        self.assertIn("get_weather", core_tools)
        self.assertIn("get_server_location", core_tools)

    def test_weather_tool_schema_definition(self):
        """Verify get_weather schema is correctly generated in _build_tools."""
        tools = self.executor._build_tools(query="xem thời tiết hôm nay như thế nào")
        weather_tool = next(
            (t for t in tools if t.get("function", {}).get("name") == "get_weather"),
            None,
        )
        self.assertIsNotNone(weather_tool, "get_weather tool schema not found in build_tools!")
        params = weather_tool["function"]["parameters"]
        self.assertIn("location", params["properties"])
        self.assertNotIn("required", params)

    async def test_weather_execution_auto_location(self):
        """Verify get_weather auto-resolves server location when location is empty or None."""
        async def mock_execute(cmd: str) -> str:
            if "server_wifi_locator.py" in cmd:
                return '{"error": "bssid_not_found"}'
            if "ip-api.com/json/" in cmd:
                return json.dumps({
                    "status": "success",
                    "city": "Hanoi",
                    "country": "Vietnam",
                    "lat": 21.0184,
                    "lon": 105.8461,
                    "isp": "FPT Telecom Company",
                })
            if "wttr.in/Hanoi?format=j1" in cmd:
                return json.dumps({
                    "current_condition": [{
                        "temp_C": "32",
                        "FeelsLikeC": "34",
                        "weatherDesc": [{"value": "Partly Cloudy"}],
                        "humidity": "48",
                        "windspeedKmph": "12",
                        "winddir16Point": "NNE",
                        "uvIndex": "7",
                    }],
                    "weather": [{
                        "maxtempC": "34",
                        "mintempC": "24",
                        "hourly": [{"chanceofrain": "10"}],
                    }],
                })
            return ""

        self.ssh.execute_command.side_effect = mock_execute

        result = await self.executor._execute_tool("get_weather", {})
        self.assertIn("TỰ ĐỘNG ĐỊNH VỊ VỊ TRÍ MÁY CHỦ", result)
        self.assertIn("Hanoi, Vietnam", result)
        self.assertIn("32°C", result)
        self.assertIn("Cảm giác thực tế: 34°C", result)
        self.assertIn("48%", result)

    async def test_weather_execution_specific_location(self):
        """Verify get_weather queries specific location when provided."""
        async def mock_execute(cmd: str) -> str:
            if "wttr.in/Nghe+An?format=j1" in cmd:
                return json.dumps({
                    "current_condition": [{
                        "temp_C": "28",
                        "FeelsLikeC": "30",
                        "weatherDesc": [{"value": "Patchy rain possible"}],
                        "humidity": "75",
                        "windspeedKmph": "8",
                        "winddir16Point": "E",
                        "uvIndex": "5",
                    }],
                    "weather": [{
                        "maxtempC": "29",
                        "mintempC": "22",
                        "hourly": [{"chanceofrain": "45"}],
                    }],
                })
            return ""

        self.ssh.execute_command.side_effect = mock_execute

        result = await self.executor._execute_tool("get_weather", {"location": "Nghe An"})
        self.assertIn("THỜI TIẾT TẠI NGHE AN", result)
        self.assertIn("28°C", result)
        self.assertIn("Có thể có mưa vài nơi", result)
        self.assertIn("mang theo áo mưa/ô", result)


if __name__ == "__main__":
    unittest.main()
