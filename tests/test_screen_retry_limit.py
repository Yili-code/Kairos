import hashlib
from datetime import UTC, datetime, timedelta
import asyncio
import pytest

from app.models import Candidate, Status
from app.storage import screen_claimable
from scripts.audit_scan_acceptance import queue_summary
from tests.test_workflow import make_workflow, run_immediate


URL = 'https://school.edu.tw/entry'


def pending(repo):
    row = Candidate('contest-' + hashlib.sha256(URL.encode()).hexdigest()[:24], 'office',
        'AI contest\n' + URL, URL, '', 'announcement:test', category='ai_competition',
        status=Status.COMPETITION_PENDING_SCREEN)
    repo.save(row)
    return row


def test_insufficient_assessments_stop_after_three_and_remain_visible():
    workflow, repo, telegram, _ = make_workflow()
    row = pending(repo)

    class Screener:
        hosts = ('edu.tw',)
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            candidate.competition = {'decision': 'pending', 'facts': {}, 'sources': []}

    screener = workflow.competition_screener = Screener()
    for _ in range(6):
        result = run_immediate(workflow.discover(()))
    assert screener.calls == row.screen_attempts == row.screen_failure_streak == 3
    assert row.status == Status.COMPETITION_PENDING_SCREEN
    assert result['screen_attention_remaining'] == 1
    assert result['screen_queue_cooling'] == result['screen_queue_due'] == 0
    assert not screen_claimable(row)
    assert telegram.cards == []
    audit = queue_summary([row.to_dict()])
    assert audit['pending'] == audit['screen_attention_remaining'] == 1
    assert audit['screen_attention_ids'] == [row.id]
    assert audit['cooling_or_leased'] == 0


def test_interrupted_attempts_are_persisted_before_provider_call_and_bounded():
    workflow, repo, _, _ = make_workflow()
    row = pending(repo)

    class Screener:
        hosts = ('edu.tw',)
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            raise asyncio.CancelledError()

    screener = workflow.competition_screener = Screener()
    for _ in range(5):
        if screener.calls < 3:
            with pytest.raises(asyncio.CancelledError):
                run_immediate(workflow.discover(()))
        else:
            run_immediate(workflow.discover(()))
        row.updated_at = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    assert screener.calls == row.screen_failure_streak == 3
    assert row.status == Status.COMPETITION_SCREENING
    assert not screen_claimable(row)


def test_manual_evidenced_review_can_recover_a_paused_item_without_resetting_history():
    workflow, repo, _, _ = make_workflow()
    row = pending(repo)
    row.screen_failure_streak = row.screen_attempts = 3

    class Screener:
        hosts = ('edu.tw',)
        async def screen(self, candidate):
            from app.competitions import evaluate
            from tests.test_competitions import valid_report, SOURCES
            candidate.competition = evaluate(valid_report(), SOURCES)

    workflow.competition_screener = Screener()
    assert run_immediate(workflow.handle_text('/competition ' + URL))
    current = repo.get(row.id)
    assert current.screen_failure_streak == 0
    assert current.screen_attempts == 4
    assert current.status == Status.TELEGRAM_SENT


def test_paused_item_does_not_block_other_due_work():
    workflow, repo, _, _ = make_workflow()
    blocked = pending(repo)
    blocked.screen_failure_streak = 3
    healthy_url = URL + '2'
    healthy = Candidate('contest-' + hashlib.sha256(healthy_url.encode()).hexdigest()[:24], 'office',
        'AI contest\n' + healthy_url, healthy_url, '', 'announcement:test',
        category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN)
    repo.save(healthy)

    class Screener:
        hosts = ('edu.tw',)
        async def screen(self, candidate):
            assert candidate.id == healthy.id
            candidate.competition = {'decision': 'rejected', 'facts': {}, 'sources': []}

    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert healthy.status == Status.SKIPPED and healthy.screen_failure_streak == 0
    assert result['screen_completed'] == result['screen_attention_remaining'] == 1
