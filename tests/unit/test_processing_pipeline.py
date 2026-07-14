from __future__ import annotations

import pytest

from app.processing.extractors import (
    extract_budget,
    extract_contacts,
    extract_deadlines,
    extract_project_types,
)
from app.processing.keywords import (
    InvalidKeywordRegex,
    KeywordRule,
    compile_keyword_rules,
    levenshtein_at_most_one,
    match_keywords,
)
from app.processing.language import detect_language
from app.processing.normalization import normalize_text
from app.processing.pipeline import process_text


def rules(*phrases: str, category: str = "explicit_need") -> list[KeywordRule]:
    return [
        KeywordRule(id=None, phrase=phrase, lang="ru", weight=5, category=category)
        for phrase in phrases
    ]


def test_normalize_text_preserves_meaning_without_original_mutation() -> None:
    assert normalize_text("  Нужен\u0301   сайт\n\nСРОЧН  ") == "нужен сайт срочно"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("нужен сайт, бюджет 100к", "ru"),
        ("потрібен сайт, бюджет 1000 грн", "uk"),
        ("need landing page asap", "en"),
        ("12345", "unknown"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(normalize_text(text)) == expected


def test_phrase_matcher_respects_word_boundaries() -> None:
    compiled = compile_keyword_rules(rules("сайт"))

    assert match_keywords("нужен сайт", compiled)
    assert not match_keywords("микросайтинг", compiled)


def test_regex_keyword_is_prevalidated() -> None:
    with pytest.raises(InvalidKeywordRegex):
        compile_keyword_rules([KeywordRule(None, "(", "ru", 1, is_regex=True)])

    compiled = compile_keyword_rules(
        [KeywordRule(None, r"нужн\w+\s+лендинг", "ru", 5, is_regex=True)]
    )
    assert match_keywords("нужно лендинг", compiled)


def test_fuzzy_match_only_for_long_words() -> None:
    compiled = compile_keyword_rules(rules("разработчик"))

    hit = match_keywords("ищу разрабочик", compiled)[0]

    assert hit.is_fuzzy is True
    assert hit.distance == 1
    assert levenshtein_at_most_one("сайт", "сай") == 1
    assert not match_keywords("нужен сай", compile_keyword_rules(rules("сайт")))


def test_negative_hits_make_prefilter_false() -> None:
    positive = compile_keyword_rules(rules("нужен сайт"))
    negative = compile_keyword_rules(rules("делаю сайты", category="negative"))

    result = process_text(
        "Нужен сайт? Я делаю сайты недорого, портфолио в профиле",
        positive_rules=positive,
        negative_rules=negative,
    )

    assert result.keyword_hits
    assert result.negative_hits
    assert result.passed_prefilter is False


@pytest.mark.parametrize(
    ("text", "project_type"),
    [
        ("нужно разработать интернет-магазин", "ecommerce"),
        ("кто может доработать woocommerce и оплату", "ecommerce"),
        ("нужен лендинг под рекламу", "landing_page"),
        ("надо починить api интеграцию", "integration"),
    ],
)
def test_extract_project_type_priority(text: str, project_type: str) -> None:
    entities = extract_project_types(normalize_text(text))

    assert entities[0].value_norm["project_type"] == project_type


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("бюджет от 50к до 80к ₽", {"amount_from": 50000, "amount_to": 80000, "currency": "RUB"}),
        ("до 100 000 руб", {"amount_from": None, "amount_to": 100000, "currency": "RUB"}),
        ("оплата 500 usd", {"amount_from": 500, "amount_to": 500, "currency": "USD"}),
        ("бюджет договорная", {"negotiable": True}),
    ],
)
def test_extract_budget(text: str, expected: dict[str, object]) -> None:
    entity = extract_budget(normalize_text(text))[0]

    assert expected.items() <= entity.value_norm.items()


@pytest.mark.parametrize(
    "text",
    [
        "сделать за 5 дней",
        "дедлайн до 25.12",
        "нужно срочно",
        "сдать к августу",
    ],
)
def test_extract_deadlines(text: str) -> None:
    assert extract_deadlines(normalize_text(text))


def test_extract_contacts() -> None:
    entities = extract_contacts(
        "Пишите @shopowner, +7 (999) 111-22-33, mail@test.ru или https://example.com"
    )
    kinds = {entity.value_norm["kind"] for entity in entities}

    assert {"telegram_username", "phone", "email", "url"}.issubset(kinds)
