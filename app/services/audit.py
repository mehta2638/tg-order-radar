from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.models import AuditLog


async def add_audit_log(
    session: AsyncSession,
    action: str,
    entity: str,
    entity_id: UUID | None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
            correlation_id=get_correlation_id(),
        )
    )
