from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    write_api_key: str | None = Field(default=None, alias="OPENAKASHIC_WRITE_API_KEY")
    cors_origins: str = Field(default="*", alias="OPENAKASHIC_CORS_ORIGINS")
    embedding_provider: str = Field(default="ollama", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="bge-m3", alias="EMBEDDING_MODEL")
    embedding_base_url: str = Field(default="http://ollama:11434", alias="EMBEDDING_BASE_URL")
    embedding_max_chars: int = Field(default=1200, alias="EMBEDDING_MAX_CHARS")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    embedding_keep_alive: str = Field(default="1h", alias="EMBEDDING_KEEP_ALIVE")
    retrieval_mode: str = Field(default="embedding", alias="RETRIEVAL_MODE")
    rrf_k: int = Field(default=60, alias="RRF_K")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("retrieval_mode")
    @classmethod
    def validate_retrieval_mode(cls, value: str) -> str:
        if value in {"embedding", "hybrid"}:
            return value
        return "embedding"

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
