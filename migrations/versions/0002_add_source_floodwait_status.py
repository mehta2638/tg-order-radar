"""Add floodwait access status for Telegram sources.

Revision ID: 0002_add_source_floodwait_status
Revises: 0001_initial_schema
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_add_source_floodwait_status"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_telegram_sources_access_status",
        "telegram_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_sources_access_status",
        "telegram_sources",
        "access_status in ("
        "'pending_validation','ok','not_found','private','banned','restricted','floodwait','error'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_telegram_sources_access_status",
        "telegram_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_sources_access_status",
        "telegram_sources",
        "access_status in ("
        "'pending_validation','ok','not_found','private','banned','restricted','error'"
        ")",
    )
