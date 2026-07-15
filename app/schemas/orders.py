from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    source_id: UUID
    project_type: str | None
    title: str | None
    summary: str | None
    budget_from: Decimal | None
    budget_to: Decimal | None
    budget_currency: str | None
    budget_negotiable: bool
    deadline: date | None
    deadline_text: str | None
    contacts: dict[str, list[str]] | None
    published_at: datetime
    relevance_score: int
    status: str
    is_fresh: bool
    version: int
    message_url: str | None = None


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    size: int


class OrderStatusUpdateRequest(BaseModel):
    status: str = Field(pattern="^(viewed|contacted|irrelevant|archived)$")
    version: int = Field(ge=1)


class OrderExportItem(BaseModel):
    id: UUID
    title: str | None
    summary: str | None
    project_type: str | None
    budget_from: Decimal | None
    budget_to: Decimal | None
    budget_currency: str | None
    deadline: date | None
    contact: str | None
    relevance_score: int
    status: str
    published_at: datetime
    message_url: str | None
