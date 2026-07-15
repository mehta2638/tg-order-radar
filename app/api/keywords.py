from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_roles
from app.db.session import get_session
from app.schemas.keywords import (
    KeywordCreateRequest,
    KeywordListResponse,
    KeywordResponse,
    KeywordUpdateRequest,
    NegativeKeywordCreateRequest,
    NegativeKeywordListResponse,
    NegativeKeywordResponse,
    NegativeKeywordUpdateRequest,
)
from app.services.keywords import (
    create_keyword,
    create_negative_keyword,
    delete_keyword,
    list_keywords,
    list_negative_keywords,
    update_keyword,
    update_negative_keyword,
)

router = APIRouter(prefix="/api/v1", tags=["dictionaries"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewerDep = Depends(require_roles("viewer"))
OperatorDep = Depends(require_roles("operator"))


@router.get("/keywords", response_model=KeywordListResponse, summary="List positive keywords")
async def list_keywords_endpoint(
    session: SessionDep,
    principal: object = ViewerDep,
) -> KeywordListResponse:
    items = await list_keywords(session)
    return KeywordListResponse(
        items=[KeywordResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/keywords",
    response_model=KeywordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create positive keyword",
)
async def create_keyword_endpoint(
    payload: KeywordCreateRequest,
    session: SessionDep,
    principal: object = OperatorDep,
) -> KeywordResponse:
    keyword = await create_keyword(session, payload.model_dump())
    return KeywordResponse.model_validate(keyword)


@router.patch(
    "/keywords/{keyword_id}",
    response_model=KeywordResponse,
    summary="Update positive keyword",
)
async def update_keyword_endpoint(
    keyword_id: UUID,
    payload: KeywordUpdateRequest,
    session: SessionDep,
    principal: object = OperatorDep,
) -> KeywordResponse:
    keyword = await update_keyword(session, keyword_id, payload.model_dump(exclude_unset=True))
    return KeywordResponse.model_validate(keyword)


@router.delete(
    "/keywords/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete keyword",
)
async def delete_keyword_endpoint(
    keyword_id: UUID,
    session: SessionDep,
    principal: object = OperatorDep,
) -> Response:
    await delete_keyword(session, keyword_id, "positive")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/negative-keywords",
    response_model=NegativeKeywordListResponse,
    summary="List negative keywords",
)
async def list_negative_keywords_endpoint(
    session: SessionDep,
    principal: object = ViewerDep,
) -> NegativeKeywordListResponse:
    items = await list_negative_keywords(session)
    return NegativeKeywordListResponse(
        items=[NegativeKeywordResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/negative-keywords",
    response_model=NegativeKeywordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create negative keyword",
)
async def create_negative_keyword_endpoint(
    payload: NegativeKeywordCreateRequest,
    session: SessionDep,
    principal: object = OperatorDep,
) -> NegativeKeywordResponse:
    keyword = await create_negative_keyword(session, payload.model_dump())
    return NegativeKeywordResponse.model_validate(keyword)


@router.patch(
    "/negative-keywords/{keyword_id}",
    response_model=NegativeKeywordResponse,
    summary="Update negative keyword",
)
async def update_negative_keyword_endpoint(
    keyword_id: UUID,
    payload: NegativeKeywordUpdateRequest,
    session: SessionDep,
    principal: object = OperatorDep,
) -> NegativeKeywordResponse:
    keyword = await update_negative_keyword(
        session,
        keyword_id,
        payload.model_dump(exclude_unset=True),
    )
    return NegativeKeywordResponse.model_validate(keyword)


@router.delete(
    "/negative-keywords/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete negative keyword",
)
async def delete_negative_keyword_endpoint(
    keyword_id: UUID,
    session: SessionDep,
    principal: object = OperatorDep,
) -> Response:
    await delete_keyword(session, keyword_id, "negative")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
