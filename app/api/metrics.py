from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.monitoring.metrics import render_metrics

router = APIRouter(tags=["metrics"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/metrics", summary="Prometheus metrics")
async def prometheus_metrics(session: SessionDep) -> Response:
    settings = get_settings()
    payload, content_type = await render_metrics(session, settings)
    return Response(content=payload, media_type=content_type)
