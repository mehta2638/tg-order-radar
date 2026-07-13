"""Initial MVP schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column[sa.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("role in ('admin','operator','viewer','service')", name="ck_users_role"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "telegram_accounts",
        uuid_pk(),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("phone_enc", sa.Text(), nullable=True),
        sa.Column("api_id_enc", sa.Text(), nullable=True),
        sa.Column("api_hash_enc", sa.Text(), nullable=True),
        sa.Column("session_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="disabled"),
        sa.Column("floodwait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status in ('active','floodwait','banned','disabled')",
            name="ck_telegram_accounts_status",
        ),
        sa.UniqueConstraint("label", name="uq_telegram_accounts_label"),
    )
    op.create_index("ix_telegram_accounts_status", "telegram_accounts", ["status"])

    op.create_table(
        "telegram_sources",
        uuid_pk(),
        sa.Column("tg_peer_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("normalized_username", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "access_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_validation",
        ),
        sa.Column("activity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "activity_status", sa.String(length=16), nullable=False, server_default="inactive"
        ),
        sa.Column("poll_mode", sa.String(length=16), nullable=False, server_default="poll"),
        sa.Column("participants_count", sa.Integer(), nullable=True),
        sa.Column("last_seen_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_until", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "type in ('channel','megagroup','unknown')", name="ck_telegram_sources_type"
        ),
        sa.CheckConstraint(
            "access_status in ("
            "'pending_validation','ok','not_found','private','banned','restricted','error'"
            ")",
            name="ck_telegram_sources_access_status",
        ),
        sa.CheckConstraint(
            "activity_score between 0 and 100", name="ck_telegram_sources_activity_score"
        ),
        sa.CheckConstraint(
            "activity_status in ('inactive','low','active','high')",
            name="ck_telegram_sources_activity_status",
        ),
        sa.CheckConstraint(
            "poll_mode in ('poll','realtime')", name="ck_telegram_sources_poll_mode"
        ),
        sa.UniqueConstraint("tg_peer_id", name="uq_telegram_sources_tg_peer_id"),
        sa.UniqueConstraint(
            "normalized_username",
            name="uq_telegram_sources_normalized_username",
        ),
    )
    op.create_index("ix_telegram_sources_access_status", "telegram_sources", ["access_status"])
    op.create_index("ix_telegram_sources_activity_status", "telegram_sources", ["activity_status"])
    op.create_index("ix_telegram_sources_enabled", "telegram_sources", ["enabled"])

    op.create_table(
        "keywords",
        uuid_pk(),
        sa.Column("phrase", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False, server_default="ru"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("is_regex", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("phrase", "lang", name="uq_keywords_phrase_lang"),
    )
    op.create_index("ix_keywords_enabled", "keywords", ["enabled"])
    op.create_index("ix_keywords_category", "keywords", ["category"])

    op.create_table(
        "negative_keywords",
        uuid_pk(),
        sa.Column("phrase", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False, server_default="ru"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_regex", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("phrase", "lang", name="uq_negative_keywords_phrase_lang"),
    )
    op.create_index("ix_negative_keywords_enabled", "negative_keywords", ["enabled"])

    op.create_table(
        "messages",
        uuid_pk(),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegram_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forward_original_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("message_url", sa.Text(), nullable=True),
        sa.Column("views_count", sa.Integer(), nullable=True),
        sa.Column("replies_count", sa.Integer(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("source_id", "tg_message_id", name="uq_messages_source_tg_message_id"),
    )
    op.create_index("ix_messages_source_id", "messages", ["source_id"])
    op.create_index("ix_messages_published_at", "messages", ["published_at"])
    op.create_index("ix_messages_content_hash", "messages", ["content_hash"])
    op.create_index("ix_messages_deleted_at", "messages", ["deleted_at"])

    op.create_table(
        "message_entities",
        uuid_pk(),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("value_norm", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "type in ("
            "'budget','deadline','contact','project_type','keyword_hit','negative_keyword_hit'"
            ")",
            name="ck_message_entities_type",
        ),
    )
    op.create_index("ix_message_entities_message_type", "message_entities", ["message_id", "type"])

    op.create_table(
        "classifications",
        uuid_pk(),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="rules"),
        sa.Column("manual_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "label in ("
            "'order','vacancy','service_ad','resume','partnership','spam','discussion','irrelevant'"
            ")",
            name="ck_classifications_label",
        ),
        sa.CheckConstraint("method in ('rules','manual')", name="ck_classifications_method"),
    )
    op.create_index("ix_classifications_message_id", "classifications", ["message_id"])
    op.create_index("ix_classifications_label", "classifications", ["label"])

    op.create_table(
        "duplicate_groups",
        uuid_pk(),
        sa.Column("canonical_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("similarity", sa.Numeric(5, 4), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False, server_default="1"),
        *timestamps(),
    )
    op.create_index(
        "ix_duplicate_groups_canonical_order_id", "duplicate_groups", ["canonical_order_id"]
    )

    op.create_table(
        "orders",
        uuid_pk(),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegram_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "duplicate_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duplicate_groups.id"),
            nullable=True,
        ),
        sa.Column("project_type", sa.String(length=32), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("budget_from", sa.Numeric(14, 2), nullable=True),
        sa.Column("budget_to", sa.Numeric(14, 2), nullable=True),
        sa.Column("budget_currency", sa.String(length=8), nullable=True),
        sa.Column("budget_negotiable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("deadline_text", sa.Text(), nullable=True),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("relevance_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("is_fresh", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *timestamps(),
        sa.CheckConstraint(
            "status in ('new','viewed','contacted','irrelevant','archived')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint("relevance_score between 0 and 100", name="ck_orders_relevance_score"),
        sa.UniqueConstraint("message_id", name="uq_orders_message_id"),
    )
    op.create_index("ix_orders_published_relevance", "orders", ["published_at", "relevance_score"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_project_type", "orders", ["project_type"])
    op.create_index("ix_orders_source_id", "orders", ["source_id"])

    op.create_table(
        "notification_deliveries",
        uuid_pk(),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="bot"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedup_key", sa.String(length=128), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("channel in ('bot')", name="ck_notification_deliveries_channel"),
        sa.CheckConstraint(
            "status in ('queued','sent','failed','skipped')",
            name="ck_notification_deliveries_status",
        ),
        sa.UniqueConstraint(
            "order_id",
            "user_id",
            "channel",
            name="uq_notification_delivery_target",
        ),
        sa.UniqueConstraint("dedup_key", name="uq_notification_deliveries_dedup_key"),
    )
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])

    op.create_table(
        "favorites",
        uuid_pk(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *timestamps(),
        sa.UniqueConstraint("user_id", "order_id", name="uq_favorites_user_order"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])

    op.create_table(
        "audit_logs",
        uuid_pk(),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity", sa.String(length=128), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity", "entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_favorites_user_id", table_name="favorites")
    op.drop_table("favorites")
    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_orders_source_id", table_name="orders")
    op.drop_index("ix_orders_project_type", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_published_relevance", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_duplicate_groups_canonical_order_id", table_name="duplicate_groups")
    op.drop_table("duplicate_groups")
    op.drop_index("ix_classifications_label", table_name="classifications")
    op.drop_index("ix_classifications_message_id", table_name="classifications")
    op.drop_table("classifications")
    op.drop_index("ix_message_entities_message_type", table_name="message_entities")
    op.drop_table("message_entities")
    op.drop_index("ix_messages_deleted_at", table_name="messages")
    op.drop_index("ix_messages_content_hash", table_name="messages")
    op.drop_index("ix_messages_published_at", table_name="messages")
    op.drop_index("ix_messages_source_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_negative_keywords_enabled", table_name="negative_keywords")
    op.drop_table("negative_keywords")
    op.drop_index("ix_keywords_category", table_name="keywords")
    op.drop_index("ix_keywords_enabled", table_name="keywords")
    op.drop_table("keywords")
    op.drop_index("ix_telegram_sources_enabled", table_name="telegram_sources")
    op.drop_index("ix_telegram_sources_activity_status", table_name="telegram_sources")
    op.drop_index("ix_telegram_sources_access_status", table_name="telegram_sources")
    op.drop_table("telegram_sources")
    op.drop_index("ix_telegram_accounts_status", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
