from datetime import timedelta

import pytest

from app.models.entities import utcnow
from app.services.analytics import analytics, monitor_view


def test_empty_and_stale_observations_never_imply_up(db, monitor, record):
    assert monitor_view(db, monitor).status == "UNKNOWN"
    assert analytics(db, monitor, "24h").availability_percent is None
    record(monitor, age=361)
    view = monitor_view(db, monitor)
    assert view.status == "UNKNOWN" and view.last_checked_at is not None
    assert view.regional_status[0].reason.startswith("Observation is stale")


def test_failure_and_recovery_thresholds_do_not_flap(db, monitor, record):
    for age in [900, 600, 300]:
        record(monitor, "FAILURE", age=age, status=503)
    assert monitor_view(db, monitor).status == "DOWN"
    record(monitor, age=0)
    assert monitor_view(db, monitor).status == "DOWN"
    # Same region, unique scheduled slot, distinct real observations.
    record(monitor, age=-1)
    assert monitor_view(db, monitor, utcnow() + timedelta(seconds=1)).status == "UP"


def test_isolated_failure_and_inconclusive_policy_are_unknown(db, monitor, record):
    record(monitor, "FAILURE", status=503)
    assert monitor_view(db, monitor).status == "UNKNOWN"
    record(monitor, "UNKNOWN", age=-1, status=None)
    assert monitor_view(db, monitor).status == "UNKNOWN"


def test_missing_intervals_break_consecutive_failure_evidence(db, monitor, record):
    record(monitor, "FAILURE", age=0)
    record(monitor, "FAILURE", age=700)
    record(monitor, "FAILURE", age=1000)
    assert monitor_view(db, monitor).status == "UNKNOWN"


def test_regions_disagree_and_missing_region_is_never_healthy(db, monitor, record):
    monitor.regions = ["ap-south-1", "eu-west-1"]
    record(monitor, region="ap-south-1")
    assert monitor_view(db, monitor).status == "UNKNOWN"
    record(monitor, "DEGRADED", region="eu-west-1")
    assert monitor_view(db, monitor).status == "DEGRADED"
    assert {r.region for r in monitor_view(db, monitor).regional_status} == set(monitor.regions)
    monitor.is_paused = True
    assert monitor_view(db, monitor).status == "PAUSED"


@pytest.mark.parametrize("window", ["24h", "7d", "30d", "90d"])
def test_availability_math_missing_data_latency_percentiles_and_buckets(
    db, monitor, record, window
):
    monitor.revision_started_at = utcnow() - timedelta(hours=1)
    db.commit()
    record(monitor, age=1200, total=10)
    record(monitor, "DEGRADED", age=900, total=30)
    record(monitor, "FAILURE", age=600, total=50, status=503)
    record(monitor, "UNKNOWN", age=300, total=90, status=None)
    data = analytics(db, monitor, window)
    assert data.samples == 4 and data.eligible_checks == 3 and data.inconclusive_checks == 1
    assert data.availability_percent == 66.667
    assert data.average_ms == data.median_ms == 30 and data.p95_ms == 50
    assert 0 < data.coverage_percent < 100 and data.estimated_downtime_seconds == 300
    assert len(data.trend) == 120 and sum(b.samples for b in data.trend) == 4
    assert any(b.availability_percent is None for b in data.trend)
    assert data.regions[0].eligible_checks == 3
    assert data.provenance == "REAL"


def test_late_completion_does_not_replace_more_recent_scheduled_result(db, monitor, record):
    recent = record(monitor, age=0)
    older = record(monitor, "FAILURE", age=300, status=503)
    older.checked_at = recent.checked_at + timedelta(seconds=10)
    db.commit()
    assert monitor_view(db, monitor).status == "UP"


def test_current_policy_metrics_exclude_previous_revisions(db, monitor, record):
    record(monitor, "FAILURE", revision=1)
    monitor.revision = 2
    monitor.revision_started_at = utcnow() - timedelta(seconds=1)
    record(monitor, revision=2)
    assert analytics(db, monitor, "24h").availability_percent == 100
    assert monitor_view(db, monitor).eligible_checks == 1
