"""Add order search indexes.

Revision ID: 0006_order_search
Revises: 0005_order_dedup
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_order_search"
down_revision: str | None = "0005_order_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists pg_trgm")
    op.execute(
        "create index if not exists ix_orders_title_trgm on orders using gin (title gin_trgm_ops)"
    )
    op.execute(
        "create index if not exists ix_orders_summary_trgm "
        "on orders using gin (summary gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("drop index if exists ix_orders_summary_trgm")
    op.execute("drop index if exists ix_orders_title_trgm")
