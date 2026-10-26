import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.competitions import evaluate
from tests.test_competitions import valid_report, SOURCES
from tests.test_refresh_concurrency import setup_refresh
from tests.test_workflow import run_immediate


def due(repo):
    repo.get("delivered").competition["refresh_retry_after"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()


@pytest.mark.parametrize("interrupted", [False, True])
def test_provider_failures_and_interruptions_are_persisted_before_io_and_stop(interrupted):
    workflow, repo, telegram = setup_refresh()
    calls = []
    class Screener:
        async def screen(self, candidate):
            calls.append(candidate.id)
            assert repo.get(candidate.id).competition["refresh_failure_streak"] == len(calls)
            if interrupted:
                raise asyncio.CancelledError()
            raise RuntimeError("private provider exception is never persisted")
    workflow.competition_screener = Screener()
    for _ in range(6):
        if interrupted and len(calls) < 3:
            with pytest.raises(asyncio.CancelledError):
                run_immediate(workflow.discover(()))
        else:
            result = run_immediate(workflow.discover(()))
        due(repo)
    saved = repo.get("delivered")
    assert len(calls) == saved.competition["refresh_failure_streak"] == 3
    assert saved.telegram_message_id == 99 and saved.status == "telegram_sent"
    assert "private" not in str(saved.competition)
    assert result["card_refresh_attention_remaining"] == 1
    assert not telegram.cards


def test_failed_edit_retries_same_message_with_backoff_then_pauses():
    workflow, repo, telegram = setup_refresh()
    edits = []
    class Screener:
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            candidate.competition = evaluate(valid_report(), SOURCES)
    async def edit(candidate, *, edit):
        assert edit
        edits.append(candidate.telegram_message_id)
        raise RuntimeError("lost acknowledgement")
    screener = workflow.competition_screener = Screener()
    telegram.send_competition = edit
    for _ in range(5):
        run_immediate(workflow.discover(()))
        # A normal next scan cannot retry before the persisted cooldown expires.
        count = len(edits)
        run_immediate(workflow.discover(()))
        assert len(edits) == count
        due(repo)
    assert edits == [99, 99, 99] and screener.calls == 1
    assert repo.get("delivered").competition["update_pending"] is True
    assert not telegram.cards


def test_successful_refresh_clears_consecutive_failure_budget():
    workflow, repo, telegram = setup_refresh()
    repo.get("delivered").competition["refresh_failure_streak"] = 2
    class Screener:
        async def screen(self, candidate):
            candidate.competition = evaluate(valid_report(), SOURCES)
    async def edit(candidate, *, edit):
        return 99
    workflow.competition_screener = Screener()
    telegram.send_competition = edit
    result = run_immediate(workflow.discover(()))
    assert result["card_updates_sent"] == 1
    assert repo.get("delivered").competition["refresh_failure_streak"] == 0
    assert repo.get("delivered").competition["refresh_retry_after"] == ""
