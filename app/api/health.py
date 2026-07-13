from typing import Literal

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.health import check_database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    settings = get_settings()
    try:
        await check_database()
        redis_client = redis.from_url(settings.redis_url)
        try:
            await redis_client.ping()
        finally:
            await redis_client.aclose()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "reason": "dependency_unavailable"},
        ) from exc

    return HealthResponse(status="ok")
