import pytest

from app.config import Settings


def test_production_rejects_missing_durable_and_external_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings.from_env(require_secrets=False)
    with pytest.raises(RuntimeError) as error:
        settings.validate_production()
    message = str(error.value)
    assert "GOOGLE_CLOUD_PROJECT" in message
    assert "GEMINI_API_KEY" in message
    assert "THREADS_ACCESS_TOKEN" in message


def test_dm_enabled_requires_browser_state(monkeypatch) -> None:
    monkeypatch.setenv("THREADS_DM_AUTOMATION_ENABLED", "true")
    monkeypatch.delenv("THREADS_STORAGE_STATE_JSON", raising=False)
    settings = Settings.from_env(require_secrets=False)
    with pytest.raises(RuntimeError) as error:
        settings.validate_production()
    assert "THREADS_STORAGE_STATE_JSON" in str(error.value)


def test_default_search_terms_cover_english_and_traditional_chinese(monkeypatch) -> None:
    monkeypatch.delenv("THREADS_SEARCH_TERMS", raising=False)

    settings = Settings.from_env(require_secrets=False)

    assert "hackathon" in settings.threads_search_terms
    assert "黑客松 組隊" in settings.threads_search_terms
    assert "徵隊友" in settings.threads_search_terms
    assert "有薪合作" in settings.threads_search_terms


def test_environment_is_normalized_before_security_checks(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", " Production ")

    settings = Settings.from_env(require_secrets=False)

    assert settings.app_env == "production"
    with pytest.raises(RuntimeError, match="Missing production configuration"):
        settings.validate_production()


def test_unknown_environment_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")

    with pytest.raises(RuntimeError, match="APP_ENV"):
        Settings.from_env(require_secrets=False)


def test_production_requires_https_public_url(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://kairos.example.test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "telegram-secret")
    monkeypatch.setenv("SCHEDULER_SECRET", "scheduler-secret")
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "threads-token")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    settings = Settings.from_env(require_secrets=False)

    with pytest.raises(RuntimeError, match="HTTPS"):
        settings.validate_production()
