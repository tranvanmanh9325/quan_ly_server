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

    # Groq Multi-Key Pool
    GROQ_API_KEY: str = Field(default="", alias="GROQ_API_KEY")
    GROQ_API_KEY_2: str = Field(default="", alias="GROQ_API_KEY_2")
    GROQ_API_KEY_3: str = Field(default="", alias="GROQ_API_KEY_3")
    GROQ_API_KEY_4: str = Field(default="", alias="GROQ_API_KEY_4")
    GROQ_API_KEY_5: str = Field(default="", alias="GROQ_API_KEY_5")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")

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
        ]
        return [k.strip() for k in keys if k and k.strip()]


settings = Settings()
