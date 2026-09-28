"""add analysis jobs table

Revision ID: 0002_analysis_jobs
Revises: 0001_baseline
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_analysis_jobs"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("analysis_jobs"):
        return

    op.create_table(
        "analysis_jobs",
        sa.Column("run_id", sa.String(length=128), primary_key=True),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("queue_name", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("concurrency_group", sa.String(length=64), nullable=True),
        sa.Column("concurrency_limit", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("worker_heartbeat_at", sa.String(length=64), nullable=True),
        sa.Column("operator", sa.String(length=80), nullable=True),
        sa.Column("last_operator", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failed_node_id", sa.String(length=128), nullable=True),
        sa.Column("retry_from_node_id", sa.String(length=128), nullable=True),
        sa.Column("resume_from_node_id", sa.String(length=128), nullable=True),
        sa.Column("retry_of_job_id", sa.String(length=128), nullable=True),
        sa.Column("same_input_retry", sa.Boolean(), nullable=True),
        sa.Column("stale_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested_at", sa.String(length=64), nullable=True),
        sa.Column("history_json", sa.JSON(), nullable=True),
        sa.Column("recovery_json", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_analysis_jobs_job_id", "analysis_jobs", ["job_id"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index("ix_analysis_jobs_queue_name", "analysis_jobs", ["queue_name"])
    op.create_index("ix_analysis_jobs_concurrency_group", "analysis_jobs", ["concurrency_group"])
    op.create_index("ix_analysis_jobs_worker_id", "analysis_jobs", ["worker_id"])
    op.create_index("ix_analysis_jobs_worker_heartbeat_at", "analysis_jobs", ["worker_heartbeat_at"])
    op.create_index("ix_analysis_jobs_created_at", "analysis_jobs", ["created_at"])
    op.create_index("ix_analysis_jobs_updated_at", "analysis_jobs", ["updated_at"])
    op.create_index("ix_analysis_jobs_queued_at", "analysis_jobs", ["queued_at"])
    op.create_index("ix_analysis_jobs_started_at", "analysis_jobs", ["started_at"])
    op.create_index("ix_analysis_jobs_finished_at", "analysis_jobs", ["finished_at"])
    op.create_index("ix_analysis_jobs_cancel_requested_at", "analysis_jobs", ["cancel_requested_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("analysis_jobs"):
        op.drop_table("analysis_jobs")
