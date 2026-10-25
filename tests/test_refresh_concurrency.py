from copy import deepcopy
from datetime import UTC, datetime, timedelta

from app.models import Candidate, Status
from tests.test_workflow import make_workflow, run_immediate


def setup_refresh():
    workflow, repo, telegram, _ = make_workflow()
    row = Candidate('delivered', 'owner', 'AI contest', 'https://school.edu.tw/entry', '', 'test',
        category='ai_competition', status=Status.TELEGRAM_SENT, telegram_message_id=99,
        updated_at=(datetime.now(UTC) - timedelta(days=2)).isoformat())
    repo.save(row)
    return workflow, repo, telegram


def test_owner_skip_during_screening_prevents_stale_refresh_and_edit():
    workflow, repo, telegram = setup_refresh()

    class Screener:
        async def screen(self, candidate):
            current = repo.get(candidate.id)
            current.status = Status.SKIPPED
            current.answers = {'interest': 'no'}
            repo.save(current)
            candidate.competition = {'decision': 'pending', 'sources': []}

    async def edit(*args, **kwargs):
        raise AssertionError('A stale refresh must not edit the owner card')

    workflow.competition_screener = Screener()
    telegram.send_competition = edit
    result = run_immediate(workflow.discover(()))
    assert repo.get('delivered').status == Status.SKIPPED
    assert repo.get('delivered').answers == {'interest': 'no'}
    assert result['card_updates_sent'] == 0


def test_owner_skip_during_telegram_edit_is_not_resurrected_by_completion():
    workflow, repo, telegram = setup_refresh()

    class Screener:
        async def screen(self, candidate):
            from app.competitions import evaluate
            from tests.test_competitions import valid_report, SOURCES
            candidate.competition = evaluate(valid_report(), SOURCES)

    async def edit(candidate, *, edit):
        assert edit
        current = repo.get(candidate.id)
        current.status = Status.SKIPPED
        repo.save(current)

    workflow.competition_screener = Screener()
    telegram.send_competition = edit
    run_immediate(workflow.discover(()))
    assert repo.get('delivered').status == Status.SKIPPED


def test_old_refresh_cannot_replace_a_newer_assessment_or_other_fields():
    _, repo, _ = setup_refresh()
    original = deepcopy(repo.get('delivered'))
    expected = original.to_dict()
    newer = repo.get('delivered')
    newer.competition = {'decision': 'rejected', 'update_pending': True}
    newer.answers = {'interest': 'no'}
    repo.save(newer)
    original.competition = {'decision': 'eligible'}
    assert not repo.save_refresh(original, expected)
    assert repo.get('delivered').competition['decision'] == 'rejected'
    fresh = deepcopy(repo.get('delivered'))
    expected = fresh.to_dict()
    fresh.competition['update_pending'] = False
    fresh.answers = {}
    fresh.telegram_message_id = 1000
    assert repo.save_refresh(fresh, expected)
    assert repo.get('delivered').answers == {'interest': 'no'}
    assert repo.get('delivered').telegram_message_id == 99
