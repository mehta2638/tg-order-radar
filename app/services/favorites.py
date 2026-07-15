from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ApiPrincipal
from app.core.errors import ApiError
from app.models import Favorite, Order, User
from app.services.audit import add_audit_log


async def get_or_create_api_user(session: AsyncSession, principal: ApiPrincipal) -> User:
    email = f"api-{principal.key_name}@local"
    result = await session.scalars(select(User).where(User.email == email))
    user = result.one_or_none()
    if user is not None:
        return user

    user = User(email=email, password_hash="api-key", role=principal.role, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def add_favorite(
    session: AsyncSession,
    principal: ApiPrincipal,
    order_id: UUID,
) -> Favorite:
    await ensure_order_exists(session, order_id)
    user = await get_or_create_api_user(session, principal)
    favorite = Favorite(user_id=user.id, order_id=order_id)
    session.add(favorite)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        user = await get_or_create_api_user(session, principal)
        result = await session.scalars(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.order_id == order_id)
        )
        favorite = result.one()
        return favorite

    await add_audit_log(
        session,
        action="favorite.add",
        entity="order",
        entity_id=order_id,
        payload={"user_id": str(user.id)},
    )
    await session.commit()
    await session.refresh(favorite)
    return favorite


async def remove_favorite(
    session: AsyncSession,
    principal: ApiPrincipal,
    order_id: UUID,
) -> None:
    user = await get_or_create_api_user(session, principal)
    result = await session.scalars(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.order_id == order_id)
    )
    favorite = result.one_or_none()
    if favorite is not None:
        await session.delete(favorite)
        await add_audit_log(
            session,
            action="favorite.remove",
            entity="order",
            entity_id=order_id,
            payload={"user_id": str(user.id)},
        )
    await session.commit()


async def list_favorites(
    session: AsyncSession,
    principal: ApiPrincipal,
) -> tuple[list[Favorite], int]:
    user = await get_or_create_api_user(session, principal)
    result = await session.scalars(
        select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())
    )
    favorites = list(result)
    return favorites, len(favorites)


async def ensure_order_exists(session: AsyncSession, order_id: UUID) -> None:
    if await session.get(Order, order_id) is None:
        raise ApiError(
            code="ORDER_NOT_FOUND",
            message="Order was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
