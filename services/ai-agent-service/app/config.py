import os
from typing import List, Optional
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

    # OpenRouter Multi-Model Fallback
    OPENROUTER_API_KEY: str = Field(default="", alias="OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = Field(default="nvidia/nemotron-3-super-120b-a12b:free", alias="OPENROUTER_MODEL")
    OPENROUTER_API_URL: str = Field(default="https://openrouter.ai/api/v1/chat/completions", alias="OPENROUTER_API_URL")

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


settings = Settings()
