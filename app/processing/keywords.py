from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

WORD_RE = re.compile(r"[\wа-яёіїєґ-]+", re.IGNORECASE)


class InvalidKeywordRegex(ValueError):
    pass


@dataclass(frozen=True)
class KeywordRule:
    id: UUID | None
    phrase: str
    lang: str
    weight: int
    category: str | None = None
    is_regex: bool = False


@dataclass(frozen=True)
class CompiledKeywordRule:
    rule: KeywordRule
    pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class KeywordHit:
    phrase: str
    matched_text: str
    weight: int
    category: str | None
    is_regex: bool
    is_fuzzy: bool = False
    distance: int = 0


def compile_keyword_rules(rules: list[KeywordRule]) -> list[CompiledKeywordRule]:
    return [compile_keyword_rule(rule) for rule in rules]


def compile_keyword_rule(rule: KeywordRule) -> CompiledKeywordRule:
    if rule.is_regex:
        try:
            return CompiledKeywordRule(rule=rule, pattern=re.compile(rule.phrase, re.IGNORECASE))
        except re.error as exc:
            raise InvalidKeywordRegex(f"Invalid regex keyword {rule.phrase!r}: {exc}") from exc
    return CompiledKeywordRule(rule=rule)


def match_keywords(
    normalized_text: str,
    rules: list[CompiledKeywordRule],
    *,
    fuzzy_enabled: bool = True,
) -> list[KeywordHit]:
    if not normalized_text:
        return []

    hits: list[KeywordHit] = []
    words = WORD_RE.findall(normalized_text)
    for compiled in rules:
        rule = compiled.rule
        if rule.is_regex:
            if compiled.pattern is None:
                continue
            for match in compiled.pattern.finditer(normalized_text):
                hits.append(
                    KeywordHit(
                        phrase=rule.phrase,
                        matched_text=match.group(0),
                        weight=rule.weight,
                        category=rule.category,
                        is_regex=True,
                    )
                )
            continue

        phrase = rule.phrase.casefold().strip()
        exact_pattern = compile_phrase_pattern(phrase)
        exact_match = exact_pattern.search(normalized_text)
        if exact_match:
            hits.append(
                KeywordHit(
                    phrase=rule.phrase,
                    matched_text=exact_match.group(0),
                    weight=rule.weight,
                    category=rule.category,
                    is_regex=False,
                )
            )
            continue

        if fuzzy_enabled:
            fuzzy_hit = match_fuzzy_word(rule, phrase, words)
            if fuzzy_hit is not None:
                hits.append(fuzzy_hit)

    return hits


def compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped_parts = [re.escape(part) for part in phrase.split()]
    body = r"\s+".join(escaped_parts)
    return re.compile(rf"(?<![\wа-яёіїєґ]){body}(?![\wа-яёіїєґ])", re.IGNORECASE)


def match_fuzzy_word(
    rule: KeywordRule,
    phrase: str,
    words: list[str],
) -> KeywordHit | None:
    if " " in phrase or len(phrase) < 6:
        return None
    for word in words:
        if len(word) < 6:
            continue
        distance = levenshtein_at_most_one(phrase, word)
        if distance <= 1:
            return KeywordHit(
                phrase=rule.phrase,
                matched_text=word,
                weight=rule.weight,
                category=rule.category,
                is_regex=False,
                is_fuzzy=distance > 0,
                distance=distance,
            )
    return None


def levenshtein_at_most_one(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 1:
        return 2

    if len(left) == len(right):
        mismatches = sum(1 for index, char in enumerate(left) if right[index] != char)
        return mismatches if mismatches <= 1 else 2

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    mismatch_seen = False
    short_index = 0
    long_index = 0
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        if mismatch_seen:
            return 2
        mismatch_seen = True
        long_index += 1
    return 1
