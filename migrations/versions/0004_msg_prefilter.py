"""Add message prefilter fields.

Revision ID: 0004_msg_prefilter
Revises: 0003_create_failed_tasks
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_msg_prefilter"
down_revision: str | None = "0003_create_failed_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("detected_language", sa.String(length=8), nullable=True))
    op.add_column("messages", sa.Column("passed_prefilter", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "passed_prefilter")
    op.drop_column("messages", "detected_language")
