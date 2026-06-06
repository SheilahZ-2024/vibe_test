from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _discover_env_files() -> list[str]:
    here = Path(__file__).resolve()
    candidates: list[Path] = [Path(".env")]
    for depth in (3, 2, 1):
        if len(here.parents) > depth:
            candidates.append(here.parents[depth] / ".env")
    seen: set[str] = set()
    files: list[str] = []
    for path in candidates:
        key = str(path)
        if path.exists() and key not in seen:
            seen.add(key)
            files.append(key)
    return files


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_discover_env_files(),
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://smart_assistant:change_me_in_production@localhost:5432/smart_assistant"
    redis_url: str = "redis://localhost:6379/0"

    llm_api_key: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    llm_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"))
    llm_temperature: float = Field(default=0.3, validation_alias=AliasChoices("LLM_TEMPERATURE", "OPENAI_TEMPERATURE"))
    llm_top_p: float = Field(default=0.8, validation_alias=AliasChoices("LLM_TOP_P", "OPENAI_TOP_P"))
    llm_max_tokens: int = Field(default=1200, validation_alias=AliasChoices("LLM_MAX_TOKENS", "OPENAI_MAX_TOKENS"))
    llm_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS", "OPENAI_TIMEOUT_SECONDS"),
    )
    llm_fallback_to_mock: bool = Field(
        default=False,
        validation_alias=AliasChoices("LLM_FALLBACK_TO_MOCK", "OPENAI_FALLBACK_TO_MOCK"),
    )
    llm_require_live: bool = Field(
        default=True,
        validation_alias=AliasChoices("LLM_REQUIRE_LIVE"),
    )

    intent_confidence_threshold: float = Field(default=0.65, validation_alias=AliasChoices("INTENT_CONFIDENCE_THRESHOLD"))
    intent_use_llm: bool = Field(default=True, validation_alias=AliasChoices("INTENT_USE_LLM"))
    intent_llm_temperature: float = Field(default=0.1, validation_alias=AliasChoices("INTENT_LLM_TEMPERATURE"))
    intent_llm_max_tokens: int = Field(default=256, validation_alias=AliasChoices("INTENT_LLM_MAX_TOKENS"))

    agent_max_steps: int = Field(default=5, validation_alias=AliasChoices("AGENT_MAX_STEPS"))
    agent_react_temperature: float = Field(default=0.2, validation_alias=AliasChoices("AGENT_REACT_TEMPERATURE"))
    agent_react_max_tokens: int = Field(default=512, validation_alias=AliasChoices("AGENT_REACT_MAX_TOKENS"))
    agent_history_max_turns: int = Field(default=4, validation_alias=AliasChoices("AGENT_HISTORY_MAX_TURNS"))
    agent_skip_final_llm_when_draft: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_SKIP_FINAL_LLM_WHEN_DRAFT"),
    )
    agent_draft_min_chars: int = Field(default=24, validation_alias=AliasChoices("AGENT_DRAFT_MIN_CHARS"))
    agent_react_observation_limit: int = Field(default=350, validation_alias=AliasChoices("AGENT_REACT_OBSERVATION_LIMIT"))
    agent_knowledge_content_limit: int = Field(default=180, validation_alias=AliasChoices("AGENT_KNOWLEDGE_CONTENT_LIMIT"))

    agent_tone_polish_enabled: bool = Field(default=True, validation_alias=AliasChoices("AGENT_TONE_POLISH_ENABLED"))
    agent_tone_polish_temperature: float = Field(
        default=0.72,
        validation_alias=AliasChoices("AGENT_TONE_POLISH_TEMPERATURE"),
    )
    agent_tone_polish_max_tokens: int = Field(default=384, validation_alias=AliasChoices("AGENT_TONE_POLISH_MAX_TOKENS"))
    agent_tone_polish_min_chars: int = Field(default=8, validation_alias=AliasChoices("AGENT_TONE_POLISH_MIN_CHARS"))
    agent_parallel_intent_knowledge: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENT_PARALLEL_INTENT_KNOWLEDGE"),
    )
    agent_early_draft_stream: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_EARLY_DRAFT_STREAM"),
    )
    agent_prefetch_focus_bundle: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_PREFETCH_FOCUS_BUNDLE"),
    )
    agent_react_stream_json: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_REACT_STREAM_JSON"),
    )
    agent_coalesce_focus_reads: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_COALESCE_FOCUS_READS"),
    )
    agent_hide_atomic_focus_reads: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENT_HIDE_ATOMIC_FOCUS_READS"),
    )

    error_recovery_use_llm: bool = Field(default=True, validation_alias=AliasChoices("ERROR_RECOVERY_USE_LLM"))
    error_recovery_max_tokens: int = Field(default=320, validation_alias=AliasChoices("ERROR_RECOVERY_MAX_TOKENS"))

    api_secret_key: str = "dev-secret-change-me"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator(
        "llm_api_key",
        "llm_base_url",
        "llm_model",
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
