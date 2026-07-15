from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    created_at: datetime


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    total: int
