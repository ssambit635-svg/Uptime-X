from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import current_user
from app.models.entities import CheckJob, Monitor, ServiceHeartbeat, User, utcnow
from app.services.jobs import ACTIVE

router = APIRouter(tags=["Operations"])


@router.get("/operations")
def operations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    now = utcnow()
    counts = dict(
        db.execute(
            select(CheckJob.state, func.count())
            .join(Monitor, Monitor.id == CheckJob.monitor_id)
            .where(Monitor.user_id == user.id)
            .group_by(CheckJob.state)
        ).all()
    )
    oldest = db.scalar(
        select(func.min(CheckJob.scheduled_at))
        .join(Monitor, Monitor.id == CheckJob.monitor_id)
        .where(Monitor.user_id == user.id, CheckJob.state.in_(ACTIVE))
    )
    scheduler = db.scalar(
        select(func.max(ServiceHeartbeat.seen_at)).where(ServiceHeartbeat.role == "scheduler")
    )
    regions = []
    for region in settings.monitor_regions:
        latest = db.scalar(
            select(func.max(ServiceHeartbeat.seen_at)).where(
                ServiceHeartbeat.role == "worker", ServiceHeartbeat.region == region
            )
        )
        healthy = (
            db.scalar(
                select(func.count())
                .select_from(ServiceHeartbeat)
                .where(
                    ServiceHeartbeat.role == "worker",
                    ServiceHeartbeat.region == region,
                    ServiceHeartbeat.seen_at >= now - timedelta(seconds=90),
                )
            )
            or 0
        )
        regions.append({"region": region, "healthy_workers": healthy, "last_seen_at": latest})
    return {
        "checks_enabled": settings.monitoring_enabled,
        "queue_transport": settings.queue_backend,
        "configured_regions": settings.monitor_regions,
        "retention_days": settings.check_retention_days,
        "scheduler": {
            "last_seen_at": scheduler,
            "healthy": bool(scheduler and scheduler >= now - timedelta(seconds=180)),
        },
        "regions": regions,
        "jobs": {
            "pending": sum(counts.get(state, 0) for state in ACTIVE),
            "dead": counts.get("DEAD", 0),
            "oldest_pending_seconds": max(0, (now - oldest).total_seconds()) if oldest else None,
        },
    }
