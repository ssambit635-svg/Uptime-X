import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.entities import Monitor

ALLOWED_INTERVALS = {300, 600, 900, 1800, 3600}


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    target_url: str = Field(min_length=1, max_length=2048)
    interval_seconds: int = Field(default=300, strict=True)
    timeout_seconds: int = Field(default=10, ge=1, le=10, strict=True)

    @field_validator("interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise ValueError("Choose a check interval of 5, 10, 15, 30 or 60 minutes.")
        return value


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_url: str | None = Field(default=None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, strict=True)
    timeout_seconds: int | None = Field(default=None, ge=1, le=10, strict=True)

    @field_validator("interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int | None) -> int | None:
        if value is not None and value not in ALLOWED_INTERVALS:
            raise ValueError("Choose a check interval of 5, 10, 15, 30 or 60 minutes.")
        return value

    @model_validator(mode="after")
    def no_null_fields(self) -> "MonitorUpdate":
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Monitor fields cannot be null.")
        return self


class MonitorOut(BaseModel):
    id: uuid.UUID
    name: str
    target_url: str
    interval_seconds: int
    timeout_seconds: int
    status: Literal["UNKNOWN", "PAUSED"]
    provenance: Literal["REAL"] = "REAL"
    created_at: datetime
    updated_at: datetime
    # Measurements are deliberately absent until a real check engine exists.
    last_checked_at: None = None
    availability_percent: None = None
    response_time_ms: None = None

    @classmethod
    def from_monitor(cls, monitor: Monitor) -> "MonitorOut":
        return cls(
            id=monitor.id,
            name=monitor.name,
            target_url=monitor.target_url,
            interval_seconds=monitor.interval_seconds,
            timeout_seconds=monitor.timeout_seconds,
            status="PAUSED" if monitor.is_paused else "UNKNOWN",
            created_at=monitor.created_at,
            updated_at=monitor.updated_at,
        )


class MonitorList(BaseModel):
    items: list[MonitorOut]
    total: int
    limit: int
    offset: int
    quota: int
    checks_enabled: Literal[False] = False
