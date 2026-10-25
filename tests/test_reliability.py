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

