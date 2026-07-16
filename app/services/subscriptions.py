from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ROLE_LEVELS, ApiPrincipal
from app.core.errors import ApiError
from app.models import NotificationSubscription, User
from app.services.audit import add_audit_log
from app.services.favorites import get_or_create_api_user
from app.services.subscription_matching import validate_quiet_hours, validate_timezone


def _as_string_list(values: list[Any] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def normalize_subscription_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    if "project_types" in payload:
        payload["project_types"] = _as_string_list(payload.get("project_types"))
    if "currencies" in payload:
        payload["currencies"] = [
            item.upper() for item in _as_string_list(payload.get("currencies"))
        ]
    if "source_ids" in payload:
        payload["source_ids"] = _as_string_list(payload.get("source_ids"))
        for source_id in payload["source_ids"]:
            try:
                UUID(source_id)
            except ValueError as exc:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message="source_ids must contain valid UUIDs.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"source_id": source_id},
                ) from exc
    if "positive_keywords" in payload:
        payload["positive_keywords"] = _as_string_list(payload.get("positive_keywords"))
    if "negative_keywords" in payload:
        payload["negative_keywords"] = _as_string_list(payload.get("negative_keywords"))

    if "timezone" in payload and payload["timezone"] is not None:
        try:
            payload["timezone"] = validate_timezone(str(payload["timezone"]))
        except ValueError as exc:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    start = payload.get("quiet_hours_start", None)
    end = payload.get("quiet_hours_end", None)
    if "quiet_hours_start" in payload or "quiet_hours_end" in payload:
        try:
            start, end = validate_quiet_hours(
                None if start in {"", None} else start,
                None if end in {"", None} else end,
            )
        except ValueError as exc:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc
        payload["quiet_hours_start"] = start
        payload["quiet_hours_end"] = end

    budget_min = payload.get("budget_min")
    budget_max = payload.get("budget_max")
    if budget_min is not None:
        payload["budget_min"] = Decimal(str(budget_min))
    if budget_max is not None:
        payload["budget_max"] = Decimal(str(budget_max))
    if (
        payload.get("budget_min") is not None
        and payload.get("budget_max") is not None
        and payload["budget_min"] > payload["budget_max"]
    ):
        raise ApiError(
            code="VALIDATION_ERROR",
            message="budget_min must be <= budget_max.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    min_relevance = payload.get("min_relevance_score")
    if min_relevance is not None and not (0 <= int(min_relevance) <= 100):
        raise ApiError(
            code="VALIDATION_ERROR",
            message="min_relevance_score must be between 0 and 100.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return payload


async def resolve_subscription_owner(
    session: AsyncSession,
    principal: ApiPrincipal,
    *,
    user_id: UUID | None = None,
    tg_chat_id: int | None = None,
) -> User:
    if tg_chat_id is not None:
        if ROLE_LEVELS[principal.role] < ROLE_LEVELS["operator"]:
            raise ApiError(
                code="FORBIDDEN",
                message="Only operator/admin can attach subscriptions by tg_chat_id.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        from app.bot.services import get_or_create_bot_user

        return await get_or_create_bot_user(session, int(tg_chat_id))

    if user_id is not None:
        if ROLE_LEVELS[principal.role] < ROLE_LEVELS["admin"]:
            raise ApiError(
                code="FORBIDDEN",
                message="Only admin can manage subscriptions for another user_id.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        owner_id = UUID(str(user_id))
        user = await session.get(User, owner_id)
        if user is None:
            raise ApiError(
                code="USER_NOT_FOUND",
                message="User was not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return user

    return await get_or_create_api_user(session, principal)


async def list_subscriptions(
    session: AsyncSession,
    principal: ApiPrincipal,
    *,
    user_id: UUID | None = None,
) -> list[NotificationSubscription]:
    if user_id is not None and ROLE_LEVELS[principal.role] >= ROLE_LEVELS["admin"]:
        owner_id = user_id
    else:
        owner = await get_or_create_api_user(session, principal)
        owner_id = owner.id
        if user_id is not None and user_id != owner_id:
            raise ApiError(
                code="FORBIDDEN",
                message="Cannot list another user's subscriptions.",
                status_code=status.HTTP_403_FORBIDDEN,
            )

    result = await session.scalars(
        select(NotificationSubscription)
        .where(NotificationSubscription.user_id == owner_id)
        .order_by(NotificationSubscription.created_at.desc())
    )
    return list(result)


async def list_all_subscriptions_for_admin(
    session: AsyncSession,
    principal: ApiPrincipal,
) -> list[NotificationSubscription]:
    if ROLE_LEVELS[principal.role] < ROLE_LEVELS["admin"]:
        raise ApiError(
            code="FORBIDDEN",
            message="Only admin can list all subscriptions.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    result = await session.scalars(
        select(NotificationSubscription).order_by(NotificationSubscription.created_at.desc())
    )
    return list(result)


async def get_subscription(
    session: AsyncSession,
    principal: ApiPrincipal,
    subscription_id: UUID,
) -> NotificationSubscription:
    subscription = await session.get(NotificationSubscription, subscription_id)
    if subscription is None:
        raise ApiError(
            code="SUBSCRIPTION_NOT_FOUND",
            message="Subscription was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    await ensure_subscription_access(session, principal, subscription)
    return subscription


async def ensure_subscription_access(
    session: AsyncSession,
    principal: ApiPrincipal,
    subscription: NotificationSubscription,
) -> None:
    if ROLE_LEVELS[principal.role] >= ROLE_LEVELS["admin"]:
        return
    owner = await get_or_create_api_user(session, principal)
    if subscription.user_id != owner.id:
        raise ApiError(
            code="FORBIDDEN",
            message="Cannot access another user's subscription.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


async def create_subscription(
    session: AsyncSession,
    principal: ApiPrincipal,
    data: dict[str, Any],
) -> NotificationSubscription:
    payload = normalize_subscription_payload(data)
    owner = await resolve_subscription_owner(
        session,
        principal,
        user_id=payload.pop("user_id", None),
        tg_chat_id=payload.pop("tg_chat_id", None),
    )
    subscription = NotificationSubscription(user_id=owner.id, **payload)
    session.add(subscription)
    await session.flush()
    await add_audit_log(
        session,
        action="subscription.create",
        entity="notification_subscription",
        entity_id=subscription.id,
        payload={
            "user_id": str(owner.id),
            "name": subscription.name,
            "enabled": subscription.enabled,
            "actor": principal.key_name,
        },
    )
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def update_subscription(
    session: AsyncSession,
    principal: ApiPrincipal,
    subscription_id: UUID,
    data: dict[str, Any],
) -> NotificationSubscription:
    subscription = await get_subscription(session, principal, subscription_id)
    payload = normalize_subscription_payload(data)
    payload.pop("user_id", None)
    payload.pop("tg_chat_id", None)
    for key, value in payload.items():
        setattr(subscription, key, value)
    await add_audit_log(
        session,
        action="subscription.update",
        entity="notification_subscription",
        entity_id=subscription.id,
        payload={"fields": sorted(payload.keys()), "actor": principal.key_name},
    )
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def set_subscription_enabled(
    session: AsyncSession,
    principal: ApiPrincipal,
    subscription_id: UUID,
    enabled: bool,
) -> NotificationSubscription:
    return await update_subscription(
        session,
        principal,
        subscription_id,
        {"enabled": enabled},
    )


async def delete_subscription(
    session: AsyncSession,
    principal: ApiPrincipal,
    subscription_id: UUID,
) -> None:
    subscription = await get_subscription(session, principal, subscription_id)
    await add_audit_log(
        session,
        action="subscription.delete",
        entity="notification_subscription",
        entity_id=subscription.id,
        payload={"name": subscription.name, "actor": principal.key_name},
    )
    await session.delete(subscription)
    await session.commit()
