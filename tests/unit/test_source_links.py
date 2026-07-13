import pytest

from app.core.errors import ApiError
from app.services.source_links import normalize_source_link


@pytest.mark.parametrize(
    ("raw_link", "expected"),
    [
        ("@Freelance_Orders", "freelance_orders"),
        ("t.me/Freelance_Orders", "freelance_orders"),
        ("https://t.me/Freelance_Orders", "freelance_orders"),
        ("https://t.me/Freelance_Orders/123", "freelance_orders"),
        ("Freelance_Orders", "freelance_orders"),
    ],
)
def test_normalize_source_link(raw_link: str, expected: str) -> None:
    result = normalize_source_link(raw_link)

    assert result.username == expected
    assert result.normalized_username == expected


@pytest.mark.parametrize(
    "raw_link",
    [
        "https://t.me/joinchat/abcdef",
        "https://t.me/+abcdef",
        "https://t.me/c/12345/678",
    ],
)
def test_private_source_links_are_rejected(raw_link: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        normalize_source_link(raw_link)

    assert exc_info.value.code == "SOURCE_NOT_PUBLIC"


@pytest.mark.parametrize(
    "raw_link",
    ["abc", "1channel", "bad-name", "https://example.com/channel", "@somebot"],
)
def test_invalid_usernames_are_rejected(raw_link: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        normalize_source_link(raw_link)

    assert exc_info.value.code == "INVALID_SOURCE_USERNAME"
