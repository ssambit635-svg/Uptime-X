from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./.local/uptimex.db"
    session_cookie_secure: bool = False
    # Explicit, non-production mode for HTTPS previews embedded in a cross-site iframe.
    embedded_preview: bool = False
    preview_session_minutes: int = Field(default=60, ge=5, le=120)
    frontend_dist: Path | None = None
    session_hours: int = Field(default=168, ge=1, le=720)

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        if self.app_env == "production":
            if self.embedded_preview:
                raise ValueError("EMBEDDED_PREVIEW is only available outside production")
            if not self.session_cookie_secure:
                raise ValueError("Production requires SESSION_COOKIE_SECURE=true and HTTPS")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL via the psycopg driver")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.session_cookie_secure or self.embedded_preview

    @property
    def cookie_samesite(self) -> Literal["lax", "none"]:
        return "none" if self.embedded_preview else "lax"

    @property
    def cookie_name(self) -> str:
        return "__Host-uptimex_session" if self.cookie_secure else "uptimex_session"


@lru_cache
def get_settings() -> Settings:
    return Settings()
