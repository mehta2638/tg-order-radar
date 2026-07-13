from app.core.config import Settings


def test_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Test Radar")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    settings = Settings()

    assert settings.app_name == "Test Radar"
    assert settings.environment == "test"
    assert settings.postgres_password == "test-password"
