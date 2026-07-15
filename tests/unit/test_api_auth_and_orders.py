import pytest

from app.api.auth import resolve_api_key
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.main import create_app
from app.services.orders import ALLOWED_STATUS_TRANSITIONS


def test_resolve_api_key_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY_ADMIN", "admin")
    monkeypatch.setenv("API_KEY_OPERATOR", "operator")
    monkeypatch.setenv("API_KEY_VIEWER", "viewer")
    get_settings.cache_clear()

    try:
        assert resolve_api_key("admin").role == "admin"
        assert resolve_api_key("operator").role == "operator"
        assert resolve_api_key("viewer").role == "viewer"
    finally:
        get_settings.cache_clear()


def test_resolve_api_key_rejects_unknown_key() -> None:
    with pytest.raises(ApiError) as exc_info:
        resolve_api_key("missing")

    assert exc_info.value.code == "UNAUTHORIZED"


def test_order_status_state_machine_is_restrictive() -> None:
    assert "viewed" in ALLOWED_STATUS_TRANSITIONS["new"]
    assert "contacted" in ALLOWED_STATUS_TRANSITIONS["viewed"]
    assert "new" not in ALLOWED_STATUS_TRANSITIONS["archived"]
    assert "viewed" not in ALLOWED_STATUS_TRANSITIONS["irrelevant"]


def test_settings_have_safe_dev_api_keys() -> None:
    settings = Settings()

    assert settings.api_key_admin
    assert settings.api_key_operator
    assert settings.api_key_viewer


def test_openapi_includes_stage_ten_routes() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    assert "/api/v1/orders" in paths
    assert "/api/v1/orders/{order_id}/status" in paths
    assert "/api/v1/favorites/{order_id}" in paths
    assert "/api/v1/keywords" in paths
    assert "/api/v1/negative-keywords" in paths
    assert "/api/v1/stats/summary" in paths
