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
