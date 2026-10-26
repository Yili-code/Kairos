from datetime import datetime, UTC, timedelta
import asyncio
import httpx
from app.models import Candidate, Status
from app.telegram import TelegramClient
from app.scan_runtime import ScanRunner, MemoryScanStore
from tests.test_workflow import make_workflow, run_immediate, FakeTelegram
from tests.test_competitions import valid_report, SOURCES
from app.competitions import evaluate


def test_old_queue_moves_forward_across_runs_without_fresh_lead_starvation():
    workflow, repo, _, _ = make_workflow()
    workflow.competition_screen_limit = 1
    calls = []
    class Screener:
        hosts = ()
        async def screen(self, candidate):
            calls.append(candidate.id)
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    for i in range(4):
        repo.save(Candidate(str(i), 'x', 'Online AI competition cash prize', 'https://example.test/'+str(i), '', 'test',
                            category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN))
    for _ in range(4):
        run_immediate(workflow.discover(()))
    assert calls == ['0', '1', '2', '3']


def test_lost_edit_acknowledgement_retries_same_message_without_new_card():
    workflow, repo, _, _ = make_workflow()
    report = evaluate(valid_report(), SOURCES)
    report['checked_at'] = (datetime.now(UTC)-timedelta(days=2)).isoformat()
    candidate = Candidate('sent', 'x', 'contest', 'https://example.test/', '', 'test',
        category='ai_competition', status=Status.TELEGRAM_SENT, telegram_message_id=123, competition=report)
    repo.save(candidate)
    calls = []
    class Screener:
        async def screen(self, candidate):
            candidate.competition = evaluate(valid_report(), SOURCES)
    class Telegram(FakeTelegram):
        async def send_competition(self, candidate, *, edit=False):
            calls.append((candidate.telegram_message_id, edit))
            if len(calls) == 1: raise RuntimeError('lost acknowledgement')
            return 123
    workflow.competition_screener = Screener()
    workflow.telegram = Telegram()
    assert run_immediate(workflow.discover(()))['card_update_errors'] == 1
    assert repo.get('sent').competition['update_pending']
    assert run_immediate(workflow.discover(()))['card_updates_sent'] == 0
    repo.get('sent').competition['refresh_retry_after'] = (datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    assert run_immediate(workflow.discover(()))['card_updates_sent'] == 1
    assert calls == [(123, True), (123, True)]
    assert repo.get('sent').status == Status.TELEGRAM_SENT
    assert not repo.get('sent').competition['update_pending']


def test_due_queue_prevents_false_full_success():
    async def run():
        store = MemoryScanStore()
        async def work(): return {'screen_queue_due': 4}
        assert (await ScanRunner(store, FakeTelegram()).run(work))['scan_status'] == 'partial'
        assert 'last_full_success' not in store.control
    asyncio.run(run())


def test_repeated_identical_edit_is_accepted_without_send():
    methods = []
    def handler(request):
        methods.append(request.url.path.rsplit('/', 1)[-1])
        return httpx.Response(400, json={'ok': False, 'description': 'Bad Request: message is not modified'})
    client = TelegramClient('test', 0, transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call('editMessageText', {'message_id': 123}))
    assert result['message_id'] == 123 and methods == ['editMessageText']


def test_listing_cap_rotates_instead_of_permanently_losing_tail_leads():
    from app.announcements import entries
    body = ''.join(f'<a href="https://example.test/{i}">AI competition {i}</a>' for i in range(26))
    first = entries(body, 'https://example.test/', ('example.test',), offset=0)
    second = entries(body, 'https://example.test/', ('example.test',), offset=20)
    assert len(first) == len(second) == 20
    assert len({item.id for item in first + second}) == 26


def test_unexpected_board_failure_does_not_discard_other_boards():
    from app.announcements import AnnouncementSource
    from app.public_fetch import PublicPage
    async def fetch(client, url, allowed):
        if '/broken' in url:
            raise RuntimeError('Injected independent source failure')
        return PublicPage(url, 'ok', body=b'<a href="https://example.test/event">AI competition</a>',
                          content_type='text/html')
    source = AnnouncementSource(('https://example.test/broken', 'https://example.test/good'),
                                ('example.test',), fetcher=fetch)
    rows, errors = asyncio.run(source.discover())
    assert len(rows) == 1 and errors == 1
    assert {row['status'] for row in source.last_report} == {'source_exception', 'ok'}


def test_screen_metrics_distinguish_retry_from_completed_assessment():
    workflow, repo, _, _ = make_workflow()
    candidate = Candidate('old-retry', 'x', 'Online AI competition cash prize', 'https://example.test/', '',
        'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN,
        competition={'fetch_report': [{'status': 'http_403'}]})
    repo.save(candidate)
    class Screener:
        hosts = ()
        async def screen(self, candidate):
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert result['screen_attempts'] == result['screen_retry_attempts'] == result['screen_completed'] == 1
    assert result['screen_leads_created'] == result['screen_queue_after'] == 0
    assert repo.get('old-retry').screen_attempts == 1


def test_repeated_origin_denials_leave_capacity_for_another_source():
    workflow, repo, _, _ = make_workflow()
    calls = []
    for i in range(12):
        repo.save(Candidate('bad'+str(i), 'x', 'AI competition', 'https://blocked.test/'+str(i), '',
            'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN))
    repo.save(Candidate('good', 'x', 'AI competition', 'https://readable.test/event', '',
        'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN))
    class Screener:
        hosts = ('blocked.test', 'readable.test')
        async def screen(self, candidate):
            calls.append(candidate.permalink)
            if 'blocked.test' in candidate.permalink:
                candidate.competition = {'decision': 'pending', 'sources': [], 'facts': {},
                    'fetch_report': [{'status': 'http_403', 'url': candidate.permalink}]}
            else:
                candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert len(calls) == 3 and calls[-1] == 'https://readable.test/event'
    assert result['screen_origin_deferred'] == 10
    assert result['screen_completed'] == 1 and result['competition_source_errors'] == 2


def test_notification_deduplication_reads_beyond_first_hundred_receipts():
    workflow, repo, telegram, _ = make_workflow()
    for i in range(101):
        repo.save(Candidate('sent'+str(i), 'x', 'old generic card', 'https://example.test/'+str(i), '',
                            'test', status=Status.TELEGRAM_SENT, telegram_message_id=i+1))
    url = 'https://campus.edu.tw/entry?id=1&lang=tw'
    prior = Candidate('prior', 'x', 'AI contest', url, '', 'test', category='ai_competition',
        status=Status.TELEGRAM_SENT, telegram_message_id=999, competition=evaluate(valid_report(), SOURCES))
    repo.save(prior)
    class Source:
        last_report = []
        async def discover(self):
            return [Candidate('duplicate', 'x', 'AI contest', 'https://campus.edu.tw/entry?lang=tw&id=1', '',
                'announcement:test', category='ai_competition')], 0
    class Screener:
        hosts = ('edu.tw',)
        async def screen(self, candidate):
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.announcement_source = Source()
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert result['cards_sent'] == 0 and telegram.cards == []
    assert result['duplicate_competition_cards_suppressed'] == 1


def test_delivery_cap_does_not_hide_an_outstanding_notification_as_success():
    workflow, repo, _, _ = make_workflow()
    workflow.max_cards = 1
    for i in range(2):
        repo.save(Candidate('queued'+str(i), 'x', 'card', 'https://example.test/'+str(i), '',
                            'test', first_round_score=90))
    async def run():
        runner = ScanRunner(MemoryScanStore(), FakeTelegram())
        first = await runner.run(lambda: workflow.discover(()))
        assert first['cards_sent'] == first['card_queue_due'] == 1
        assert first['scan_status'] == 'partial'
        second = await runner.run(lambda: workflow.discover(()))
        assert second['cards_sent'] == 1 and second['card_queue_due'] == 0
        assert second['scan_status'] == 'succeeded'
    asyncio.run(run())
