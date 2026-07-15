from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_roles
from app.db.session import get_session
from app.schemas.orders import OrderListResponse, OrderResponse, OrderStatusUpdateRequest
from app.services.orders import (
    OrderFilters,
    export_orders,
    get_order_row,
    list_orders,
    order_to_response_payload,
    update_order_status,
)

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewerDep = Depends(require_roles("viewer"))
OperatorDep = Depends(require_roles("operator"))
DateQuery = Annotated[date | None, Query()]
BudgetQuery = Annotated[int | None, Query(ge=0)]
ProjectTypeQuery = Annotated[list[str] | None, Query()]
RelevanceQuery = Annotated[int | None, Query(ge=0, le=100)]
SourceIdQuery = Annotated[UUID | None, Query()]
StatusQuery = Annotated[list[str] | None, Query()]
SearchQuery = Annotated[str | None, Query(min_length=1, max_length=128)]
PageQuery = Annotated[int, Query(ge=1)]
SizeQuery = Annotated[int, Query(ge=1, le=100)]
ExportFormatQuery = Annotated[Literal["json", "csv"], Query()]
ExportLimitQuery = Annotated[int, Query(ge=1, le=1000)]


@router.get(
    "",
    response_model=OrderListResponse,
    summary="List orders with MVP filters",
)
async def list_orders_endpoint(
    response: Response,
    session: SessionDep,
    date_from: DateQuery = None,
    date_to: DateQuery = None,
    budget_min: BudgetQuery = None,
    budget_max: BudgetQuery = None,
    project_type: ProjectTypeQuery = None,
    relevance_min: RelevanceQuery = None,
    source_id: SourceIdQuery = None,
    status: StatusQuery = None,
    q: SearchQuery = None,
    page: PageQuery = 1,
    size: SizeQuery = 20,
    principal: object = ViewerDep,
) -> OrderListResponse:
    rows, total = await list_orders(
        session,
        OrderFilters(
            date_from=date_from,
            date_to=date_to,
            budget_min=budget_min,
            budget_max=budget_max,
            project_type=project_type,
            relevance_min=relevance_min,
            source_id=source_id,
            status=status,
            q=q,
        ),
        page=page,
        size=size,
    )
    response.headers["X-Total-Count"] = str(total)
    return OrderListResponse(
        items=[OrderResponse.model_validate(order_to_response_payload(row)) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/export",
    summary="Export a limited orders selection as JSON or CSV",
    response_model=None,
)
async def export_orders_endpoint(
    session: SessionDep,
    format: ExportFormatQuery = "json",  # noqa: A002
    limit: ExportLimitQuery = 100,
    date_from: DateQuery = None,
    date_to: DateQuery = None,
    project_type: ProjectTypeQuery = None,
    relevance_min: RelevanceQuery = None,
    status: StatusQuery = None,
    q: SearchQuery = None,
    principal: object = ViewerDep,
) -> JSONResponse | StreamingResponse:
    rows = await export_orders(
        session,
        OrderFilters(
            date_from=date_from,
            date_to=date_to,
            project_type=project_type,
            relevance_min=relevance_min,
            status=status,
            q=q,
        ),
        limit=limit,
    )
    payloads = [order_to_response_payload(row) for row in rows]
    if format == "json":
        return JSONResponse(content={"items": [jsonable_order(item) for item in payloads]})
    return csv_response(payloads)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get one order card",
)
async def get_order_endpoint(
    order_id: UUID,
    session: SessionDep,
    principal: object = ViewerDep,
) -> OrderResponse:
    row = await get_order_row(session, order_id)
    return OrderResponse.model_validate(order_to_response_payload(row))


@router.patch(
    "/{order_id}/status",
    response_model=OrderResponse,
    summary="Change order status with optimistic locking",
)
async def update_order_status_endpoint(
    order_id: UUID,
    payload: OrderStatusUpdateRequest,
    session: SessionDep,
    principal: object = OperatorDep,
) -> OrderResponse:
    order = await update_order_status(session, order_id, payload.status, payload.version)
    row = await get_order_row(session, order.id)
    return OrderResponse.model_validate(order_to_response_payload(row))


def csv_response(payloads: list[dict[str, object]]) -> StreamingResponse:
    stream = io.StringIO()
    fieldnames = [
        "id",
        "title",
        "project_type",
        "budget_from",
        "budget_to",
        "budget_currency",
        "deadline",
        "relevance_score",
        "status",
        "published_at",
        "message_url",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for payload in payloads:
        writer.writerow(jsonable_order(payload))
    stream.seek(0)
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


def jsonable_order(payload: dict[str, object]) -> dict[str, object]:
    return {key: str(value) if value is not None else None for key, value in payload.items()}
