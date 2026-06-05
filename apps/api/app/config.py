from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILES = [PROJECT_ROOT / ".env", Path(".env")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(path) for path in ENV_FILES if path.exists()],
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://smart_assistant:change_me_in_production@localhost:5432/smart_assistant"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.3
    openai_top_p: float = 0.8
    openai_max_tokens: int = 1200
    openai_timeout_seconds: float = 60.0
    openai_fallback_to_mock: bool = True

    api_secret_key: str = "dev-secret-change-me"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "database_url",
        "redis_url",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
