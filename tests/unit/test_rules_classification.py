from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from app.classification.rules import (
    ClassificationInput,
    EntityFact,
    calculate_relevance_score,
    classify_rules,
)
from app.core.config import Settings
from app.processing.keywords import KeywordRule, compile_keyword_rules
from app.processing.pipeline import PrefilterResult, process_text

FIXTURE_PATH = Path("tests/fixtures/rules_regression_dataset.json")
NOW = datetime(2026, 7, 15, tzinfo=UTC)


class RegressionExample(TypedDict):
    text: str
    label: str


POSITIVE_RULES = compile_keyword_rules(
    [
        KeywordRule(None, "нужен сайт", "ru", 5, "explicit_need"),
        KeywordRule(None, "нужен лендинг", "ru", 5, "landing_page"),
        KeywordRule(None, "нужно", "ru", 4, "explicit_need"),
        KeywordRule(None, "ищу разработчика", "ru", 4, "explicit_need"),
        KeywordRule(None, "ищу веб-разработчика", "ru", 4, "explicit_need"),
        KeywordRule(None, "требуется интернет-магазин", "ru", 5, "ecommerce"),
        KeywordRule(None, "доработать", "ru", 4, "revision"),
        KeywordRule(None, r"кто\s+может\s+доработать", "ru", 4, "revision", True),
    ]
)
NEGATIVE_RULES = compile_keyword_rules(
    [
        KeywordRule(None, "делаю сайты", "ru", 5, "negative"),
        KeywordRule(None, "сайты недорого", "ru", 5, "negative"),
        KeywordRule(None, "моё портфолио", "ru", 4, "negative"),
        KeywordRule(None, "портфолио в профиле", "ru", 4, "negative"),
        KeywordRule(None, "выполню", "ru", 4, "negative"),
        KeywordRule(None, "оказываю услуги", "ru", 4, "negative"),
        KeywordRule(None, "ищу работу", "ru", 5, "negative"),
        KeywordRule(None, "резюме", "ru", 5, "negative"),
        KeywordRule(None, "опыт работы", "ru", 3, "negative"),
        KeywordRule(None, "создаю интернет-магазины", "ru", 4, "negative"),
        KeywordRule(None, "разработаю лендинг", "ru", 4, "negative"),
    ]
)


def test_relevance_score_matches_section_9_formula() -> None:
    settings = Settings()
    signals = {
        "need": 1.0,
        "task": 1.0,
        "budget": 1.0,
        "deadline": 1.0,
        "contact": 1.0,
        "niche": 1.0,
        "freshness": 1.0,
        "p_client": 0.9,
        "ad_signals": 0.0,
        "spam_signals": 0.0,
    }

    assert calculate_relevance_score(signals, settings) == 99


def test_rules_regression_dataset_precision(capsys: object) -> None:
    dataset = load_dataset()
    predictions = [
        classify_rules(input_from_text(example["text"]), settings=Settings(), now=NOW).label
        for example in dataset
    ]
    expected = [example["label"] for example in dataset]
    correct = sum(
        1 for predicted, label in zip(predictions, expected, strict=True) if predicted == label
    )
    overall_precision = correct / len(dataset)
    predicted_orders = [
        (predicted, label)
        for predicted, label in zip(predictions, expected, strict=True)
        if predicted == "order"
    ]
    order_precision = (
        sum(1 for predicted, label in predicted_orders if label == "order") / len(predicted_orders)
        if predicted_orders
        else 0.0
    )
    print(
        "rules regression precision on small fixture: "
        f"overall={overall_precision:.3f}, order={order_precision:.3f}, n={len(dataset)}"
    )

    assert len(dataset) >= 50
    assert overall_precision >= 0.82
    assert order_precision >= 0.85


def test_low_confidence_order_goes_to_manual_review() -> None:
    result = classify_rules(
        input_from_text("Нужно что-то сделать по сайту, деталей пока нет"),
        settings=Settings(),
        now=NOW,
    )

    assert result.label == "order"
    assert result.manual_review is True
    assert result.relevance_score < Settings().order_min_relevance_score


def input_from_text(text: str) -> ClassificationInput:
    processed = process_text(
        text,
        positive_rules=POSITIVE_RULES,
        negative_rules=NEGATIVE_RULES,
    )
    return input_from_prefilter(processed)


def input_from_prefilter(result: PrefilterResult) -> ClassificationInput:
    facts = [*keyword_facts(result), *entity_facts(result)]
    return ClassificationInput(
        normalized_text=result.normalized_text,
        published_at=NOW - timedelta(days=1),
        passed_prefilter=result.passed_prefilter,
        keyword_hits=[fact for fact in facts if fact.type == "keyword_hit"],
        negative_hits=[fact for fact in facts if fact.type == "negative_keyword_hit"],
        project_types=[fact for fact in facts if fact.type == "project_type"],
        budgets=[fact for fact in facts if fact.type == "budget"],
        deadlines=[fact for fact in facts if fact.type == "deadline"],
        contacts=[fact for fact in facts if fact.type == "contact"],
    )


def keyword_facts(result: PrefilterResult) -> list[EntityFact]:
    return [
        *[
            EntityFact(
                type="keyword_hit",
                value_text=hit.matched_text,
                value_norm={"phrase": hit.phrase, "category": hit.category},
            )
            for hit in result.keyword_hits
        ],
        *[
            EntityFact(
                type="negative_keyword_hit",
                value_text=hit.matched_text,
                value_norm={"phrase": hit.phrase, "category": hit.category},
            )
            for hit in result.negative_hits
        ],
    ]


def entity_facts(result: PrefilterResult) -> list[EntityFact]:
    return [
        EntityFact(
            type=entity.type,
            value_text=entity.value_text,
            value_norm=entity.value_norm,
        )
        for entity in result.extracted_entities
    ]


def load_dataset() -> list[RegressionExample]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
