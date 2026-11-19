import hashlib
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import current_user
from app.models.entities import Monitor, MonitorCheck, User, utcnow
from app.schemas.monitors import (
    AnalyticsOut,
    CheckList,
    CheckOut,
    MonitorCreate,
    MonitorList,
    MonitorOut,
    MonitorUpdate,
)
from app.services.analytics import analytics, monitor_view
from app.services.jobs import enqueue_monitor, invalidate_jobs
from app.services.url_policy import validate_target_url

router = APIRouter(prefix="/monitors", tags=["Monitors"])
MONITOR_QUOTA = 10


def fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def owned_monitor(
    db: Session, monitor_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> Monitor:
    query = select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user_id)
    monitor = db.scalar(query.with_for_update() if lock else query)
    if monitor is None:
        # Same response for missing and another tenant's records.
        raise AppError(404, "MONITOR_NOT_FOUND", "This monitor could not be found.")
    return monitor


def commit_monitor(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            409, "DUPLICATE_MONITOR", "You already have a monitor for this URL."
        ) from exc


@router.get("", response_model=MonitorList)
def list_monitors(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorList:
    count = (
        db.scalar(select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id)) or 0
    )
    monitors = db.scalars(
        select(Monitor)
        .where(Monitor.user_id == user.id)
        .order_by(Monitor.created_at.desc(), Monitor.id)
        .offset(offset)
        .limit(limit)
    )
    return MonitorList(
        items=[monitor_view(db, monitor) for monitor in monitors],
        total=count,
        limit=limit,
        offset=offset,
        quota=MONITOR_QUOTA,
        checks_enabled=get_settings().monitoring_enabled,
    )


@router.post("", response_model=MonitorOut, status_code=201)
def create_monitor(
    payload: MonitorCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    target = validate_target_url(payload.target_url)
    # Serialize creates per owner on PostgreSQL so concurrent requests cannot exceed quota.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    count = (
        db.scalar(select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id)) or 0
    )
    if count >= MONITOR_QUOTA:
        raise AppError(409, "MONITOR_QUOTA", "Your workspace has reached its 10-monitor limit.")
    fields = payload.model_dump(exclude={"target_url", "regions"})
    regions = payload.regions or get_settings().monitor_regions
    validate_regions(regions)
    monitor = Monitor(
        user_id=user.id,
        target_url=target,
        target_fingerprint=fingerprint(target),
        regions=regions,
        **fields,
    )
    db.add(monitor)
    commit_monitor(db)
    return monitor_view(db, monitor)


@router.get("/{monitor_id}", response_model=MonitorOut)
def get_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    return monitor_view(db, owned_monitor(db, monitor_id, user.id))


@router.patch("/{monitor_id}", response_model=MonitorOut)
def update_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    if "target_url" in changes:
        changes["target_url"] = validate_target_url(changes["target_url"])
    if "regions" in changes:
        validate_regions(changes["regions"])
    low = changes.get("expected_status_min", monitor.expected_status_min)
    high = changes.get("expected_status_max", monitor.expected_status_max)
    if low > high:
        raise AppError(
            422, "INVALID_POLICY", "Expected HTTP status minimum must not exceed maximum."
        )
    if any(key != "name" and getattr(monitor, key) != value for key, value in changes.items()):
        invalidate_jobs(db, monitor)
    for name, value in changes.items():
        setattr(monitor, name, value)
    if "target_url" in changes:
        monitor.target_fingerprint = fingerprint(changes["target_url"])
    if changes:
        monitor.updated_at = utcnow()
    commit_monitor(db)
    return monitor_view(db, monitor)


@router.post("/{monitor_id}/pause", response_model=MonitorOut)
def pause_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id, lock=True)
    if not monitor.is_paused:
        invalidate_jobs(db, monitor)
    monitor.is_paused = True
    commit_monitor(db)
    return monitor_view(db, monitor)


@router.post("/{monitor_id}/resume", response_model=MonitorOut)
def resume_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id, lock=True)
    if monitor.is_paused:
        invalidate_jobs(db, monitor)
    monitor.is_paused = False
    commit_monitor(db)
    return monitor_view(db, monitor)


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    monitor = owned_monitor(db, monitor_id, user.id, lock=True)
    db.delete(monitor)
    db.commit()
    return Response(status_code=204)


def validate_regions(regions: list[str]) -> None:
    if any(region not in get_settings().monitor_regions for region in regions):
        raise AppError(422, "UNAVAILABLE_REGION", "Choose an enabled worker region.")


@router.post("/{monitor_id}/check", status_code=202)
def request_check(
    monitor_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    monitor = owned_monitor(db, monitor_id, user.id, lock=True)
    if monitor.is_paused:
        raise AppError(409, "MONITOR_PAUSED", "Resume the monitor before requesting a check.")
    settings = get_settings()
    if not settings.monitoring_enabled:
        raise AppError(503, "MONITORING_DISABLED", "Monitoring is disabled by the operator.")
    validate_regions(monitor.regions)
    now = utcnow()
    if monitor.last_manual_check_at and monitor.last_manual_check_at > now - timedelta(seconds=60):
        raise AppError(
            429,
            "CHECK_RATE_LIMITED",
            "Wait one minute before requesting another check.",
            {"Retry-After": "60"},
        )
    jobs = enqueue_monitor(db, monitor, settings, now)
    monitor.last_manual_check_at = now
    db.commit()
    return {"job_ids": [str(job.id) for job in jobs], "state": "QUEUED"}


@router.get("/{monitor_id}/checks", response_model=CheckList)
def history(
    monitor_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
    region: str | None = Query(default=None, max_length=40),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CheckList:
    monitor = owned_monitor(db, monitor_id, user.id)
    if region and region not in monitor.regions:
        raise AppError(422, "UNAVAILABLE_REGION", "Choose one of this monitor's regions.")
    clauses = [MonitorCheck.monitor_id == monitor_id]
    if region:
        clauses.append(MonitorCheck.region == region)
    total = db.scalar(select(func.count()).select_from(MonitorCheck).where(*clauses)) or 0
    checks = db.scalars(
        select(MonitorCheck)
        .where(*clauses)
        .order_by(MonitorCheck.scheduled_at.desc(), MonitorCheck.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return CheckList(
        items=[CheckOut.model_validate(check) for check in checks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{monitor_id}/analytics", response_model=AnalyticsOut)
def monitor_analytics(
    monitor_id: uuid.UUID,
    window: str = Query(default="24h", pattern="^(24h|7d|30d|90d)$"),
    region: str | None = Query(default=None, max_length=40),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AnalyticsOut:
    monitor = owned_monitor(db, monitor_id, user.id)
    if region and region not in monitor.regions:
        raise AppError(422, "UNAVAILABLE_REGION", "Choose one of this monitor's regions.")
    return analytics(db, monitor, window, region)
