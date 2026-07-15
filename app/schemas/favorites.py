from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.orders import OrderResponse


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    created_at: datetime
    order: OrderResponse | None = None


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    total: int
