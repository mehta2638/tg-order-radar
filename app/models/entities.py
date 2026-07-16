from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('admin','operator','viewer','service')", name="role"),
        Index("ix_users_role", "role"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    favorites: Mapped[list[Favorite]] = relationship(back_populates="user")
    notification_subscriptions: Mapped[list[NotificationSubscription]] = relationship(
        back_populates="user"
    )


class TelegramAccount(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "telegram_accounts"
    __table_args__ = (
        CheckConstraint(
            "status in ('active','floodwait','banned','disabled')",
            name="status",
        ),
        Index("ix_telegram_accounts_status", "status"),
    )

    label: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    phone_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_id_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_hash_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="disabled")
    floodwait_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramSource(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "telegram_sources"
    __table_args__ = (
        UniqueConstraint("tg_peer_id", name="uq_telegram_sources_tg_peer_id"),
        UniqueConstraint("normalized_username", name="uq_telegram_sources_normalized_username"),
        CheckConstraint(
            "type in ('channel','megagroup','unknown')",
            name="type",
        ),
        CheckConstraint(
            "access_status in ("
            "'pending_validation','ok','not_found','private','banned','restricted','floodwait','error'"
            ")",
            name="access_status",
        ),
        CheckConstraint("activity_score between 0 and 100", name="activity_score"),
        CheckConstraint(
            "activity_status in ('inactive','low','active','high')",
            name="activity_status",
        ),
        CheckConstraint("poll_mode in ('poll','realtime')", name="poll_mode"),
        Index("ix_telegram_sources_access_status", "access_status"),
        Index("ix_telegram_sources_activity_status", "activity_status"),
        Index("ix_telegram_sources_enabled", "enabled"),
    )

    tg_peer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    access_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_validation",
    )
    activity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_status: Mapped[str] = mapped_column(String(16), nullable=False, default="inactive")
    poll_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="poll")
    participants_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[Message]] = relationship(back_populates="source")


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # DB physical PK is (id, published_at) for RANGE partitioning; ORM keeps id PK
        # because message UUIDs are globally unique and session.get()/FKs use id.
        UniqueConstraint(
            "source_id",
            "tg_message_id",
            "published_at",
            name="uq_messages_source_tg_message_published_at",
        ),
        Index("ix_messages_source_id", "source_id"),
        Index("ix_messages_published_at", "published_at"),
        Index("ix_messages_content_hash", "content_hash"),
        Index("ix_messages_deleted_at", "deleted_at"),
        Index("ix_messages_source_tg_message_id", "source_id", "tg_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forward_original_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    passed_prefilter: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    views_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    source: Mapped[TelegramSource] = relationship(back_populates="messages")
    entities: Mapped[list[MessageEntity]] = relationship(
        back_populates="message",
        primaryjoin="Message.id == MessageEntity.message_id",
        foreign_keys="MessageEntity.message_id",
    )
    classifications: Mapped[list[Classification]] = relationship(
        back_populates="message",
        primaryjoin="Message.id == Classification.message_id",
        foreign_keys="Classification.message_id",
    )
    order: Mapped[Order | None] = relationship(
        back_populates="message",
        primaryjoin="Message.id == Order.message_id",
        foreign_keys="Order.message_id",
        uselist=False,
    )


class Keyword(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("phrase", "lang", name="uq_keywords_phrase_lang"),
        Index("ix_keywords_enabled", "enabled"),
        Index("ix_keywords_category", "category"),
    )

    phrase: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    is_regex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NegativeKeyword(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "negative_keywords"
    __table_args__ = (
        UniqueConstraint("phrase", "lang", name="uq_negative_keywords_phrase_lang"),
        Index("ix_negative_keywords_enabled", "enabled"),
    )

    phrase: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_regex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MessageEntity(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "message_entities"
    __table_args__ = (
        CheckConstraint(
            "type in ("
            "'budget','deadline','contact','project_type','keyword_hit','negative_keyword_hit'"
            ")",
            name="type",
        ),
        Index("ix_message_entities_message_type", "message_id", "type"),
    )

    # Logical reference only: partitioned messages use PK (id, published_at).
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_norm: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    message: Mapped[Message] = relationship(
        back_populates="entities",
        primaryjoin="MessageEntity.message_id == Message.id",
        foreign_keys="MessageEntity.message_id",
    )


class Classification(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "classifications"
    __table_args__ = (
        CheckConstraint(
            "label in ("
            "'order','vacancy','service_ad','resume','partnership','spam','discussion','irrelevant'"
            ")",
            name="label",
        ),
        CheckConstraint("method in ('rules','ml','manual')", name="method"),
        Index("ix_classifications_message_id", "message_id"),
        Index("ix_classifications_label", "label"),
    )

    # Logical reference only: partitioned messages use PK (id, published_at).
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="rules")
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    message: Mapped[Message] = relationship(
        back_populates="classifications",
        primaryjoin="Classification.message_id == Message.id",
        foreign_keys="Classification.message_id",
    )


class DuplicateGroup(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "duplicate_groups"
    __table_args__ = (Index("ix_duplicate_groups_canonical_order_id", "canonical_order_id"),)

    canonical_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    similarity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    orders: Mapped[list[Order]] = relationship(back_populates="duplicate_group")


class Order(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_orders_message_id"),
        CheckConstraint(
            "status in ('new','viewed','contacted','irrelevant','archived')",
            name="status",
        ),
        CheckConstraint("relevance_score between 0 and 100", name="relevance_score"),
        Index("ix_orders_published_relevance", "published_at", "relevance_score"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_project_type", "project_type"),
        Index("ix_orders_source_id", "source_id"),
        Index("ix_orders_duplicate_fingerprint", "duplicate_fingerprint"),
    )

    # Logical reference only: partitioned messages use PK (id, published_at).
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    duplicate_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("duplicate_groups.id"),
        nullable=True,
    )
    project_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_from: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_to: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    budget_negotiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    contacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duplicate_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    is_fresh: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    message: Mapped[Message] = relationship(
        back_populates="order",
        primaryjoin="Order.message_id == Message.id",
        foreign_keys="Order.message_id",
    )
    duplicate_group: Mapped[DuplicateGroup | None] = relationship(back_populates="orders")
    notification_deliveries: Mapped[list[NotificationDelivery]] = relationship(
        back_populates="order"
    )
    favorites: Mapped[list[Favorite]] = relationship(back_populates="order")


class NotificationDelivery(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("order_id", "user_id", "channel", name="uq_notification_delivery_target"),
        CheckConstraint("channel in ('bot')", name="channel"),
        CheckConstraint(
            "status in ('queued','sent','failed','skipped','deferred')",
            name="status",
        ),
        Index("ix_notification_deliveries_status", "status"),
        Index("ix_notification_deliveries_scheduled_for", "scheduled_for"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="bot")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[Order] = relationship(back_populates="notification_deliveries")
    subscription: Mapped[NotificationSubscription | None] = relationship(
        back_populates="deliveries"
    )


class NotificationSubscription(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "min_relevance_score is null or (min_relevance_score between 0 and 100)",
            name="ck_notification_subscriptions_min_relevance",
        ),
        CheckConstraint(
            "budget_min is null or budget_max is null or budget_min <= budget_max",
            name="ck_notification_subscriptions_budget_range",
        ),
        CheckConstraint(
            "freshness_days is null or freshness_days >= 1",
            name="ck_notification_subscriptions_freshness",
        ),
        CheckConstraint(
            "max_notifications_per_period is null or max_notifications_per_period >= 1",
            name="ck_notification_subscriptions_rate_limit",
        ),
        CheckConstraint(
            "rate_limit_period_minutes >= 1",
            name="ck_notification_subscriptions_rate_period",
        ),
        CheckConstraint(
            "similar_cooldown_minutes is null or similar_cooldown_minutes >= 1",
            name="ck_notification_subscriptions_cooldown",
        ),
        Index("ix_notification_subscriptions_user_id", "user_id"),
        Index("ix_notification_subscriptions_enabled", "enabled"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_types: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currencies: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    positive_keywords: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    negative_keywords: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    freshness_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_notifications_per_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_period_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    similar_cooldown_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="notification_subscriptions")
    deliveries: Mapped[list[NotificationDelivery]] = relationship(back_populates="subscription")


class Favorite(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "order_id", name="uq_favorites_user_order"),
        Index("ix_favorites_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="favorites")
    order: Mapped[Order] = relationship(back_populates="favorites")


class AuditLog(UuidPkMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class FailedTask(UuidPkMixin, Base):
    __tablename__ = "failed_tasks"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_failed_tasks_dedup_key"),
        Index("ix_failed_tasks_task_name", "task_name"),
        Index("ix_failed_tasks_created_at", "created_at"),
    )

    task_name: Mapped[str] = mapped_column(String(256), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    queue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(512), nullable=False)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    kwargs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
