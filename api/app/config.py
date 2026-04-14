from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    write_api_key: str | None = Field(default=None, alias="OPENAKASHIC_WRITE_API_KEY")
    cors_origins: str = Field(default="*", alias="OPENAKASHIC_CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
