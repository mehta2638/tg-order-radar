from __future__ import annotations

import re
import unicodedata

SPACE_RE = re.compile(r"\s+")
ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bсрочн\b", re.IGNORECASE), "срочно"),
    (re.compile(r"\bинет[\s-]?магазин\b", re.IGNORECASE), "интернет-магазин"),
)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""

    normalized = unicodedata.normalize("NFC", text)
    normalized = remove_noise_symbols(normalized)
    normalized = normalized.casefold()
    for pattern, replacement in ABBREVIATIONS:
        normalized = pattern.sub(replacement, normalized)
    return SPACE_RE.sub(" ", normalized).strip()


def remove_noise_symbols(text: str) -> str:
    chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in {"Mn", "So"}:
            continue
        chars.append(char)
    return "".join(chars)
