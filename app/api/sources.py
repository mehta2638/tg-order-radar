from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.sources import (
    SourceCreateRequest,
    SourceListResponse,
    SourceResponse,
    SourceUpdateRequest,
)
from app.services.source_validation import validate_source
from app.services.sources import (
    create_source,
    disable_source,
    get_source,
    list_sources,
    set_source_enabled,
)

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source_endpoint(
    payload: SourceCreateRequest,
    session: SessionDep,
) -> SourceResponse:
    source = await create_source(session, payload.link)
    return SourceResponse.model_validate(source)


@router.get("", response_model=SourceListResponse)
async def list_sources_endpoint(
    response: Response,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=1, max_length=64),
) -> SourceListResponse:
    sources, total = await list_sources(session, page=page, size=size, q=q)
    response.headers["X-Total-Count"] = str(total)
    return SourceListResponse(
        items=[SourceResponse.model_validate(source) for source in sources],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source_endpoint(
    source_id: UUID,
    session: SessionDep,
) -> SourceResponse:
    source = await get_source(session, source_id)
    return SourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source_endpoint(
    source_id: UUID,
    payload: SourceUpdateRequest,
    session: SessionDep,
) -> SourceResponse:
    source = await set_source_enabled(session, source_id, payload.enabled)
    return SourceResponse.model_validate(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_endpoint(
    source_id: UUID,
    session: SessionDep,
) -> Response:
    await disable_source(session, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/validate", response_model=SourceResponse)
async def validate_source_endpoint(
    source_id: UUID,
    session: SessionDep,
) -> SourceResponse:
    source = await validate_source(session, source_id)
    return SourceResponse.model_validate(source)
