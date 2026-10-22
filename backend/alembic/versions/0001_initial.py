"""initial schema — conversion_jobs table

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("server_host", sa.String(255), nullable=True),
        sa.Column("meeting_id", sa.String(255), nullable=True),
        sa.Column("playback_version", sa.String(16), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("format", sa.String(8), nullable=True),
        sa.Column("strategy", sa.String(24), nullable=True),
        sa.Column("include_webcam_pip", sa.Boolean(), nullable=True),
        sa.Column("assets_json", sa.JSON(), nullable=True),
        sa.Column("fidelity_notes", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("progress_detail", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_filename", sa.String(255), nullable=True),
        sa.Column("output_size", sa.Integer(), nullable=True),
        sa.Column("output_duration", sa.Float(), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("canceled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversion_jobs_status", "conversion_jobs", ["status"])
    op.create_index("ix_conversion_jobs_expires_at", "conversion_jobs", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_conversion_jobs_expires_at", table_name="conversion_jobs")
    op.drop_index("ix_conversion_jobs_status", table_name="conversion_jobs")
    op.drop_table("conversion_jobs")
