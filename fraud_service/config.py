from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    investigation_mode: Literal["demo", "groq"] = "demo"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-20b"
    database_path: Path = Path("data/fraud.db")
    investigation_timeout_seconds: float = Field(default=90, gt=0, le=300)
    max_agent_rounds: int = Field(default=6, ge=2, le=12)
    max_tool_calls: int = Field(default=12, ge=3, le=30)
