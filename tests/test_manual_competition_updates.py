from copy import deepcopy
import hashlib

from app.competitions import evaluate
from app.models import Candidate, Status
from tests.test_competitions import SOURCES, valid_report, URL
from tests.test_workflow import make_workflow, run_immediate


def setup():
    workflow, repo, telegram, _ = make_workflow()
    row = Candidate('contest-' + hashlib.sha256(URL.encode()).hexdigest()[:24], 'office', URL, URL, '',
                    'announcement:test', category='ai_competition', status=Status.TELEGRAM_SENT,
                    competition=evaluate(valid_report(), SOURCES), telegram_message_id=123, card_attempts=1)
    repo.save(row)
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    return workflow, repo, telegram, row


def test_repeated_manual_recheck_edits_original_without_rearming_delivery():
    workflow, repo, telegram, row = setup()
    edits = []
    async def edit(candidate, *, edit):
        assert edit
        edits.append(candidate.telegram_message_id)
        return 123
    telegram.send_competition = edit
    for _ in range(3):
        assert run_immediate(workflow.handle_text('/competition ' + URL))
    assert edits == [123, 123, 123] and telegram.cards == []
    saved = repo.get(row.id)
    assert saved.status == Status.TELEGRAM_SENT and saved.card_attempts == 1
    assert saved.telegram_message_id == 123 and not saved.competition['update_pending']


def test_lost_manual_edit_ack_is_durable_and_never_sends_a_new_card():
    workflow, repo, telegram, row = setup()
    async def edit(candidate, *, edit):
        assert edit and candidate.telegram_message_id == 123
        raise RuntimeError('unknown acknowledgement')
    telegram.send_competition = edit
    run_immediate(workflow.handle_text('/competition ' + URL))
    saved = repo.get(row.id)
    assert saved.competition['update_pending'] and saved.competition['refresh_failure_streak'] == 1
    assert saved.status == Status.TELEGRAM_SENT and saved.telegram_message_id == 123
    assert not telegram.cards
    assert run_immediate(workflow.discover(()))['card_updates_sent'] == 0


def test_owner_skip_during_manual_recheck_prevents_stale_save_and_edit():
    workflow, repo, telegram, row = setup()
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            current = repo.get(candidate.id)
            current.status = Status.SKIPPED
            current.answers['interest'] = 'no'
            repo.save(current)
            candidate.competition = evaluate(valid_report(), SOURCES)
    async def no_edit(*args, **kwargs):
        raise AssertionError('Owner decision must win')
    workflow.competition_screener = Screener()
    telegram.send_competition = no_edit
    run_immediate(workflow.handle_text('/competition ' + URL))
    assert repo.get(row.id).status == Status.SKIPPED
    assert repo.get(row.id).answers['interest'] == 'no'
    assert not telegram.cards


def test_owner_skip_during_rejected_manual_review_is_not_overwritten():
    workflow, repo, telegram, row = setup()
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            current = repo.get(candidate.id)
            current.answers['interest'] = 'no'
            current.status = Status.SKIPPED
            repo.save(current)
            candidate.competition = {'decision': 'rejected', 'facts': {}, 'sources': []}
            candidate.risks = ['An independently rejected review']
    workflow.competition_screener = Screener()
    run_immediate(workflow.handle_text('/competition ' + URL))
    assert repo.get(row.id).answers['interest'] == 'no'
    assert repo.get(row.id).telegram_message_id == 123
    assert not telegram.cards
