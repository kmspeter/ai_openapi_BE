from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    google_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")

    database_url: str = Field(default="sqlite+aiosqlite:///./data/usage.db", alias="DATABASE_URL")
    allowed_origins: List[str] = Field(default_factory=list, alias="ALLOWED_ORIGINS")

    port: int = Field(default=8000, alias="PORT")
    debug: bool = Field(default=False, alias="DEBUG")
    
    enable_ngrok: bool = Field(default=False, alias="ENABLE_NGROK")
    ngrok_authtoken: Optional[str] = Field(default=None, alias="NGROK_AUTHTOKEN")
    ngrok_region: Optional[str] = Field(default=None, alias="NGROK_REGION")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Optional[str | List[str]]) -> List[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _ensure_async_sqlite(cls, value: str) -> str:
        if value.startswith("sqlite") and "+aiosqlite" not in value:
            return value.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return value

    @property
    def provider_keys(self) -> Dict[str, Optional[str]]:
        return {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
        }


@lru_cache()
def get_settings() -> Config:
    return Config()


settings = get_settings()
