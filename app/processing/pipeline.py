from __future__ import annotations

from dataclasses import dataclass

from app.processing.extractors import ExtractedEntity, extract_entities
from app.processing.keywords import (
    CompiledKeywordRule,
    KeywordHit,
    match_keywords,
)
from app.processing.language import detect_language
from app.processing.normalization import normalize_text


@dataclass(frozen=True)
class PrefilterResult:
    original_text: str | None
    normalized_text: str
    detected_language: str
    keyword_hits: list[KeywordHit]
    negative_hits: list[KeywordHit]
    extracted_entities: list[ExtractedEntity]
    passed_prefilter: bool


def process_text(
    original_text: str | None,
    *,
    positive_rules: list[CompiledKeywordRule],
    negative_rules: list[CompiledKeywordRule],
    fuzzy_enabled: bool = True,
) -> PrefilterResult:
    normalized_text = normalize_text(original_text)
    detected_language = detect_language(normalized_text)

    if not normalized_text:
        return PrefilterResult(
            original_text=original_text,
            normalized_text=normalized_text,
            detected_language=detected_language,
            keyword_hits=[],
            negative_hits=[],
            extracted_entities=[],
            passed_prefilter=False,
        )

    keyword_hits = match_keywords(normalized_text, positive_rules, fuzzy_enabled=fuzzy_enabled)
    negative_hits = match_keywords(normalized_text, negative_rules, fuzzy_enabled=fuzzy_enabled)
    extracted_entities = extract_entities(normalized_text, original_text)
    passed_prefilter = bool(keyword_hits) and not negative_hits

    return PrefilterResult(
        original_text=original_text,
        normalized_text=normalized_text,
        detected_language=detected_language,
        keyword_hits=keyword_hits,
        negative_hits=negative_hits,
        extracted_entities=extracted_entities,
        passed_prefilter=passed_prefilter,
    )
