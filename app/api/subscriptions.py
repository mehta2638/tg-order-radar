from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ApiPrincipal, require_roles
from app.db.session import get_session
from app.schemas.subscriptions import (
    SubscriptionCreateRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
    SubscriptionUpdateRequest,
)
from app.services import subscriptions as subscription_service

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewerDep = Annotated[ApiPrincipal, Depends(require_roles("viewer"))]
OperatorDep = Annotated[ApiPrincipal, Depends(require_roles("operator"))]
UserIdQuery = Annotated[UUID | None, Query()]
AllUsersQuery = Annotated[bool, Query()]


@router.get("", response_model=SubscriptionListResponse, summary="List subscriptions")
async def list_subscriptions_endpoint(
    session: SessionDep,
    principal: ViewerDep,
    user_id: UserIdQuery = None,
    all_users: AllUsersQuery = False,
) -> SubscriptionListResponse:
    if all_users:
        items = await subscription_service.list_all_subscriptions_for_admin(session, principal)
    else:
        items = await subscription_service.list_subscriptions(session, principal, user_id=user_id)
    return SubscriptionListResponse(
        items=[SubscriptionResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create subscription",
)
async def create_subscription_endpoint(
    payload: SubscriptionCreateRequest,
    session: SessionDep,
    principal: OperatorDep,
) -> SubscriptionResponse:
    subscription = await subscription_service.create_subscription(
        session,
        principal,
        payload.model_dump(mode="json"),
    )
    return SubscriptionResponse.model_validate(subscription)


@router.get(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Get subscription",
)
async def get_subscription_endpoint(
    subscription_id: UUID,
    session: SessionDep,
    principal: ViewerDep,
) -> SubscriptionResponse:
    subscription = await subscription_service.get_subscription(session, principal, subscription_id)
    return SubscriptionResponse.model_validate(subscription)


@router.patch(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Update subscription",
)
async def update_subscription_endpoint(
    subscription_id: UUID,
    payload: SubscriptionUpdateRequest,
    session: SessionDep,
    principal: OperatorDep,
) -> SubscriptionResponse:
    subscription = await subscription_service.update_subscription(
        session,
        principal,
        subscription_id,
        payload.model_dump(exclude_unset=True, mode="json"),
    )
    return SubscriptionResponse.model_validate(subscription)


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete subscription",
)
async def delete_subscription_endpoint(
    subscription_id: UUID,
    session: SessionDep,
    principal: OperatorDep,
) -> Response:
    await subscription_service.delete_subscription(session, principal, subscription_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{subscription_id}/enable",
    response_model=SubscriptionResponse,
    summary="Enable subscription",
)
async def enable_subscription_endpoint(
    subscription_id: UUID,
    session: SessionDep,
    principal: OperatorDep,
) -> SubscriptionResponse:
    subscription = await subscription_service.set_subscription_enabled(
        session, principal, subscription_id, True
    )
    return SubscriptionResponse.model_validate(subscription)


@router.post(
    "/{subscription_id}/disable",
    response_model=SubscriptionResponse,
    summary="Disable subscription",
)
async def disable_subscription_endpoint(
    subscription_id: UUID,
    session: SessionDep,
    principal: OperatorDep,
) -> SubscriptionResponse:
    subscription = await subscription_service.set_subscription_enabled(
        session, principal, subscription_id, False
    )
    return SubscriptionResponse.model_validate(subscription)
