from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class ExtractedEntity:
    type: str
    value_text: str
    value_norm: dict[str, Any]
    confidence: float = 0.9


PROJECT_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ecommerce", ("интернет-магазин", "интернет магазин", "маркетплейс", "woocommerce")),
    ("corporate_site", ("корпоративный сайт", "сайт компании")),
    ("landing_page", ("лендинг", "одностраничник", "landing")),
    ("business_card", ("визитка", "сайт-визитка")),
    ("integration", ("crm", "api", "интеграция", "оплату", "платеж")),
    ("redesign", ("редизайн", "перерисовать")),
    ("revision", ("доработ", "правки", "починить", "исправить", "доделать")),
    ("frontend", ("frontend", "фронтенд", "верстка", "вёрстка")),
    ("backend", ("backend", "бэкенд", "бекенд")),
    ("fullstack", ("fullstack", "фулстек", "под ключ")),
)

CURRENCY_MARKERS = {
    "₽": "RUB",
    "руб": "RUB",
    "р": "RUB",
    "rub": "RUB",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "грн": "UAH",
    "uah": "UAH",
    "тенге": "KZT",
    "kzt": "KZT",
    "бел": "BYN",
}
NUMBER_RE = r"\d[\d\s.]*"
MONEY_RE = re.compile(
    rf"(?P<amount>{NUMBER_RE})\s*(?P<suffix>тыс|k|к)?\s*"
    r"(?P<currency>руб\.?|р\.?|₽|rub|\$|usd|€|eur|грн|uah|тенге|kzt|бел)?",
    re.IGNORECASE,
)
RANGE_RE = re.compile(
    rf"(?:от\s+)?(?P<from>{NUMBER_RE})\s*(?P<from_suffix>тыс|k|к)?\s*"
    rf"(?:-|–|—|\s+до\s+)\s*(?P<to>{NUMBER_RE})\s*(?P<to_suffix>тыс|k|к)?\s*"
    r"(?P<currency>руб\.?|р\.?|₽|rub|\$|usd|€|eur|грн|uah|тенге|kzt|бел)?",
    re.IGNORECASE,
)
UP_TO_RE = re.compile(
    rf"до\s+(?P<amount>{NUMBER_RE})\s*(?P<suffix>тыс|k|к)?\s*"
    r"(?P<currency>руб\.?|р\.?|₽|rub|\$|usd|€|eur|грн|uah|тенге|kzt|бел)?",
    re.IGNORECASE,
)
NEGOTIABLE_RE = re.compile(r"\b(договорн\w*|по договор[её]нности|обсудим бюджет)\b")

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.+-])", re.IGNORECASE)
USERNAME_RE = re.compile(r"(?<![\w])@[a-zA-Z][\w\d_]{4,31}(?![\w])")
TME_RE = re.compile(
    r"https?://t\.me/([a-zA-Z][\w\d_]{4,31})|(?<![\w])t\.me/([a-zA-Z][\w\d_]{4,31})"
)
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d\s()\-]{7,}\d(?!\d)")
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

RELATIVE_DEADLINE_RE = re.compile(r"\bза\s+(\d{1,2})\s+(дн(?:я|ей|ь)|недел[юьиь])\b")
DATE_DEADLINE_RE = re.compile(r"\b(?:до|к)\s+(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
MONTH_DEADLINE_RE = re.compile(
    r"\bк\s+("
    r"январ[юя]|феврал[юя]|март[ау]?|апрел[юя]|ма[юя]|июн[юя]|июл[юя]|"
    r"август[ау]?|сентябр[юя]|октябр[юя]|ноябр[юя]|декабр[юя]"
    r")\b"
)
URGENT_RE = re.compile(r"\b(срочно|дедлайн|горит)\b")

MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def extract_entities(
    normalized_text: str,
    original_text: str | None = None,
) -> list[ExtractedEntity]:
    text = normalized_text
    source_text = original_text or normalized_text
    return [
        *extract_project_types(text),
        *extract_budget(text),
        *extract_deadlines(text),
        *extract_contacts(source_text),
    ]


def extract_project_types(normalized_text: str) -> list[ExtractedEntity]:
    for project_type, markers in PROJECT_TYPE_RULES:
        for marker in markers:
            if marker in normalized_text:
                return [
                    ExtractedEntity(
                        type="project_type",
                        value_text=marker,
                        value_norm={"project_type": project_type},
                        confidence=0.95,
                    )
                ]
    return []


def extract_budget(normalized_text: str) -> list[ExtractedEntity]:
    negotiable_match = NEGOTIABLE_RE.search(normalized_text)
    if negotiable_match:
        return [
            ExtractedEntity(
                type="budget",
                value_text=negotiable_match.group(0),
                value_norm={"negotiable": True},
                confidence=0.9,
            )
        ]

    range_match = RANGE_RE.search(normalized_text)
    if range_match:
        currency = normalize_currency(range_match.group("currency"))
        return [
            ExtractedEntity(
                type="budget",
                value_text=range_match.group(0),
                value_norm={
                    "amount_from": parse_amount(
                        range_match.group("from"),
                        range_match.group("from_suffix"),
                    ),
                    "amount_to": parse_amount(
                        range_match.group("to"),
                        range_match.group("to_suffix"),
                    ),
                    "currency": currency,
                    "negotiable": False,
                },
                confidence=0.95,
            )
        ]

    up_to_match = UP_TO_RE.search(normalized_text)
    if up_to_match:
        return [
            ExtractedEntity(
                type="budget",
                value_text=up_to_match.group(0),
                value_norm={
                    "amount_from": None,
                    "amount_to": parse_amount(
                        up_to_match.group("amount"),
                        up_to_match.group("suffix"),
                    ),
                    "currency": normalize_currency(up_to_match.group("currency")),
                    "negotiable": False,
                },
                confidence=0.9,
            )
        ]

    for match in MONEY_RE.finditer(normalized_text):
        currency = normalize_currency(match.group("currency"))
        suffix = match.group("suffix")
        if currency is None and suffix is None:
            continue
        amount = parse_amount(match.group("amount"), suffix)
        return [
            ExtractedEntity(
                type="budget",
                value_text=match.group(0),
                value_norm={
                    "amount_from": amount,
                    "amount_to": amount,
                    "currency": currency,
                    "negotiable": False,
                },
                confidence=0.9,
            )
        ]
    return []


def extract_deadlines(normalized_text: str) -> list[ExtractedEntity]:
    now = datetime.now(UTC).date()
    relative_match = RELATIVE_DEADLINE_RE.search(normalized_text)
    if relative_match:
        amount = int(relative_match.group(1))
        multiplier = 7 if relative_match.group(2).startswith("нед") else 1
        deadline = now + timedelta(days=amount * multiplier)
        return [deadline_entity(relative_match.group(0), deadline, "relative")]

    date_match = DATE_DEADLINE_RE.search(normalized_text)
    if date_match:
        deadline = parse_date_deadline(date_match, now)
        return [deadline_entity(date_match.group(0), deadline, "date")]

    month_match = MONTH_DEADLINE_RE.search(normalized_text)
    if month_match:
        month = parse_month(month_match.group(1))
        year = now.year if month >= now.month else now.year + 1
        return [deadline_entity(month_match.group(0), date(year, month, 1), "month")]

    urgent_match = URGENT_RE.search(normalized_text)
    if urgent_match:
        return [
            ExtractedEntity(
                type="deadline",
                value_text=urgent_match.group(0),
                value_norm={"deadline_text": urgent_match.group(0), "urgent": True},
                confidence=0.8,
            )
        ]
    return []


def extract_contacts(text: str) -> list[ExtractedEntity]:
    contacts: list[ExtractedEntity] = []
    seen: set[tuple[str, str]] = set()

    for match in USERNAME_RE.finditer(text):
        add_contact(contacts, seen, "telegram_username", match.group(0), match.group(0).lower())
    for match in TME_RE.finditer(text):
        username = match.group(1) or match.group(2)
        add_contact(contacts, seen, "telegram_username", match.group(0), f"@{username.lower()}")
    for match in EMAIL_RE.finditer(text):
        add_contact(contacts, seen, "email", match.group(0), match.group(0).lower())
    for match in PHONE_RE.finditer(text):
        normalized_phone = re.sub(r"[^\d+]", "", match.group(0))
        add_contact(contacts, seen, "phone", match.group(0), normalized_phone)
    for match in URL_RE.finditer(text):
        if "t.me/" in match.group(0).lower():
            continue
        add_contact(contacts, seen, "url", match.group(0), match.group(0))

    if not contacts and re.search(r"\b(в лс|в личк|пишите|комментарии)\b", text, re.IGNORECASE):
        contacts.append(
            ExtractedEntity(
                type="contact",
                value_text="implicit_contact",
                value_norm={"kind": "implicit", "value": "direct_message"},
                confidence=0.5,
            )
        )
    return contacts


def add_contact(
    contacts: list[ExtractedEntity],
    seen: set[tuple[str, str]],
    kind: str,
    value_text: str,
    normalized_value: str,
) -> None:
    key = (kind, normalized_value)
    if key in seen:
        return
    seen.add(key)
    contacts.append(
        ExtractedEntity(
            type="contact",
            value_text=value_text,
            value_norm={"kind": kind, "value": normalized_value},
            confidence=0.95,
        )
    )


def parse_amount(raw_amount: str, suffix: str | None) -> int:
    amount = int(re.sub(r"[^\d]", "", raw_amount))
    if suffix is not None and suffix.casefold() in {"тыс", "k", "к"}:
        amount *= 1000
    return amount


def normalize_currency(raw_currency: str | None) -> str | None:
    if not raw_currency:
        return None
    cleaned = raw_currency.casefold().replace(".", "")
    return CURRENCY_MARKERS.get(cleaned)


def deadline_entity(value_text: str, deadline: date, mode: str) -> ExtractedEntity:
    return ExtractedEntity(
        type="deadline",
        value_text=value_text,
        value_norm={"deadline": deadline.isoformat(), "mode": mode},
        confidence=0.9,
    )


def parse_date_deadline(match: re.Match[str], today: date) -> date:
    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    year = today.year if year_raw is None else int(year_raw)
    if year < 100:
        year += 2000
    candidate = date(year, month, day)
    if year_raw is None and candidate < today:
        candidate = date(today.year + 1, month, day)
    return candidate


def parse_month(raw_month: str) -> int:
    normalized = raw_month.casefold()
    for stem, month in MONTHS.items():
        if normalized.startswith(stem):
            return month
    raise ValueError(f"Unsupported month: {raw_month}")
