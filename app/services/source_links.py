from dataclasses import dataclass
from re import fullmatch
from urllib.parse import urlparse

from fastapi import status

from app.core.errors import ApiError

USERNAME_PATTERN = r"[a-z][a-z0-9_]{4,31}"
PRIVATE_PATH_PREFIXES = ("joinchat", "+", "c")


@dataclass(frozen=True)
class NormalizedSourceLink:
    username: str
    normalized_username: str


def normalize_source_link(raw_link: str) -> NormalizedSourceLink:
    value = raw_link.strip()
    if not value:
        raise_invalid_username(raw_link)

    candidate = extract_username_candidate(value)
    normalized = candidate.lower()

    if not fullmatch(USERNAME_PATTERN, normalized):
        raise_invalid_username(raw_link)

    if normalized.endswith("bot"):
        raise_invalid_username(raw_link)

    return NormalizedSourceLink(username=normalized, normalized_username=normalized)


def extract_username_candidate(value: str) -> str:
    if value.startswith("@"):
        return value[1:]

    parsed = urlparse(value if "://" in value else f"https://{value}")
    hostname = (parsed.hostname or "").lower()
    if hostname in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            raise_invalid_username(value)

        first_part = path_parts[0]
        if first_part.startswith(PRIVATE_PATH_PREFIXES):
            raise_source_not_public(value)

        return first_part

    if "/" in value or "." in value:
        raise_invalid_username(value)

    return value


def raise_source_not_public(raw_link: str) -> None:
    raise ApiError(
        code="SOURCE_NOT_PUBLIC",
        message="Only public Telegram channels and groups can be added.",
        status_code=status.HTTP_409_CONFLICT,
        details={"link": raw_link},
    )


def raise_invalid_username(raw_link: str) -> None:
    raise ApiError(
        code="INVALID_SOURCE_USERNAME",
        message="Telegram source username is invalid.",
        status_code=422,
        details={"link": raw_link},
    )
