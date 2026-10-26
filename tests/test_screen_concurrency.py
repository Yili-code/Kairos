from copy import deepcopy
import hashlib
from app.competitions import evaluate
from app.models import Candidate, Status
from tests.test_competitions import SOURCES, valid_report, URL
from tests.test_workflow import make_workflow, run_immediate


def pending(repo):
    row = Candidate('contest-' + hashlib.sha256(URL.encode()).hexdigest()[:24], 'office', URL, URL, '',
        'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN)
    repo.save(row)
    return row


def test_stale_automatic_result_cannot_erase_a_newer_receipt_or_owner_answers():
    workflow, repo, telegram, _ = make_workflow()
    row = pending(repo)
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            current = repo.get(candidate.id)
            current.status = Status.TELEGRAM_SENT
            current.telegram_message_id = 999
            current.answers = {'interest': 'no'}
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    saved = repo.get(row.id)
    assert saved.status == Status.TELEGRAM_SENT and saved.telegram_message_id == 999
    assert saved.answers == {'interest': 'no'}
    assert result['screen_completed'] == 0 and not telegram.cards


def test_manual_review_cannot_overlap_a_live_scheduled_claim():
    workflow, repo, telegram, _ = make_workflow()
    row = pending(repo)
    class Screener:
        hosts = ('devpost.com',)
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            assert run_immediate(workflow.handle_text('/competition ' + URL))
            assert self.calls == 1
            candidate.competition = evaluate(valid_report(), SOURCES)
    screener = workflow.competition_screener = Screener()
    run_immediate(workflow.discover(()))
    assert screener.calls == 1 and telegram.cards == [row.id]
    assert any('正在查核' in line for line in telegram.notifications)


def test_scheduled_run_cannot_overlap_a_live_manual_claim():
    workflow, repo, telegram, _ = make_workflow()
    row = pending(repo)
    class Screener:
        hosts = ('devpost.com',)
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            assert run_immediate(workflow.discover(()))['screen_attempts'] == 0
            candidate.competition = evaluate(valid_report(), SOURCES)
    screener = workflow.competition_screener = Screener()
    run_immediate(workflow.handle_text('/competition ' + URL))
    assert screener.calls == 1 and telegram.cards == [row.id]
    assert repo.get(row.id).screen_attempts == 1


def test_screen_snapshot_write_rejects_newer_same_time_state():
    _, repo, _, _ = make_workflow()
    row = pending(repo)
    claimed = repo.claim_for_screen(row.id)
    expected = claimed.to_dict()
    result = deepcopy(claimed)
    result.status = Status.DISCOVERED
    result.competition = evaluate(valid_report(), SOURCES)
    repo.get(row.id).answers = {'interest': 'no'}
    assert not repo.save_screen_result(result, expected)
    assert repo.get(row.id).status == Status.COMPETITION_SCREENING


def test_unexpected_manual_provider_failure_keeps_progress_without_rearming_retries():
    workflow, repo, telegram, _ = make_workflow()
    row = pending(repo)
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            raise RuntimeError('private exception must not escape or be stored')
    workflow.competition_screener = Screener()
    assert run_immediate(workflow.handle_text('/competition ' + URL))
    saved = repo.get(row.id)
    assert saved.status == Status.COMPETITION_PENDING_SCREEN
    assert saved.screen_failure_streak == 1 and saved.screen_attempts == 1
    assert saved.competition['analysis_error'] == 'manual_review_failed'
    assert 'private' not in str(saved.competition) and telegram.cards == []
