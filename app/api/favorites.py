from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ApiPrincipal, require_roles
from app.db.session import get_session
from app.schemas.favorites import FavoriteListResponse, FavoriteResponse
from app.services.favorites import add_favorite, list_favorites, remove_favorite

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewerDep = Depends(require_roles("viewer"))


@router.get("", response_model=FavoriteListResponse, summary="List current API user's favorites")
async def list_favorites_endpoint(
    session: SessionDep,
    principal: ApiPrincipal = ViewerDep,
) -> FavoriteListResponse:
    favorites, total = await list_favorites(session, principal)
    return FavoriteListResponse(
        items=[FavoriteResponse.model_validate(favorite) for favorite in favorites],
        total=total,
    )


@router.post(
    "/{order_id}",
    response_model=FavoriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add order to favorites idempotently",
)
async def add_favorite_endpoint(
    order_id: UUID,
    session: SessionDep,
    principal: ApiPrincipal = ViewerDep,
) -> FavoriteResponse:
    favorite = await add_favorite(session, principal, order_id)
    return FavoriteResponse.model_validate(favorite)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove favorite")
async def remove_favorite_endpoint(
    order_id: UUID,
    session: SessionDep,
    principal: ApiPrincipal = ViewerDep,
) -> Response:
    await remove_favorite(session, principal, order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
