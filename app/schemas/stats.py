from __future__ import annotations

from pydantic import BaseModel


class StatsSummaryResponse(BaseModel):
    orders_total: int
    sources_total: int
    classes: dict[str, int]
    order_statuses: dict[str, int]
