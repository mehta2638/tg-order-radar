"""Add order duplicate fingerprint.

Revision ID: 0005_order_dedup
Revises: 0004_msg_prefilter
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_order_dedup"
down_revision: str | None = "0004_msg_prefilter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("duplicate_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_orders_duplicate_fingerprint",
        "orders",
        ["duplicate_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_duplicate_fingerprint", table_name="orders")
    op.drop_column("orders", "duplicate_fingerprint")
