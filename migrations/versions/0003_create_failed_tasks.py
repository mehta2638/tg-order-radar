"""Create failed tasks dead-letter storage.

Revision ID: 0003_create_failed_tasks
Revises: 0002_add_source_floodwait_status
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_create_failed_tasks"
down_revision: str | None = "0002_add_source_floodwait_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "failed_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_name", sa.String(length=256), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("queue", sa.String(length=128), nullable=True),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("kwargs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("dedup_key", name="uq_failed_tasks_dedup_key"),
    )
    op.create_index("ix_failed_tasks_task_name", "failed_tasks", ["task_name"])
    op.create_index("ix_failed_tasks_created_at", "failed_tasks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_failed_tasks_created_at", table_name="failed_tasks")
    op.drop_index("ix_failed_tasks_task_name", table_name="failed_tasks")
    op.drop_table("failed_tasks")
