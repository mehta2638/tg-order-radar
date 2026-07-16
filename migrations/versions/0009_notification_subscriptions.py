"""Add notification subscriptions and deferred deliveries.

Revision ID: 0009_notification_subscriptions
Revises: 0008_semantic_dedup
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_notification_subscriptions"
down_revision: str | None = "0008_semantic_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("min_relevance_score", sa.Integer(), nullable=True),
        sa.Column(
            "project_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("budget_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("budget_max", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "currencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "positive_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("quiet_hours_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column("freshness_days", sa.Integer(), nullable=True),
        sa.Column("max_notifications_per_period", sa.Integer(), nullable=True),
        sa.Column(
            "rate_limit_period_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column("similar_cooldown_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "min_relevance_score is null or (min_relevance_score between 0 and 100)",
            name="ck_notification_subscriptions_min_relevance",
        ),
        sa.CheckConstraint(
            "budget_min is null or budget_max is null or budget_min <= budget_max",
            name="ck_notification_subscriptions_budget_range",
        ),
        sa.CheckConstraint(
            "freshness_days is null or freshness_days >= 1",
            name="ck_notification_subscriptions_freshness",
        ),
        sa.CheckConstraint(
            "max_notifications_per_period is null or max_notifications_per_period >= 1",
            name="ck_notification_subscriptions_rate_limit",
        ),
        sa.CheckConstraint(
            "rate_limit_period_minutes >= 1",
            name="ck_notification_subscriptions_rate_period",
        ),
        sa.CheckConstraint(
            "similar_cooldown_minutes is null or similar_cooldown_minutes >= 1",
            name="ck_notification_subscriptions_cooldown",
        ),
    )
    op.create_index(
        "ix_notification_subscriptions_user_id",
        "notification_subscriptions",
        ["user_id"],
    )
    op.create_index(
        "ix_notification_subscriptions_enabled",
        "notification_subscriptions",
        ["enabled"],
    )

    op.add_column(
        "notification_deliveries",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_deliveries_subscription_id",
        "notification_deliveries",
        "notification_subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        alter table notification_deliveries
            drop constraint if exists ck_notification_deliveries_status;
        """
    )
    op.execute(
        """
        alter table notification_deliveries
            add constraint ck_notification_deliveries_status
            check (status in ('queued','sent','failed','skipped','deferred'));
        """
    )
    op.create_index(
        "ix_notification_deliveries_scheduled_for",
        "notification_deliveries",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_scheduled_for",
        table_name="notification_deliveries",
    )
    op.drop_constraint(
        "fk_notification_deliveries_subscription_id",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_column("notification_deliveries", "subscription_id")
    op.drop_column("notification_deliveries", "scheduled_for")
    op.execute(
        """
        alter table notification_deliveries
            drop constraint if exists ck_notification_deliveries_status;
        """
    )
    op.execute(
        """
        alter table notification_deliveries
            add constraint ck_notification_deliveries_status
            check (status in ('queued','sent','failed','skipped'));
        """
    )
    op.drop_index(
        "ix_notification_subscriptions_enabled",
        table_name="notification_subscriptions",
    )
    op.drop_index(
        "ix_notification_subscriptions_user_id",
        table_name="notification_subscriptions",
    )
    op.drop_table("notification_subscriptions")
