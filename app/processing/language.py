from __future__ import annotations

import re

CYRILLIC_RE = re.compile(r"[а-яёіїєґ]", re.IGNORECASE)
LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
UKRAINIAN_MARKERS_RE = re.compile(r"[іїєґ]", re.IGNORECASE)
RUSSIAN_MARKERS = {
    "нужен",
    "нужно",
    "ищу",
    "требуется",
    "сайт",
    "сделать",
    "разработать",
    "доработать",
    "бюджет",
}


def detect_language(normalized_text: str) -> str:
    if not normalized_text:
        return "unknown"

    cyrillic_count = len(CYRILLIC_RE.findall(normalized_text))
    latin_count = len(LATIN_RE.findall(normalized_text))
    alpha_count = cyrillic_count + latin_count
    if alpha_count == 0:
        return "unknown"

    cyrillic_ratio = cyrillic_count / alpha_count
    if cyrillic_ratio < 0.25:
        return "en"
    if UKRAINIAN_MARKERS_RE.search(normalized_text):
        return "uk"
    if any(marker in normalized_text for marker in RUSSIAN_MARKERS):
        return "ru"
    return "ru" if cyrillic_ratio >= 0.5 else "unknown"
