from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_roles
from app.db.session import get_session
from app.models import Classification, Order, TelegramSource
from app.schemas.stats import StatsSummaryResponse

router = APIRouter(prefix="/api/v1/stats", tags=["statistics"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewerDep = Depends(require_roles("viewer"))


@router.get("/summary", response_model=StatsSummaryResponse, summary="Get MVP statistics summary")
async def stats_summary_endpoint(
    session: SessionDep,
    principal: object = ViewerDep,
) -> StatsSummaryResponse:
    orders_total = int(await session.scalar(select(func.count()).select_from(Order)) or 0)
    sources_total = int(await session.scalar(select(func.count()).select_from(TelegramSource)) or 0)
    class_rows = (
        await session.execute(
            select(Classification.label, func.count()).group_by(Classification.label)
        )
    ).all()
    status_rows = (
        await session.execute(select(Order.status, func.count()).group_by(Order.status))
    ).all()
    return StatsSummaryResponse(
        orders_total=orders_total,
        sources_total=sources_total,
        classes={str(label): int(count) for label, count in class_rows},
        order_statuses={str(order_status): int(count) for order_status, count in status_rows},
    )
