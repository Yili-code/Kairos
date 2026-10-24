import asyncio
import pytest
from app.scan_runtime import ScanRunner, MemoryScanStore, status_text
from tests.test_workflow import FakeTelegram, make_workflow, run_immediate
from app.models import Candidate, Status


def test_partial_failure_is_not_full_success_and_repeated_alert_is_bounded():
    async def scenario():
        store = MemoryScanStore();telegram = FakeTelegram();runner = ScanRunner(store, telegram)
        async def work():return {'search_errors': 1, 'cards_sent': 0}
        for _ in range(3):assert (await runner.run(work))['scan_status'] == 'partial'
        assert len(telegram.notifications) == 1
        assert 'last_full_success' not in store.control
        async def healthy():return {'search_errors': 0, 'cards_sent': 0}
        assert (await runner.run(healthy))['scan_status'] == 'succeeded'
        assert store.control['consecutive_failures'] == 0
        assert store.control['last_full_success']['counts']['cards_sent'] == 0
    asyncio.run(scenario())


def test_shared_lease_suppresses_overlapping_runs_and_recovers_abandoned_owner():
    async def scenario():
        store = MemoryScanStore();runner = ScanRunner(store, FakeTelegram())
        entered = asyncio.Event();release = asyncio.Event()
        async def work():entered.set();await release.wait();return {}
        first = asyncio.create_task(runner.run(work));await entered.wait()
        assert (await runner.run(work)) == {'scan_status': 'busy'}
        release.set();await first
        assert store.start('dead', 0)
        assert store.start('replacement', 601)
        assert store.runs['dead']['status'] == 'abandoned'
        assert store.finish('dead', 'succeeded', {}, '', 602) is False
    asyncio.run(scenario())


def test_timeout_persists_failure_and_releases_lease_without_false_success():
    async def scenario():
        store = MemoryScanStore();runner = ScanRunner(store, FakeTelegram(), timeout=.01)
        async def blocked():await asyncio.Event().wait()
        with pytest.raises(TimeoutError):await runner.run(blocked)
        assert store.control['lease_until'] == 0
        assert store.control['last_finished']['error_type'] == 'TimeoutError'
        assert 'last_full_success' not in store.control
    asyncio.run(scenario())


def test_one_broken_candidate_does_not_abort_later_candidates_or_auto_contact():
    workflow,repo,telegram,_ = make_workflow()
    class Source:
        last_report = []
        async def discover(self):
            return [Candidate(k,'office',k,'https://school.edu.tw/'+k,'','announcement:test',category='ai_competition') for k in ['broken','good']],0
    class Screener:
        hosts = ('edu.tw',)
        async def screen(self,candidate):
            if candidate.text == 'broken':raise RuntimeError('Injected model failure')
            from app.competitions import evaluate
            from tests.test_competitions import valid_report, SOURCES
            candidate.competition = evaluate(valid_report(), SOURCES)
    workflow.announcement_source = Source();workflow.competition_screener = Screener()
    workflow.competition_mailer = None
    result = run_immediate(workflow.discover(()))
    assert result['candidate_errors'] == 1
    assert result['cards_sent'] == 1
    assert len(telegram.cards) == 1


def test_source_adapter_failure_still_allows_independent_threads_progress():
    workflow,_,telegram,_ = make_workflow()
    class Source:
        async def discover(self):raise RuntimeError('Injected parse failure')
    workflow.announcement_source = Source()
    result = run_immediate(workflow.discover(('hackathon',)))
    assert result['announcement_source_errors'] == 1 and result['cards_sent'] == 1
    assert len(telegram.cards) == 1


def test_threads_auth_or_rate_failure_does_not_repeat_for_every_keyword():
    from app.threads_client import ThreadsUnavailable
    workflow,_,_,_=make_workflow()
    class Threads:
        calls=0
        async def search(self,*args,**kwargs):
            self.calls+=1;raise ThreadsUnavailable(429)
    threads=Threads();workflow.threads=threads
    result=run_immediate(workflow.discover(('one','two','three')))
    assert threads.calls==1 and result['search_halted']==1 and result['search_terms_deferred']==2


def test_status_is_owner_only_and_does_not_evaluate_or_send_outreach(monkeypatch):
    from tests.test_api import settings, FakeWorkflow, FakeRequest, endpoint
    from app.main import create_app
    from fastapi import HTTPException
    workflow=FakeWorkflow();app=create_app(settings(monkeypatch),workflow)
    with pytest.raises(HTTPException):
        run_immediate(endpoint(app,'/tasks/status')(x_scheduler_secret='wrong'))
    asyncio.run(endpoint(app,'/telegram/webhook')(FakeRequest({'message':{'chat':{'id':42},'text':'/status'}}),
                                                  x_telegram_bot_api_secret_token='telegram-secret'))
    assert workflow.text_messages==[] and '最後完整成功' in workflow.telegram.notifications[0]
