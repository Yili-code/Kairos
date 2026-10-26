from dataclasses import replace

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.main import create_app


class FakeTelegram:
    def __init__(self) -> None:
        self.notifications = []

    async def notify(self, text: str) -> None:
        self.notifications.append(text)


class FakeWorkflow:
    def __init__(self) -> None:
        self.telegram = FakeTelegram()
        self.callbacks = []
        self.text_messages = []

    async def handle_callback(self, callback_id: str, data: str) -> None:
        self.callbacks.append((callback_id, data))

    async def handle_text(self, text: str, *, reply_to_text: str = "") -> bool:
        self.text_messages.append((text, reply_to_text))
        return True


def settings(monkeypatch) -> Settings:
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "telegram-secret")
    monkeypatch.setenv("SCHEDULER_SECRET", "scheduler-secret")
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    return Settings.from_env(require_secrets=False)


class FakeRequest:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def json(self):
        return self.payload


def endpoint(app, path: str):
    return next(route.endpoint for route in app.routes if getattr(route, "path", "") == path)


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Endpoint unexpectedly waited on real asynchronous I/O")


def test_telegram_webhook_rejects_invalid_secret(monkeypatch) -> None:
    workflow = FakeWorkflow()
    app = create_app(settings(monkeypatch), workflow)
    webhook = endpoint(app, "/telegram/webhook")

    with pytest.raises(HTTPException) as error:
        run_immediate(webhook(
            FakeRequest({"message": {"chat": {"id": 42}, "text": "hello"}}),
            x_telegram_bot_api_secret_token="wrong",
        ))

    assert error.value.status_code == 403
    assert workflow.text_messages == []


def test_telegram_webhook_rejects_non_owner_chat(monkeypatch) -> None:
    workflow = FakeWorkflow()
    app = create_app(settings(monkeypatch), workflow)
    webhook = endpoint(app, "/telegram/webhook")

    with pytest.raises(HTTPException) as error:
        run_immediate(webhook(
            FakeRequest({"message": {"chat": {"id": 99}, "text": "hello"}}),
            x_telegram_bot_api_secret_token="telegram-secret",
        ))

    assert error.value.status_code == 403
    assert workflow.text_messages == []


def test_telegram_reply_context_reaches_workflow(monkeypatch) -> None:
    workflow = FakeWorkflow()
    app = create_app(settings(monkeypatch), workflow)
    webhook = endpoint(app, "/telegram/webhook")

    response = run_immediate(webhook(
        FakeRequest({
                "message": {
                    "chat": {"id": 42},
                    "text": "Need a clearer role.",
                    "reply_to_message": {"text": "Question\n\n[Kairos:123:note]"},
                },
        }),
        x_telegram_bot_api_secret_token="telegram-secret",
    ))

    assert response == {"ok": True}
    assert workflow.text_messages == [("Need a clearer role.", "Question\n\n[Kairos:123:note]")]


def test_scheduler_rejects_invalid_secret(monkeypatch) -> None:
    workflow = FakeWorkflow()
    app = create_app(settings(monkeypatch), workflow)
    discover = endpoint(app, "/tasks/discover")

    with pytest.raises(HTTPException) as error:
        run_immediate(discover(x_scheduler_secret="wrong"))

    assert error.value.status_code == 403


def test_scheduler_fails_closed_without_threads_token(monkeypatch) -> None:
    workflow = FakeWorkflow()
    app = create_app(settings(monkeypatch), workflow)
    discover = endpoint(app, "/tasks/discover")

    with pytest.raises(HTTPException) as error:
        run_immediate(discover(x_scheduler_secret="scheduler-secret"))

    assert error.value.status_code == 503
    assert error.value.detail == "Threads search is not configured"


def test_production_disables_interactive_api_documentation(monkeypatch) -> None:
    production = replace(
        settings(monkeypatch),
        app_env="production",
        public_base_url="https://kairos.example.test",
        telegram_bot_token="telegram-token",
        threads_access_token="threads-token",
        gemini_api_key="gemini-key",
        google_cloud_project="test-project",
    )

    app = create_app(production, FakeWorkflow())

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_authenticated_status_identifies_paused_checks_without_restarting_them(monkeypatch):
    from app.storage import InMemoryRepository
    from app.models import Candidate, Status
    workflow = FakeWorkflow()
    workflow.repository = InMemoryRepository()
    row = Candidate('paused', 'office', 'AI film festival', 'https://cuefilmfest.com/terms-and-conditions', '',
        'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN,
        screen_failure_streak=3, screen_attempts=3,
        competition={'fetch_report': [{'status': 'dynamic_rules_unavailable'}]})
    workflow.repository.save(row)
    before = row.to_dict()
    app = create_app(settings(monkeypatch), workflow)
    import asyncio
    result = asyncio.run(endpoint(app, '/tasks/status')(x_scheduler_secret='scheduler-secret'))
    assert result['review_needed'][0]['url'] == row.permalink
    assert result['review_needed'][0]['source_statuses'] == ['dynamic_rules_unavailable']
    assert row.to_dict() == before and workflow.text_messages == []
