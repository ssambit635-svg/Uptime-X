"""Bounded real monitoring, durable jobs, leases, and service heartbeats.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("monitors") as batch:
        for name, default in (
            ("expected_status_min", 200),
            ("expected_status_max", 299),
            ("slow_threshold_ms", 2000),
            ("failure_threshold", 3),
            ("recovery_threshold", 2),
            ("revision", 1),
        ):
            batch.add_column(
                sa.Column(name, sa.Integer(), nullable=False, server_default=str(default))
            )
        batch.add_column(
            sa.Column("regions", sa.JSON(), nullable=False, server_default='["local"]')
        )
        batch.add_column(
            sa.Column(
                "next_check_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(
            sa.Column(
                "revision_started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(sa.Column("last_manual_check_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_monitors_next_check_at", ["next_check_at"])
    op.create_table(
        "check_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "monitor_id",
            sa.Uuid(),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("last_error", sa.String(40)),
        sa.UniqueConstraint("monitor_id", "region", "revision", "scheduled_at", name="uq_job_slot"),
    )
    op.create_index("ix_check_jobs_monitor_id", "check_jobs", ["monitor_id"])
    op.create_index("ix_jobs_ready", "check_jobs", ["state", "region", "available_at"])
    op.create_table(
        "monitor_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("check_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "monitor_id",
            sa.Uuid(),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(40), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("http_status", sa.Integer()),
        *[sa.Column(name, sa.Float()) for name in ("dns_ms", "connect_ms", "tls_ms", "ttfb_ms")],
        sa.Column("total_ms", sa.Float(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("redirect_count", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(40)),
    )
    op.create_index("ix_checks_monitor_time", "monitor_checks", ["monitor_id", "scheduled_at"])
    op.create_index("ix_checks_region_time", "monitor_checks", ["region", "checked_at"])
    op.create_table(
        "service_heartbeats",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("region", sa.String(40), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_service_heartbeats_seen_at", "service_heartbeats", ["seen_at"])


def downgrade() -> None:
    # Destructive rollback: export history first; see docs/operations.md.
    op.drop_table("service_heartbeats")
    op.drop_table("monitor_checks")
    op.drop_table("check_jobs")
    with op.batch_alter_table("monitors") as batch:
        batch.drop_index("ix_monitors_next_check_at")
        for name in (
            "last_manual_check_at",
            "revision_started_at",
            "next_check_at",
            "revision",
            "regions",
            "recovery_threshold",
            "failure_threshold",
            "slow_threshold_ms",
            "expected_status_max",
            "expected_status_min",
        ):
            batch.drop_column(name)
