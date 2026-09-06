import os
from typing import List, Optional, Tuple
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", "../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server / App
    PORT: int = Field(default=8084, alias="PORT")
    JWT_SECRET: str = Field(default="change-me-secret-key-at-least-32-chars-long", alias="JWT_SECRET")

    # Database (PostgreSQL)
    POSTGRES_DB: str = Field(default="quan_ly_server", alias="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="dashboard_user", alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="dashboard_password", alias="POSTGRES_PASSWORD")
    DB_HOST: str = Field(default="db", alias="DB_HOST")
    DB_PORT: int = Field(default=5432, alias="DB_PORT")

    # SSH Connection to server
    SSH_HOST: str = Field(default="192.168.0.100", alias="SSH_HOST")
    SSH_PORT: int = Field(default=22, alias="SSH_PORT")
    SSH_USER: str = Field(default="kirito", alias="SSH_USER")
    SSH_PASSWORD: str = Field(default="", alias="SSH_PASSWORD")
    SSH_FALLBACK_HOST: Optional[str] = Field(default=None, alias="SSH_FALLBACK_HOST")
    SSH_FALLBACK_PORT: int = Field(default=22, alias="SSH_FALLBACK_PORT")
    SSH_FALLBACK_PORT_2: Optional[int] = Field(default=None, alias="SSH_FALLBACK_PORT_2")
    SSH_FALLBACK_PORT_3: Optional[int] = Field(default=None, alias="SSH_FALLBACK_PORT_3")
    SSH_FALLBACK_PORT_4: Optional[int] = Field(default=None, alias="SSH_FALLBACK_PORT_4")
    SSH_FALLBACK_PORT_5: Optional[int] = Field(default=None, alias="SSH_FALLBACK_PORT_5")
    NGROK_SSH_TUNNELS: Optional[str] = Field(default=None, alias="NGROK_SSH_TUNNELS")

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    TELEGRAM_POLLING_ENABLED: bool = Field(default=True, alias="TELEGRAM_POLLING_ENABLED")

    # Groq Multi-Key Pool (Supports 10+ keys with dynamic environment discovery)
    GROQ_API_KEY: str = Field(default="", alias="GROQ_API_KEY")
    GROQ_API_KEY_2: str = Field(default="", alias="GROQ_API_KEY_2")
    GROQ_API_KEY_3: str = Field(default="", alias="GROQ_API_KEY_3")
    GROQ_API_KEY_4: str = Field(default="", alias="GROQ_API_KEY_4")
    GROQ_API_KEY_5: str = Field(default="", alias="GROQ_API_KEY_5")
    GROQ_API_KEY_6: str = Field(default="", alias="GROQ_API_KEY_6")
    GROQ_API_KEY_7: str = Field(default="", alias="GROQ_API_KEY_7")
    GROQ_API_KEY_8: str = Field(default="", alias="GROQ_API_KEY_8")
    GROQ_API_KEY_9: str = Field(default="", alias="GROQ_API_KEY_9")
    GROQ_API_KEY_10: str = Field(default="", alias="GROQ_API_KEY_10")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")

    # OpenRouter Multi-Key Pool (mirrors Groq pool pattern)
    OPENROUTER_API_KEY: str = Field(default="", alias="OPENROUTER_API_KEY")
    OPENROUTER_API_KEY_2: str = Field(default="", alias="OPENROUTER_API_KEY_2")
    OPENROUTER_API_KEY_3: str = Field(default="", alias="OPENROUTER_API_KEY_3")
    OPENROUTER_API_KEY_4: str = Field(default="", alias="OPENROUTER_API_KEY_4")
    OPENROUTER_API_KEY_5: str = Field(default="", alias="OPENROUTER_API_KEY_5")
    # Primary free model: nemotron-3-ultra-550b (strongest free model, 550B params, 1M ctx, verified live 27/08/2026)
    OPENROUTER_MODEL: str = Field(default="nvidia/nemotron-3-ultra-550b-a55b:free", alias="OPENROUTER_MODEL")
    # Fallback free model: nemotron-3-super-120b (verified live, activated when ultra is rate-limited)
    OPENROUTER_MODEL_FALLBACK: str = Field(default="nvidia/nemotron-3-super-120b-a12b:free", alias="OPENROUTER_MODEL_FALLBACK")
    OPENROUTER_API_URL: str = Field(default="https://openrouter.ai/api/v1/chat/completions", alias="OPENROUTER_API_URL")

    # Server Physical Ground Truth Metadata (Dynamically resolved via Wi-Fi WPS)
    SERVER_PHYSICAL_LOCATION: str = Field(default="Tự động phân giải theo thời gian thực qua Wi-Fi WPS", alias="SERVER_PHYSICAL_LOCATION")
    SERVER_ISP: str = Field(default="FPT Telecom", alias="SERVER_ISP")
    SERVER_OWNER: str = Field(default="Trần Văn Mạnh (kirito)", alias="SERVER_OWNER")

    # Multimodal — Groq STT (Whisper)
    GROQ_WHISPER_MODEL: str = Field(default="whisper-large-v3-turbo", alias="GROQ_WHISPER_MODEL")
    GROQ_WHISPER_MODEL_FALLBACK: str = Field(default="whisper-large-v3", alias="GROQ_WHISPER_MODEL_FALLBACK")

    # Multimodal — Groq Vision (Qwen VL, verified active Aug 2026)
    GROQ_VISION_MODEL: str = Field(default="qwen/qwen3.8-27b", alias="GROQ_VISION_MODEL")
    GROQ_VISION_MODEL_FALLBACK: str = Field(default="qwen/qwen3.6-27b", alias="GROQ_VISION_MODEL_FALLBACK")

    # Multimodal — OpenRouter Vision fallback (free tier, verified Aug 2026)
    OPENROUTER_VISION_MODEL: str = Field(default="google/gemma-4-31b-it:free", alias="OPENROUTER_VISION_MODEL")
    OPENROUTER_VISION_MODEL_FALLBACK: str = Field(default="google/gemma-4-26b-a4b-it:free", alias="OPENROUTER_VISION_MODEL_FALLBACK")

    # Reasoning — Groq native think mode (qwen3 family only, Aug 2026)
    # Values: "low" | "medium" | "high" — controls thinking budget/quality tradeoff
    # Applied only to qwen3 models; gpt-oss-120b ignores this parameter
    GROQ_REASONING_EFFORT_DEFAULT: str = Field(default="medium", alias="GROQ_REASONING_EFFORT_DEFAULT")

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.POSTGRES_DB}"

    @property
    def groq_keys(self) -> List[str]:
        keys = [
            self.GROQ_API_KEY,
            self.GROQ_API_KEY_2,
            self.GROQ_API_KEY_3,
            self.GROQ_API_KEY_4,
            self.GROQ_API_KEY_5,
            self.GROQ_API_KEY_6,
            self.GROQ_API_KEY_7,
            self.GROQ_API_KEY_8,
            self.GROQ_API_KEY_9,
            self.GROQ_API_KEY_10,
        ]
        # Also dynamically discover any extra GROQ_API_KEY_* environment variables
        for env_k, env_v in os.environ.items():
            if env_k.startswith("GROQ_API_KEY") and env_v and env_v.strip():
                if env_v.strip() not in keys:
                    keys.append(env_v.strip())

        # Return unique, non-empty stripped keys while preserving order
        seen = set()
        result = []
        for k in keys:
            clean = k.strip() if k else ""
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @property
    def openrouter_keys(self) -> List[str]:
        keys = [
            self.OPENROUTER_API_KEY,
            self.OPENROUTER_API_KEY_2,
            self.OPENROUTER_API_KEY_3,
            self.OPENROUTER_API_KEY_4,
            self.OPENROUTER_API_KEY_5,
        ]
        # Dynamically discover any extra OPENROUTER_API_KEY_* environment variables
        for env_k, env_v in os.environ.items():
            if env_k.startswith("OPENROUTER_API_KEY") and env_v and env_v.strip():
                if env_v.strip() not in keys:
                    keys.append(env_v.strip())

        # Return unique, non-empty stripped keys while preserving order
        seen = set()
        result = []
        for k in keys:
            clean = k.strip() if k else ""
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @property
    def ssh_fallback_endpoints(self) -> List[Tuple[str, int]]:
        """
        Returns a deduplicated list of fallback SSH tunnel endpoints (host, port).
        Parses NGROK_SSH_TUNNELS, discrete SSH_FALLBACK_PORT_*, and dynamic env vars.
        """
        endpoints: List[Tuple[str, int]] = []
        default_host = (self.SSH_FALLBACK_HOST or "0.tcp.ap.ngrok.io").strip()

        # 1. Parse NGROK_SSH_TUNNELS (e.g. "0.tcp.ap.ngrok.io:25823,0.tcp.ap.ngrok.io:18974")
        if self.NGROK_SSH_TUNNELS:
            for item in self.NGROK_SSH_TUNNELS.split(","):
                item = item.strip()
                if not item:
                    continue
                if ":" in item:
                    parts = item.split(":", 1)
                    h, p = parts[0].strip(), parts[1].strip()
                    if p.isdigit():
                        endpoints.append((h, int(p)))
                elif item.isdigit():
                    endpoints.append((default_host, int(item)))

        # 2. Check discrete port fields
        if self.SSH_FALLBACK_HOST:
            discrete_ports = [
                self.SSH_FALLBACK_PORT,
                self.SSH_FALLBACK_PORT_2,
                self.SSH_FALLBACK_PORT_3,
                self.SSH_FALLBACK_PORT_4,
                self.SSH_FALLBACK_PORT_5,
            ]
            for port in discrete_ports:
                if port and port > 0:
                    endpoints.append((self.SSH_FALLBACK_HOST.strip(), port))

        # 3. Dynamic discovery of any extra SSH_FALLBACK_PORT_* env vars
        if self.SSH_FALLBACK_HOST:
            for env_k, env_v in os.environ.items():
                if env_k.startswith("SSH_FALLBACK_PORT_") and env_v and env_v.strip().isdigit():
                    p = int(env_v.strip())
                    if p > 0:
                        endpoints.append((self.SSH_FALLBACK_HOST.strip(), p))

        # Deduplicate while preserving order and filtering out duplicate of primary (SSH_HOST, SSH_PORT)
        seen = set()
        result: List[Tuple[str, int]] = []
        for host, port in endpoints:
            if (host, port) == (self.SSH_HOST, self.SSH_PORT):
                continue
            if (host, port) not in seen:
                seen.add((host, port))
                result.append((host, port))
        return result


settings = Settings()
