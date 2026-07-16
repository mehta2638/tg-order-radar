"""Add semantic dedup pgvector columns.

Revision ID: 0008_semantic_dedup
Revises: 0007_ml_classification
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_semantic_dedup"
down_revision: str | None = "0007_ml_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        do $$
        begin
            create extension if not exists vector;
        exception
            when others then
                raise notice 'pgvector extension is not installed; semantic dedup stays disabled';
        end $$;
        """
    )
    op.execute(
        """
        do $$
        begin
            if exists (select 1 from pg_type where typname = 'vector') then
                alter table orders
                    add column if not exists semantic_embedding vector(384),
                    add column if not exists semantic_embedding_model varchar(128),
                    add column if not exists semantic_embedding_updated_at timestamptz;
            end if;
        end $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table orders
            drop column if exists semantic_embedding_updated_at,
            drop column if exists semantic_embedding_model,
            drop column if exists semantic_embedding;
        """
    )
