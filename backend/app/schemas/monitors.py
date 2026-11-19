import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_INTERVALS = {300, 600, 900, 1800, 3600}
MonitorStatus = Literal["UP", "DEGRADED", "DOWN", "UNKNOWN", "PAUSED"]


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    target_url: str = Field(min_length=1, max_length=2048)
    interval_seconds: int = Field(default=300, strict=True)
    timeout_seconds: int = Field(default=10, ge=1, le=10, strict=True)
    expected_status_min: int = Field(default=200, ge=100, le=599, strict=True)
    expected_status_max: int = Field(default=299, ge=100, le=599, strict=True)
    slow_threshold_ms: int = Field(default=2000, ge=100, le=10000, strict=True)
    failure_threshold: int = Field(default=3, ge=2, le=10, strict=True)
    recovery_threshold: int = Field(default=2, ge=1, le=10, strict=True)
    regions: list[str] | None = Field(default=None, min_length=1, max_length=3)

    @field_validator("interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise ValueError("Choose a check interval of 5, 10, 15, 30 or 60 minutes.")
        return value

    @model_validator(mode="after")
    def valid_policy(self) -> "MonitorCreate":
        if self.expected_status_min > self.expected_status_max:
            raise ValueError("Expected status minimum must not exceed maximum.")
        if self.regions is not None and len(self.regions) != len(set(self.regions)):
            raise ValueError("Regions must be unique.")
        return self


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_url: str | None = Field(default=None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, strict=True)
    timeout_seconds: int | None = Field(default=None, ge=1, le=10, strict=True)
    expected_status_min: int | None = Field(default=None, ge=100, le=599, strict=True)
    expected_status_max: int | None = Field(default=None, ge=100, le=599, strict=True)
    slow_threshold_ms: int | None = Field(default=None, ge=100, le=10000, strict=True)
    failure_threshold: int | None = Field(default=None, ge=2, le=10, strict=True)
    recovery_threshold: int | None = Field(default=None, ge=1, le=10, strict=True)
    regions: list[str] | None = Field(default=None, min_length=1, max_length=3)

    @field_validator("interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int | None) -> int | None:
        if value is not None:
            MonitorCreate.allowed_interval(value)
        return value

    @model_validator(mode="after")
    def no_null_fields(self) -> "MonitorUpdate":
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Monitor fields cannot be null.")
        if self.regions is not None and len(self.regions) != len(set(self.regions)):
            raise ValueError("Regions must be unique.")
        return self


class RegionalStatus(BaseModel):
    region: str
    status: MonitorStatus
    reason: str
    last_checked_at: datetime | None
    response_time_ms: float | None


class MonitorOut(BaseModel):
    id: uuid.UUID
    name: str
    target_url: str
    interval_seconds: int
    timeout_seconds: int
    expected_status_min: int
    expected_status_max: int
    slow_threshold_ms: int
    failure_threshold: int
    recovery_threshold: int
    regions: list[str]
    revision: int
    revision_started_at: datetime
    status: MonitorStatus
    status_reason: str
    provenance: Literal["REAL"] = "REAL"
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    availability_percent: float | None
    response_time_ms: float | None
    eligible_checks: int
    regional_status: list[RegionalStatus]


class MonitorList(BaseModel):
    items: list[MonitorOut]
    total: int
    limit: int
    offset: int
    quota: int
    checks_enabled: bool


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    revision: int
    region: str
    scheduled_at: datetime
    started_at: datetime
    checked_at: datetime
    outcome: Literal["UP", "DEGRADED", "FAILURE", "UNKNOWN"]
    http_status: int | None
    dns_ms: float | None
    connect_ms: float | None
    tls_ms: float | None
    ttfb_ms: float | None
    total_ms: float
    response_bytes: int
    redirect_count: int
    error_category: str | None
    provenance: Literal["REAL"] = "REAL"


class CheckList(BaseModel):
    items: list[CheckOut]
    total: int
    limit: int
    offset: int
    provenance: Literal["REAL"] = "REAL"


class SampleStats(BaseModel):
    samples: int
    eligible_checks: int
    successful_checks: int
    failed_checks: int
    inconclusive_checks: int
    availability_percent: float | None
    latency_samples: int
    average_ms: float | None
    median_ms: float | None
    p95_ms: float | None


class TrendPoint(SampleStats):
    start: datetime
    end: datetime


class RegionStats(SampleStats):
    region: str


class AnalyticsOut(SampleStats):
    window: str
    start: datetime
    end: datetime
    eligible_since: datetime
    revision: int
    estimated_downtime_seconds: float
    expected_slots: int
    observed_slots: int
    coverage_percent: float
    regions: list[RegionStats]
    trend: list[TrendPoint]
    provenance: Literal["REAL"] = "REAL"
    policy: str = (
        "Current configuration only. Missing, paused and inconclusive observations are not "
        "successes or failures; coverage is separate. "
        "Downtime is a sample-based estimate, not an SLA."
    )
