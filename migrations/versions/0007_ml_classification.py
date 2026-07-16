"""Add ML classification metadata.

Revision ID: 0007_ml_classification
Revises: 0006_order_search
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ml_classification"
down_revision: str | None = "0006_order_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column("model_version", sa.String(length=64), nullable=True),
    )
    op.drop_constraint("ck_classifications_method", "classifications", type_="check")
    op.create_check_constraint(
        "ck_classifications_method",
        "classifications",
        "method in ('rules','ml','manual')",
    )


def downgrade() -> None:
    op.execute(
        "update classifications set method = 'rules', model_version = null where method = 'ml'"
    )
    op.drop_constraint("ck_classifications_method", "classifications", type_="check")
    op.create_check_constraint(
        "ck_classifications_method",
        "classifications",
        "method in ('rules','manual')",
    )
    op.drop_column("classifications", "model_version")
