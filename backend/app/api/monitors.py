import hashlib
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import current_user
from app.models.entities import Monitor, User, utcnow
from app.schemas.monitors import MonitorCreate, MonitorList, MonitorOut, MonitorUpdate
from app.services.url_policy import validate_target_url

router = APIRouter(prefix="/monitors", tags=["Monitors"])
MONITOR_QUOTA = 10


def fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def owned_monitor(db: Session, monitor_id: uuid.UUID, user_id: uuid.UUID) -> Monitor:
    monitor = db.scalar(select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user_id))
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
        items=[MonitorOut.from_monitor(monitor) for monitor in monitors],
        total=count,
        limit=limit,
        offset=offset,
        quota=MONITOR_QUOTA,
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
    monitor = Monitor(
        user_id=user.id,
        name=payload.name,
        target_url=target,
        target_fingerprint=fingerprint(target),
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(monitor)
    commit_monitor(db)
    return MonitorOut.from_monitor(monitor)


@router.get("/{monitor_id}", response_model=MonitorOut)
def get_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    return MonitorOut.from_monitor(owned_monitor(db, monitor_id, user.id))


@router.patch("/{monitor_id}", response_model=MonitorOut)
def update_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id)
    changes = payload.model_dump(exclude_unset=True)
    if "target_url" in changes:
        changes["target_url"] = validate_target_url(changes["target_url"])
        monitor.target_fingerprint = fingerprint(changes["target_url"])
    for name, value in changes.items():
        setattr(monitor, name, value)
    if changes:
        monitor.updated_at = utcnow()
    commit_monitor(db)
    return MonitorOut.from_monitor(monitor)


@router.post("/{monitor_id}/pause", response_model=MonitorOut)
def pause_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id)
    monitor.is_paused = True
    commit_monitor(db)
    return MonitorOut.from_monitor(monitor)


@router.post("/{monitor_id}/resume", response_model=MonitorOut)
def resume_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    monitor = owned_monitor(db, monitor_id, user.id)
    monitor.is_paused = False
    commit_monitor(db)
    return MonitorOut.from_monitor(monitor)


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    monitor = owned_monitor(db, monitor_id, user.id)
    db.delete(monitor)
    db.commit()
    return Response(status_code=204)
