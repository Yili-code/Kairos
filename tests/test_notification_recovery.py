import asyncio
from datetime import datetime, UTC, timedelta
import httpx
import pytest
from app.telegram import TelegramClient, TelegramRejected
from app.models import Candidate, Status
from tests.test_workflow import make_workflow, run_immediate, FakeTelegram


@pytest.mark.parametrize('code,retryable', [(429, True), (400, False), (401, False), (403, False)])
def test_explicit_bot_api_rejection_is_distinct_from_unknown_delivery(code, retryable):
    client = TelegramClient('not-a-real-token', 0, transport=httpx.MockTransport(lambda _: httpx.Response(
        code, json={'ok': False, 'parameters': {'retry_after': 120}})))
    with pytest.raises(TelegramRejected) as exc:
        asyncio.run(client.call('sendMessage', {}))
    assert exc.value.retryable == retryable and exc.value.retry_after == 120
    assert 'not-a-real-token' not in str(exc.value)


def test_read_timeout_is_uncertain_but_connection_failure_can_be_retried():
    for error, safe in [(httpx.ReadTimeout('lost acknowledgement'), False), (httpx.ConnectError('not connected'), True)]:
        def fail(_):raise error
        client = TelegramClient('private-token', 0, transport=httpx.MockTransport(fail))
        with pytest.raises(RuntimeError) as exc:asyncio.run(client.call('sendMessage', {}))
        assert isinstance(exc.value, TelegramRejected) == safe
        assert 'private-token' not in str(exc.value)


def test_explicit_retry_survives_and_does_not_block_other_cards():
    workflow,repo,_,_ = make_workflow()
    class Telegram(FakeTelegram):
        async def send_candidate(self,candidate):
            self.cards.append(candidate.id)
            if candidate.id == '1':raise TelegramRejected('429', retryable=True, retry_after=3600)
            return 123
    telegram=Telegram();workflow.telegram=telegram
    first=run_immediate(workflow.discover(('hackathon',)))
    assert first['card_errors']==1 and repo.get('1').status==Status.DISCOVERED
    other=Candidate('other','x','other','https://example.test/2','','test',first_round_score=90)
    repo.save(other)
    second=run_immediate(workflow.discover(()))
    assert second['cards_sent']==1 and telegram.cards==['1','other']
    for attempt in range(2):
        candidate=repo.get('1');candidate.card_retry_after=(datetime.now(UTC)-timedelta(seconds=1)).isoformat()
        repo.save(candidate);run_immediate(workflow.discover(()))
    assert repo.get('1').status==Status.TELEGRAM_FAILED and repo.get('1').card_attempts==3
    run_immediate(workflow.discover(()))
    assert telegram.cards.count('1')==3


def test_interrupted_notification_is_visible_without_resend_and_late_completion_cannot_overwrite_owner():
    workflow,repo,telegram,_=make_workflow()
    candidate=Candidate('interrupted','x','x','https://example.test/','','test')
    repo.save(candidate);claimed=repo.claim_for_card(candidate.id)
    attempt=claimed.card_attempt_id
    claimed.updated_at=(datetime.now(UTC)-timedelta(minutes=11)).isoformat()
    result=run_immediate(workflow.discover(()))
    assert result['card_uncertain_recovered']==1 and telegram.cards==[]
    assert repo.get(candidate.id).status==Status.TELEGRAM_UNCERTAIN
    assert not repo.finish_card(candidate.id,attempt,Status.TELEGRAM_SENT,telegram_message_id=111)
    assert repo.get(candidate.id).telegram_message_id is None
