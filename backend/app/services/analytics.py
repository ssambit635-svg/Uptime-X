import math
import statistics
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.entities import Monitor, MonitorCheck, utcnow
from app.schemas.monitors import (
    AnalyticsOut,
    MonitorOut,
    RegionalStatus,
    RegionStats,
    SampleStats,
    TrendPoint,
)

SUCCESS = ("UP", "DEGRADED")
ELIGIBLE = (*SUCCESS, "FAILURE")
WINDOWS = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def regional_state(
    monitor: Monitor, region: str, checks: list[MonitorCheck], now: datetime
) -> RegionalStatus:
    state = RegionalStatus(
        region=region,
        status="UNKNOWN",
        reason="No trustworthy observation yet.",
        last_checked_at=None,
        response_time_ms=None,
    )
    if monitor.is_paused:
        state.status, state.reason = "PAUSED", "Monitoring intentionally paused."
        return state
    if not checks:
        return state
    latest = checks[0]
    state.last_checked_at = latest.checked_at
    state.response_time_ms = latest.total_ms if latest.http_status is not None else None
    tolerance = timedelta(seconds=monitor.interval_seconds + 60)
    if latest.scheduled_at < now - tolerance or latest.checked_at < now - tolerance:
        state.reason = "Observation is stale; check worker and scheduler health."
        return state
    if latest.outcome == "UNKNOWN":
        state.reason = "Worker policy or execution was inconclusive; not evidence of downtime."
        return state
    consecutive = []
    previous = latest.scheduled_at
    for check in checks:
        if previous - check.scheduled_at > tolerance or check.outcome == "UNKNOWN":
            break
        consecutive.append(check)
        previous = check.scheduled_at
    if latest.outcome == "FAILURE":
        failures = 0
        for check in consecutive:
            if check.outcome != "FAILURE":
                break
            failures += 1
        state.status = "DOWN" if failures >= monitor.failure_threshold else "UNKNOWN"
        state.reason = f"{failures}/{monitor.failure_threshold} consecutive failed checks."
        return state
    successes = 0
    failures_before = 0
    for check in consecutive:
        if check.outcome in SUCCESS and failures_before == 0:
            successes += 1
        elif check.outcome == "FAILURE":
            failures_before += 1
        else:
            break
    if failures_before >= monitor.failure_threshold and successes < monitor.recovery_threshold:
        state.status, state.reason = (
            "DOWN",
            f"Recovering: {successes}/{monitor.recovery_threshold} successful checks.",
        )
    else:
        state.status = "DEGRADED" if latest.outcome == "DEGRADED" else "UP"
        state.reason = (
            "Response exceeded latency policy."
            if state.status == "DEGRADED"
            else "Recent response satisfies expected HTTP policy."
        )
    return state


def monitor_view(db: Session, monitor: Monitor, now: datetime | None = None) -> MonitorOut:
    now = now or utcnow()
    regions = []
    for region in monitor.regions:
        recent = list(
            db.scalars(
                select(MonitorCheck)
                .where(
                    MonitorCheck.monitor_id == monitor.id,
                    MonitorCheck.revision == monitor.revision,
                    MonitorCheck.region == region,
                )
                .order_by(MonitorCheck.scheduled_at.desc(), MonitorCheck.id.desc())
                .limit(25)
            )
        )
        regions.append(regional_state(monitor, region, recent, now))
    states = {item.status for item in regions}
    if monitor.is_paused:
        status, reason = "PAUSED", "Monitoring intentionally paused."
    elif not get_settings().monitoring_enabled:
        status, reason = "UNKNOWN", "Monitoring is disabled by the operator."
    elif "UNKNOWN" in states or not states:
        status, reason = "UNKNOWN", "At least one region lacks fresh, conclusive evidence."
    elif states == {"UP"}:
        status, reason = "UP", "All configured regions have recent successful observations."
    elif states == {"DOWN"}:
        status, reason = "DOWN", "Failure thresholds met in all configured regions."
    else:
        status, reason = "DEGRADED", "Latency policy exceeded or regions disagree."
    eligible, good = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((MonitorCheck.outcome.in_(SUCCESS), 1), else_=0)), 0),
        ).where(
            MonitorCheck.monitor_id == monitor.id,
            MonitorCheck.revision == monitor.revision,
            MonitorCheck.scheduled_at >= now - timedelta(days=1),
            MonitorCheck.outcome.in_(ELIGIBLE),
        )
    ).one()
    latest = max(
        (r for r in regions if r.last_checked_at), key=lambda r: r.last_checked_at, default=None
    )
    values = {
        key: getattr(monitor, key)
        for key in (
            "id",
            "name",
            "target_url",
            "interval_seconds",
            "timeout_seconds",
            "expected_status_min",
            "expected_status_max",
            "slow_threshold_ms",
            "failure_threshold",
            "recovery_threshold",
            "regions",
            "revision",
            "revision_started_at",
            "created_at",
            "updated_at",
        )
    }
    return MonitorOut(
        **values,
        status=status,
        status_reason=reason,
        last_checked_at=latest.last_checked_at if latest else None,
        response_time_ms=latest.response_time_ms if latest else None,
        availability_percent=round(good / eligible * 100, 3) if eligible else None,
        eligible_checks=eligible,
        regional_status=regions,
    )


def sample_stats(checks: list[MonitorCheck]) -> dict:
    eligible = [c for c in checks if c.outcome in ELIGIBLE]
    good = sum(c.outcome in SUCCESS for c in eligible)
    timings = sorted(c.total_ms for c in eligible if c.http_status is not None)
    return SampleStats(
        samples=len(checks),
        eligible_checks=len(eligible),
        successful_checks=good,
        failed_checks=len(eligible) - good,
        inconclusive_checks=len(checks) - len(eligible),
        availability_percent=round(good / len(eligible) * 100, 3) if eligible else None,
        latency_samples=len(timings),
        average_ms=round(statistics.mean(timings), 3) if timings else None,
        median_ms=round(statistics.median(timings), 3) if timings else None,
        p95_ms=timings[math.ceil(len(timings) * 0.95) - 1] if timings else None,
    ).model_dump()


def analytics(
    db: Session,
    monitor: Monitor,
    window: str,
    region: str | None = None,
    now: datetime | None = None,
) -> AnalyticsOut:
    now = now or utcnow()
    start = now - timedelta(days=WINDOWS[window])
    since = max(start, monitor.revision_started_at)
    query = select(MonitorCheck).where(
        MonitorCheck.monitor_id == monitor.id,
        MonitorCheck.revision == monitor.revision,
        MonitorCheck.scheduled_at >= since,
        MonitorCheck.scheduled_at <= now,
    )
    regions = [region] if region else monitor.regions
    query = query.where(MonitorCheck.region.in_(regions))
    checks = list(db.scalars(query.order_by(MonitorCheck.scheduled_at).limit(100_001)))
    if len(checks) > 100_000:
        raise AppError(413, "ANALYTICS_LIMIT", "Choose a shorter analytics window or one region.")
    groups: list[list[MonitorCheck]] = [[] for _ in range(120)]
    step = (now - start) / 120
    for check in checks:
        index = min(119, max(0, int((check.scheduled_at - start) / step)))
        groups[index].append(check)
    stats = sample_stats(checks)
    slots = max(
        1, math.floor(max(0, (now - since).total_seconds()) / monitor.interval_seconds) + 1
    ) * len(regions)
    observed = len(
        {
            (c.region, int((c.scheduled_at - since).total_seconds()) // monitor.interval_seconds)
            for c in checks
            if c.outcome in ELIGIBLE
        }
    )
    return AnalyticsOut(
        **stats,
        window=window,
        start=start,
        end=now,
        eligible_since=since,
        revision=monitor.revision,
        expected_slots=slots,
        observed_slots=min(observed, slots),
        coverage_percent=round(min(100, observed / slots * 100), 3),
        estimated_downtime_seconds=min(
            max(0, (now - since).total_seconds()),
            stats["failed_checks"] * monitor.interval_seconds / len(regions),
        ),
        regions=[
            RegionStats(region=r, **sample_stats([c for c in checks if c.region == r]))
            for r in regions
        ],
        trend=[
            TrendPoint(start=start + step * i, end=start + step * (i + 1), **sample_stats(group))
            for i, group in enumerate(groups)
        ],
    )
