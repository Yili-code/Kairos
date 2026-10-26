from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib

import pytest

from app.competition_decisions import competition_card_gaps
from app.competitions import evaluate
from app.models import Candidate, Status
from app.telegram import TelegramClient, CompetitionCardIncomplete
from app.workflow import card_recommendable
from tests.test_competitions import valid_report, SOURCES, NOW, URL
from tests.test_workflow import make_workflow, run_immediate


def complete():
    return evaluate(valid_report(), SOURCES, now=NOW)


@pytest.mark.parametrize('key', ['prize', 'prize_kind', 'deadline', 'deliverables', 'ai_policy'])
def test_each_missing_core_fact_blocks_card(key):
    report = complete()
    assert not competition_card_gaps(report, now=NOW)
    report['facts'][key] = {'value': 'unknown', 'quote': '', 'url': ''}
    assert competition_card_gaps(report, now=NOW)


def test_values_without_evidence_and_expired_dates_are_not_useful_cards():
    report = complete()
    report['facts']['prize']['quote'] = ''
    assert '現金獎金' in competition_card_gaps(report, now=NOW)
    report = complete()
    report['facts']['deadline']['value'] = (NOW - timedelta(seconds=1)).isoformat()
    assert '有效截止時間' in competition_card_gaps(report, now=NOW)


@pytest.mark.parametrize('key,value', [('total_hours', None), ('total_hours', 0),
    ('ai_share', None), ('ai_share', 2), ('extra_tools_twd', None), ('extra_tools_twd', float('nan'))])
def test_unusable_estimate_blocks_card(key, value):
    report = complete()
    report['estimate'][key] = value
    assert '完整投入估算' in competition_card_gaps(report, now=NOW)


@pytest.mark.parametrize('mode', ['send', 'edit', 'generic'])
def test_manual_resend_and_edit_cannot_bypass_final_telegram_information_gate(mode):
    class NoNetwork(TelegramClient):
        async def call(self, *args, **kwargs):
            raise AssertionError('Incomplete cards must make zero Telegram calls')
    report = {'decision': 'pending', 'sources': [URL], 'facts': {
        'registration_amount': {'value': '$99 USD', 'quote': '$99 USD', 'url': URL},
        'submission': {'value': 'online', 'quote': 'online', 'url': URL}}, 'estimate': {}}
    original = deepcopy(report)
    row = Candidate('historical-incomplete', 'office', 'un Design Award', URL, '', 'test',
                    category='ai_competition', competition=report, telegram_message_id=99)
    with pytest.raises(CompetitionCardIncomplete) as error:
        client = NoNetwork('not-a-token', 42)
        run_immediate(client.send_candidate(row) if mode == 'generic'
                      else client.send_competition(row, edit=mode == 'edit'))
    assert len(error.value.gaps) == 5
    assert row.competition == original


def test_auto_notifications_require_eligible_and_useful_not_just_a_model_label():
    row = Candidate('c', 'office', 'contest', URL, '', 'test', category='ai_competition', competition=complete())
    assert card_recommendable(row, 55)
    row.competition['decision'] = 'pending'
    assert not card_recommendable(row, 55)
    row.competition['decision'] = 'eligible'
    row.competition['facts']['prize']['value'] = 'unknown'
    assert not card_recommendable(row, 55)


def test_manual_incomplete_review_stays_background_and_does_not_rearm_failed_budget():
    workflow, repo, telegram, _ = make_workflow()
    key = 'contest-' + hashlib.sha256(URL.encode()).hexdigest()[:24]
    row = Candidate(key, 'office', URL, URL, '', 'test', category='ai_competition',
                    status=Status.COMPETITION_PENDING_SCREEN, screen_failure_streak=3)
    repo.save(row)
    class Screener:
        hosts = ('devpost.com',)
        async def screen(self, candidate):
            candidate.competition = {'decision': 'pending', 'sources': [URL],
                'facts': {'submission': {'value': 'online', 'quote': 'online', 'url': URL}}, 'estimate': {}}
    workflow.competition_screener = Screener()
    assert run_immediate(workflow.handle_text('/competition ' + URL))
    assert telegram.cards == []
    assert repo.get(key).status == Status.COMPETITION_PENDING_SCREEN
    assert repo.get(key).screen_failure_streak == 4
    assert telegram.notifications == ['資料不足，已留待補查：現金獎金、有效截止時間、交付內容、AI 規則、完整投入估算']
    assert run_immediate(workflow._deliver_card(key)) == 'incomplete'
    assert repo.get(key).card_attempts == 0


def test_incomplete_refresh_keeps_useful_card_and_stops_after_three_bounded_attempts():
    workflow, repo, telegram, _ = make_workflow()
    report = complete()
    report['checked_at'] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    row = Candidate('sent', 'office', 'contest', URL, '', 'test', category='ai_competition',
                    status=Status.TELEGRAM_SENT, competition=report, telegram_message_id=99)
    repo.save(row)
    class Screener:
        calls = 0
        async def screen(self, candidate):
            self.calls += 1
            candidate.competition = {'decision': 'pending', 'sources': [], 'facts': {}, 'estimate': {}}
    screener = workflow.competition_screener = Screener()
    async def no_edit(*args, **kwargs):
        raise AssertionError('Never replace the useful original card with an empty refresh')
    telegram.send_competition = no_edit
    for _ in range(4):
        result = run_immediate(workflow.discover(()))
        saved = repo.get('sent')
        saved.competition['refresh_retry_after'] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert screener.calls == 3
    assert saved.competition['refresh_incomplete_attempts'] == 3
    assert saved.competition['facts']['prize'] == report['facts']['prize']
    assert saved.status == Status.TELEGRAM_SENT and saved.telegram_message_id == 99
    assert len(saved.competition['information_gaps']) == 5
    assert result['stale_sent_remaining'] == 1


def test_legacy_incomplete_queued_edit_is_deferred_and_bounded_without_provider_calls():
    workflow, repo, telegram, _ = make_workflow()
    row = Candidate('legacy-edit', 'office', 'contest', URL, '', 'test', category='ai_competition',
        status=Status.TELEGRAM_SENT, telegram_message_id=99,
        competition={'decision': 'pending', 'facts': {}, 'estimate': {}, 'sources': [], 'update_pending': True})
    repo.save(row)
    class NoCalls:
        async def screen(self, candidate):
            raise AssertionError('Do not use a model to retry an already queued edit')
    async def no_edit(*args, **kwargs):
        raise AssertionError('Do not send the legacy empty update')
    workflow.competition_screener = NoCalls()
    telegram.send_competition = no_edit
    for _ in range(5):
        run_immediate(workflow.discover(()))
        saved = repo.get(row.id)
        saved.competition['refresh_retry_after'] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert saved.competition['refresh_incomplete_attempts'] == 3
    assert saved.competition['update_pending'] is True
    assert saved.status == Status.TELEGRAM_SENT


@pytest.mark.parametrize('value', ['Cash awards TBA', '現金獎金待公告', 'USD 0', '2026 cash awards'])
def test_unannounced_or_zero_awards_do_not_pass_the_information_gate(value):
    report=complete();report['facts']['prize']['value']=value
    assert '現金獎金' in competition_card_gaps(report)
