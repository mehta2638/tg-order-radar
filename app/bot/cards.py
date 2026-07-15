from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass(frozen=True)
class OrderCard:
    order_id: str
    source: str
    published_at: datetime
    project_type: str | None
    summary: str | None
    budget_from: Decimal | None
    budget_to: Decimal | None
    budget_currency: str | None
    deadline_text: str | None
    contact: str | None
    relevance_score: int
    message_url: str | None


def render_order_card(card: OrderCard) -> str:
    return "\n".join(
        [
            "<b>Новый заказ</b>",
            f"<b>Источник:</b> {escape(card.source)}",
            f"<b>Дата:</b> {escape(card.published_at.strftime('%Y-%m-%d %H:%M'))}",
            f"<b>Тип:</b> {escape(card.project_type or 'не определен')}",
            f"<b>Описание:</b> {escape(card.summary or 'без описания')}",
            f"<b>Бюджет:</b> {escape(format_budget(card))}",
            f"<b>Срок:</b> {escape(card.deadline_text or 'не указан')}",
            f"<b>Контакт:</b> {escape(card.contact or 'не найден')}",
            f"<b>Relevance:</b> {card.relevance_score}/100",
        ]
    )


def build_order_keyboard(card: OrderCard) -> InlineKeyboardMarkup:
    open_button = InlineKeyboardButton(
        text="Открыть",
        url=card.message_url or "https://t.me/",
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [open_button],
            [
                InlineKeyboardButton(
                    text="В избранное",
                    callback_data=f"order:fav:{card.order_id}",
                ),
                InlineKeyboardButton(
                    text="Связался",
                    callback_data=f"order:status:contacted:{card.order_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Неактуально",
                    callback_data=f"order:status:irrelevant:{card.order_id}",
                )
            ],
        ]
    )


def format_budget(card: OrderCard) -> str:
    if card.budget_from is None and card.budget_to is None:
        return "не указан"
    currency = f" {card.budget_currency}" if card.budget_currency else ""
    if card.budget_from == card.budget_to or card.budget_to is None:
        return f"{format_money(card.budget_from)}{currency}"
    if card.budget_from is None:
        return f"до {format_money(card.budget_to)}{currency}"
    return f"{format_money(card.budget_from)}-{format_money(card.budget_to)}{currency}"


def format_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.quantize(Decimal("1")) if value == value.to_integral() else value
    return f"{normalized:,}".replace(",", " ")


def first_contact(contacts: dict[str, object] | None) -> str | None:
    if not contacts:
        return None
    for key in ("telegram_username", "telegram_url", "phone", "email"):
        value = contacts.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
    return None
