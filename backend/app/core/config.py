import re
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
    monitoring_enabled: bool = True
    queue_backend: Literal["database", "sqs"] = "database"
    monitor_regions: list[str] = Field(
        default_factory=lambda: ["local"], min_length=1, max_length=3
    )
    worker_region: str = "local"
    # Region -> queue URL. Credentials are supplied by the AWS task role, never config.
    sqs_queue_urls: dict[str, str] = Field(default_factory=dict)
    job_lease_seconds: int = Field(default=90, ge=60, le=300)
    max_job_attempts: int = Field(default=5, ge=1, le=10)
    check_retention_days: int = Field(default=90, ge=1, le=90)

    @model_validator(mode="after")
    def monitoring_safety(self) -> "Settings":
        regions = self.monitor_regions
        if len(set(regions)) != len(regions):
            raise ValueError("Monitoring regions must be unique")
        if self.queue_backend == "database":
            if regions != ["local"] or self.worker_region != "local":
                raise ValueError("Local workers must be labelled local, not an AWS region")
        else:
            for region in regions:
                if not re.fullmatch(r"[a-z]{2}-[a-z]+-[1-9]", region):
                    raise ValueError("Use supported commercial AWS region identifiers")
                url = self.sqs_queue_urls.get(region, "")
                if not re.fullmatch(
                    rf"https://sqs\.{re.escape(region)}\.amazonaws\.com/[0-9]{{12}}/[A-Za-z0-9_-]+",
                    url,
                ):
                    raise ValueError("Configure one HTTPS regional SQS queue URL per region")
            if self.worker_region not in regions:
                raise ValueError("Worker region must be enabled")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Distributed monitoring requires PostgreSQL")
        return self

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
