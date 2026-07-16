"""Partition messages by published_at and support multi-account scaling.

Revision ID: 0010_scaling_partitions
Revises: 0009_notification_subscriptions
Create Date: 2026-07-16

Notes:
- Foreign keys to messages.id are dropped: PostgreSQL RANGE partitions require the
  partition key in primary/unique keys, which breaks single-column FKs.
- Application upsert still enforces (source_id, tg_message_id) uniqueness.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_scaling_partitions"
down_revision: str | None = "0009_notification_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy may name FKs as fk_<table>_<col>_<referred>; drop by catalog lookup.
    op.execute(
        """
        do $$
        declare r record;
        begin
            for r in
                select c.conname, c.conrelid::regclass::text as tbl
                from pg_constraint c
                where c.contype = 'f'
                  and c.confrelid = 'messages'::regclass
            loop
                execute format('alter table %s drop constraint %I', r.tbl, r.conname);
            end loop;
        end $$
        """
    )

    op.execute("alter table messages rename to messages_legacy")
    op.execute("alter index if exists ix_messages_source_id rename to ix_messages_legacy_source_id")
    op.execute(
        "alter index if exists ix_messages_published_at rename to ix_messages_legacy_published_at"
    )
    op.execute(
        "alter index if exists ix_messages_content_hash rename to ix_messages_legacy_content_hash"
    )
    op.execute(
        "alter index if exists ix_messages_deleted_at rename to ix_messages_legacy_deleted_at"
    )
    op.execute(
        """
        alter index if exists uq_messages_source_tg_message_id
            rename to uq_messages_legacy_source_tg_message_id
        """
    )

    op.execute(
        """
        create table messages (
            id uuid not null default gen_random_uuid(),
            source_id uuid not null references telegram_sources(id) on delete cascade,
            tg_message_id bigint not null,
            published_at timestamptz not null,
            collected_at timestamptz not null default now(),
            edited_at timestamptz,
            deleted_at timestamptz,
            forward_original_date timestamptz,
            text text,
            normalized_text text,
            detected_language varchar(8),
            passed_prefilter boolean,
            content_hash varchar(64),
            message_url text,
            views_count integer,
            replies_count integer,
            raw_payload jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            primary key (id, published_at),
            unique (source_id, tg_message_id, published_at)
        ) partition by range (published_at)
        """
    )

    op.execute(
        """
        do $$
        declare
            start_month date;
            end_month date;
            cursor_month date;
            part_name text;
            part_start timestamptz;
            part_end timestamptz;
        begin
            select date_trunc('month', coalesce(min(published_at), now()))::date
              into start_month
              from messages_legacy;
            start_month := (start_month - interval '1 month')::date;
            end_month := (date_trunc('month', now()) + interval '2 months')::date;
            cursor_month := start_month;
            while cursor_month <= end_month loop
                part_name := format(
                    'messages_%s',
                    to_char(cursor_month, 'YYYY_MM')
                );
                part_start := cursor_month::timestamptz;
                part_end := (cursor_month + interval '1 month')::timestamptz;
                execute format(
                    'create table if not exists %I partition of messages
                     for values from (%L) to (%L)',
                    part_name,
                    part_start,
                    part_end
                );
                cursor_month := (cursor_month + interval '1 month')::date;
            end loop;
            execute 'create table if not exists messages_default partition of messages default';
        end $$
        """
    )

    op.execute(
        """
        insert into messages (
            id, source_id, tg_message_id, published_at, collected_at, edited_at, deleted_at,
            forward_original_date, text, normalized_text, detected_language, passed_prefilter,
            content_hash, message_url, views_count, replies_count, raw_payload,
            created_at, updated_at
        )
        select
            id, source_id, tg_message_id, published_at, collected_at, edited_at, deleted_at,
            forward_original_date, text, normalized_text, detected_language, passed_prefilter,
            content_hash, message_url, views_count, replies_count, raw_payload,
            created_at, updated_at
        from messages_legacy
        """
    )

    op.execute("drop table messages_legacy")

    op.execute("create index ix_messages_source_id on messages (source_id)")
    op.execute("create index ix_messages_published_at on messages (published_at)")
    op.execute("create index ix_messages_content_hash on messages (content_hash)")
    op.execute("create index ix_messages_deleted_at on messages (deleted_at)")
    op.execute(
        "create index ix_messages_source_tg_message_id on messages (source_id, tg_message_id)"
    )


def downgrade() -> None:
    op.execute(
        """
        create table messages_restored (
            id uuid primary key default gen_random_uuid(),
            source_id uuid not null references telegram_sources(id) on delete cascade,
            tg_message_id bigint not null,
            published_at timestamptz not null,
            collected_at timestamptz not null default now(),
            edited_at timestamptz,
            deleted_at timestamptz,
            forward_original_date timestamptz,
            text text,
            normalized_text text,
            detected_language varchar(8),
            passed_prefilter boolean,
            content_hash varchar(64),
            message_url text,
            views_count integer,
            replies_count integer,
            raw_payload jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (source_id, tg_message_id)
        )
        """
    )
    op.execute(
        """
        insert into messages_restored (
            id, source_id, tg_message_id, published_at, collected_at, edited_at, deleted_at,
            forward_original_date, text, normalized_text, detected_language, passed_prefilter,
            content_hash, message_url, views_count, replies_count, raw_payload,
            created_at, updated_at
        )
        select
            id, source_id, tg_message_id, published_at, collected_at, edited_at, deleted_at,
            forward_original_date, text, normalized_text, detected_language, passed_prefilter,
            content_hash, message_url, views_count, replies_count, raw_payload,
            created_at, updated_at
        from messages
        """
    )
    op.execute("drop table messages cascade")
    op.execute("alter table messages_restored rename to messages")
    op.execute("create index ix_messages_source_id on messages (source_id)")
    op.execute("create index ix_messages_published_at on messages (published_at)")
    op.execute("create index ix_messages_content_hash on messages (content_hash)")
    op.execute("create index ix_messages_deleted_at on messages (deleted_at)")
    op.execute(
        """
        alter table message_entities
            add constraint message_entities_message_id_fkey
            foreign key (message_id) references messages(id) on delete cascade
        """
    )
    op.execute(
        """
        alter table classifications
            add constraint classifications_message_id_fkey
            foreign key (message_id) references messages(id) on delete cascade
        """
    )
    op.execute(
        """
        alter table orders
            add constraint orders_message_id_fkey
            foreign key (message_id) references messages(id) on delete cascade
        """
    )
