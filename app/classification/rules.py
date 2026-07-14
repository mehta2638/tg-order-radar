from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.config import Settings, get_settings

ClassificationLabel = Literal[
    "order",
    "vacancy",
    "service_ad",
    "resume",
    "partnership",
    "spam",
    "discussion",
    "irrelevant",
]

NEED_RE = re.compile(r"\b(нужен|нужна|нужно|ищу|требуется|надо|нужны|кто может)\b")
TASK_RE = re.compile(
    r"\b(сделать|разработать|создать|доработать|починить|исправить|"
    r"интегрировать|сверстать|настроить|редизайн)\b"
)
VACANCY_RE = re.compile(
    r"\b(в штат|офис|зарплат|з/п|full[\s-]?time|полная занятость|резюме присылать|"
    r"ищем в команду|на постоянку)\b"
)
SERVICE_AD_RE = re.compile(
    r"\b(выполню|делаю сайты|мо[её] портфолио|портфолио в профиле|"
    r"возьму заказ|оказываю услуги|сайты недорого|создаю|разработаю|"
    r"команда разработчиков|кейсы и отзывы)\b"
)
RESUME_RE = re.compile(r"\b(ищу работу|резюме|мой опыт|опыт работы|junior|middle|senior)\b")
PARTNERSHIP_RE = re.compile(
    r"\b(партн[её]р|бартер|процент от продаж|доля в проекте|ищу партнера)\b"
)
SPAM_RE = re.compile(r"\b(казино|ставки|криптосигнал|заработок без вложений|подписывайтесь)\b")
DISCUSSION_RE = re.compile(r"\b(кто знает|подскажите|как лучше|обсуждение|вопрос)\b")
ADDITIONAL_TASK_OBJECT_RE = re.compile(
    r"\b(сайт|лендинг|магазин|crm|api|оплат|форма|верстк|бот|дизайн)\w*\b"
)


@dataclass(frozen=True)
class EntityFact:
    type: str
    value_text: str
    value_norm: dict[str, Any]


@dataclass(frozen=True)
class ClassificationInput:
    normalized_text: str
    published_at: datetime
    passed_prefilter: bool | None
    keyword_hits: list[EntityFact]
    negative_hits: list[EntityFact]
    project_types: list[EntityFact]
    budgets: list[EntityFact]
    deadlines: list[EntityFact]
    contacts: list[EntityFact]


@dataclass(frozen=True)
class RulesClassificationResult:
    label: ClassificationLabel
    confidence: float
    manual_review: bool
    relevance_score: int
    explanation: dict[str, Any]


def classify_rules(
    data: ClassificationInput,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> RulesClassificationResult:
    active_settings = settings or get_settings()
    active_now = now or datetime.now(UTC)
    signals = build_signals(data, active_settings, active_now)
    label, confidence = choose_label(data, signals)
    manual_review = (
        active_settings.classification_manual_review_min_confidence
        <= confidence
        <= active_settings.classification_manual_review_max_confidence
    )
    relevance_score = calculate_relevance_score(signals, active_settings)
    return RulesClassificationResult(
        label=label,
        confidence=round(confidence, 4),
        manual_review=manual_review,
        relevance_score=relevance_score if label == "order" else 0,
        explanation={
            "signals": signals,
            "matched_rules": matched_rules(data),
            "label_reason": label_reason(label, data, signals),
            "formula": "section_9_rules_v1",
        },
    )


def build_signals(
    data: ClassificationInput,
    settings: Settings,
    now: datetime,
) -> dict[str, float]:
    normalized_text = data.normalized_text
    need = 1.0 if data.keyword_hits or NEED_RE.search(normalized_text) else 0.0
    task = 1.0 if data.project_types or TASK_RE.search(normalized_text) else 0.0
    if task == 0.0 and ADDITIONAL_TASK_OBJECT_RE.search(normalized_text):
        task = 0.5
    budget = budget_signal(data.budgets)
    deadline = 1.0 if data.deadlines else 0.0
    contact = 1.0 if data.contacts else 0.0
    niche = 1.0 if data.project_types else 0.0
    freshness = freshness_signal(data.published_at, settings, now)
    ad_signals = ad_signal(data)
    spam_signals = 1.0 if SPAM_RE.search(normalized_text) else 0.0
    p_client = max(0.0, min(1.0, 1.0 - (0.75 * ad_signals) - (0.35 * spam_signals)))
    if VACANCY_RE.search(normalized_text) or RESUME_RE.search(normalized_text):
        p_client = min(p_client, 0.35)
    return {
        "need": need,
        "task": task,
        "budget": budget,
        "deadline": deadline,
        "contact": contact,
        "niche": niche,
        "freshness": freshness,
        "p_client": p_client,
        "ad_signals": ad_signals,
        "spam_signals": spam_signals,
    }


def choose_label(
    data: ClassificationInput,
    signals: dict[str, float],
) -> tuple[ClassificationLabel, float]:
    text = data.normalized_text
    if not text:
        return "irrelevant", 0.9
    if SPAM_RE.search(text):
        return "spam", 0.92
    if VACANCY_RE.search(text):
        return "vacancy", 0.86
    if RESUME_RE.search(text):
        return "resume", 0.86
    if PARTNERSHIP_RE.search(text):
        return "partnership", 0.82
    if data.negative_hits or SERVICE_AD_RE.search(text):
        return "service_ad", 0.88
    if DISCUSSION_RE.search(text) and signals["need"] < 1.0:
        return "discussion", 0.76
    if data.passed_prefilter is False and not data.keyword_hits:
        return "irrelevant", 0.9

    order_strength = (
        0.32 * signals["need"]
        + 0.24 * signals["task"]
        + 0.16 * signals["niche"]
        + 0.12 * signals["budget"]
        + 0.08 * signals["contact"]
        + 0.08 * signals["deadline"]
    )
    if order_strength >= 0.58 and signals["ad_signals"] < 0.5 and signals["spam_signals"] < 0.5:
        return "order", min(0.95, max(0.62, order_strength + 0.18))
    if order_strength >= 0.42:
        return "order", 0.55
    if DISCUSSION_RE.search(text):
        return "discussion", 0.72
    return "irrelevant", 0.78


def calculate_relevance_score(signals: dict[str, float], settings: Settings) -> int:
    raw = (
        settings.relevance_weight_need * signals["need"]
        + settings.relevance_weight_task * signals["task"]
        + settings.relevance_weight_budget * signals["budget"]
        + settings.relevance_weight_deadline * signals["deadline"]
        + settings.relevance_weight_contact * signals["contact"]
        + settings.relevance_weight_niche * signals["niche"]
        + settings.relevance_weight_freshness * signals["freshness"]
        + settings.relevance_weight_p_client * signals["p_client"]
        - settings.relevance_weight_ad_penalty * signals["ad_signals"]
        - settings.relevance_weight_spam_penalty * signals["spam_signals"]
    )
    return round(max(0.0, min(1.0, raw)) * 100)


def budget_signal(budgets: list[EntityFact]) -> float:
    if not budgets:
        return 0.0
    first_budget = budgets[0].value_norm
    if first_budget.get("negotiable") is True:
        return 0.5
    return 1.0


def freshness_signal(published_at: datetime, settings: Settings, now: datetime) -> float:
    published = (
        published_at if published_at.tzinfo is not None else published_at.replace(tzinfo=UTC)
    )
    days = max(0.0, (now - published.astimezone(UTC)).total_seconds() / 86400)
    return max(0.0, min(1.0, 1 - days / settings.relevance_freshness_days))


def ad_signal(data: ClassificationInput) -> float:
    if data.negative_hits:
        return 1.0
    return 1.0 if SERVICE_AD_RE.search(data.normalized_text) else 0.0


def matched_rules(data: ClassificationInput) -> dict[str, list[str]]:
    return {
        "keyword_hits": [entity.value_text for entity in data.keyword_hits],
        "negative_hits": [entity.value_text for entity in data.negative_hits],
        "project_types": [
            entity.value_norm.get("project_type", "") for entity in data.project_types
        ],
        "budgets": [entity.value_text for entity in data.budgets],
        "deadlines": [entity.value_text for entity in data.deadlines],
        "contacts": [entity.value_text for entity in data.contacts],
    }


def label_reason(
    label: ClassificationLabel,
    data: ClassificationInput,
    signals: dict[str, float],
) -> str:
    if label == "order":
        return "positive need/task signals with client intent"
    if label == "service_ad":
        return "negative dictionary or performer advertising markers"
    if label == "vacancy":
        return "employment markers"
    if label == "resume":
        return "resume/job-search markers"
    if label == "partnership":
        return "partnership/barter markers"
    if label == "spam":
        return "spam markers"
    if label == "discussion":
        return "discussion/question markers"
    if data.passed_prefilter is False:
        return "message did not pass prefilter"
    return f"weak order signals: {signals}"
