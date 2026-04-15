from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    cors_origins: str = Field(default="*", alias="CLOSED_AKASHIC_CORS_ORIGINS")
    closed_akashic_path: str = Field(
        default=str(PROJECT_ROOT),
        alias="CLOSED_AKASHIC_PATH",
    )
    bearer_token: str = Field(
        default="",
        validation_alias=AliasChoices("CLOSED_AKASHIC_BEARER_TOKEN", "CLOSED_AKASHIC_TOKEN"),
    )
    log_dir: str = Field(
        default=str(PROJECT_ROOT / "server" / "logs"),
        alias="CLOSED_AKASHIC_LOG_DIR",
    )
    recent_request_limit: int = Field(default=500, alias="CLOSED_AKASHIC_RECENT_REQUEST_LIMIT")
    public_base_url: str = Field(
        default="https://knowledge.openakashic.com",
        alias="CLOSED_AKASHIC_PUBLIC_BASE_URL",
    )
    writable_roots: str = Field(
        default="doc,personal_vault,assets",
        alias="CLOSED_AKASHIC_WRITABLE_ROOTS",
    )
    default_note_owner: str = Field(
        default="admin",
        alias="CLOSED_AKASHIC_DEFAULT_NOTE_OWNER",
    )
    admin_username: str = Field(
        default="admin",
        alias="CLOSED_AKASHIC_ADMIN_USERNAME",
    )
    admin_nickname: str = Field(
        default="admin",
        alias="CLOSED_AKASHIC_ADMIN_NICKNAME",
    )
    default_note_visibility: str = Field(
        default="private",
        alias="CLOSED_AKASHIC_DEFAULT_NOTE_VISIBILITY",
    )
    librarian_provider: str = Field(
        default="codex-style",
        alias="CLOSED_AKASHIC_LIBRARIAN_PROVIDER",
    )
    librarian_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ANTHROPIC_API_KEY",
            "CLOSED_AKASHIC_LIBRARIAN_API_KEY",
            "CODEX_API_KEY",
        ),
    )
    librarian_base_url: str = Field(
        default="",
        alias="CLOSED_AKASHIC_LIBRARIAN_BASE_URL",
    )
    librarian_model: str = Field(
        default="claude-haiku-4-5-20251001",
        alias="CLOSED_AKASHIC_LIBRARIAN_MODEL",
    )
    librarian_reasoning_effort: str = Field(
        default="medium",
        alias="CLOSED_AKASHIC_LIBRARIAN_REASONING_EFFORT",
    )
    librarian_project: str = Field(default="ops/librarian", alias="CLOSED_AKASHIC_LIBRARIAN_PROJECT")
    embedding_provider: str = Field(
        default="ollama",
        alias="CLOSED_AKASHIC_EMBEDDING_PROVIDER",
    )
    embedding_model: str = Field(
        default="nomic-embed-text",
        alias="CLOSED_AKASHIC_EMBEDDING_MODEL",
    )
    embedding_max_chars: int = Field(
        default=1200,
        alias="CLOSED_AKASHIC_EMBEDDING_MAX_CHARS",
    )
    embedding_batch_size: int = Field(
        default=16,
        alias="CLOSED_AKASHIC_EMBEDDING_BATCH_SIZE",
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        alias="CLOSED_AKASHIC_OLLAMA_BASE_URL",
    )
    semantic_cache_path: str = Field(
        default=str(PROJECT_ROOT / "server" / "logs" / "semantic-index.json"),
        alias="CLOSED_AKASHIC_SEMANTIC_CACHE_PATH",
    )
    user_store_path: str = Field(
        default=str(PROJECT_ROOT / "server" / "data" / "users.json"),
        alias="CLOSED_AKASHIC_USER_STORE_PATH",
    )
    core_api_url: str = Field(
        default="http://openakashic-api:8000",
        alias="OPENAKASHIC_CORE_API_URL",
    )
    core_api_write_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAKASHIC_CORE_WRITE_KEY", "OPENAKASHIC_WRITE_API_KEY"),
    )
    open_signup: bool = Field(
        default=False,
        alias="CLOSED_AKASHIC_OPEN_SIGNUP",
        description="Allow self-registration without admin invite. Set True only on trusted networks.",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _normalize_local_defaults(self) -> "Settings":
        legacy_vault = Path("/vault/closed")
        legacy_server_root = Path("/server")
        configured_root = Path(self.closed_akashic_path).expanduser()
        if configured_root == legacy_vault and not configured_root.exists():
            self.closed_akashic_path = str(PROJECT_ROOT)
            configured_root = Path(self.closed_akashic_path).expanduser()
        for field_name in ("log_dir", "semantic_cache_path", "user_store_path"):
            configured_path = Path(getattr(self, field_name)).expanduser()
            if legacy_server_root in configured_path.parents or configured_path == legacy_server_root:
                relative = configured_path.relative_to(legacy_server_root)
                setattr(self, field_name, str(configured_root / "server" / relative))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def writable_root_list(self) -> list[str]:
        return [item.strip() for item in self.writable_roots.split(",") if item.strip()]

    @property
    def librarian_effective_base_url(self) -> str:
        """provider=claude-cli이면 Anthropic OpenAI-compat endpoint를 기본으로 사용한다."""
        if self.librarian_base_url.strip():
            return self.librarian_base_url.strip()
        if self.librarian_provider.strip().lower() == "claude-cli":
            return "https://api.anthropic.com/v1"
        return ""

    @property
    def has_librarian_api_key(self) -> bool:
        return bool(self.librarian_api_key.strip())


def _load_openclaw_defaults(path: Path) -> dict[str, str]:
    # Kept as a compatibility stub for older imports. OpenClaw is now used as
    # an architecture reference, not as a runtime credential source.
    return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
