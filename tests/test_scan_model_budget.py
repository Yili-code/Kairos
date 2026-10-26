from app.competitions import CompetitionScreener
from app.models import Candidate
from tests.test_workflow import make_workflow, run_immediate
from tests.test_competitions import SOURCES


def test_unexpected_model_failures_cannot_multiply_the_configured_model_budget():
    workflow,repo,_,_=make_workflow();calls=[]
    class Model:
        async def screen_competition(self,candidate,sources):
            calls.append(candidate.id);raise AttributeError('Injected unexpected provider adapter fault')
    class Screener(CompetitionScreener):
        async def sources(self,text):return SOURCES
    class Source:
        last_report=[]
        async def discover(self):return [Candidate(str(i),'x','AI contest\nhttps://test.edu.tw/event/'+str(i),
            'https://test.edu.tw/event/'+str(i),'','announcement:test',category='ai_competition') for i in range(8)],0
    workflow.competition_screener=Screener(Model(),('edu.tw',));workflow.announcement_source=Source()
    result=run_immediate(workflow.discover(()))
    assert len(calls)==result['model_evaluations_attempted']==workflow.competition_screen_limit==3
    assert result['candidate_errors']==3 and result['cards_sent']==0


def test_rate_limited_refresh_stops_new_model_checks_in_the_same_run():
    from datetime import UTC, datetime, timedelta
    from app.competitions import evaluate
    from app.models import Status
    from tests.test_competitions import valid_report
    workflow,repo,telegram,_=make_workflow();calls=[]
    report=evaluate(valid_report(),SOURCES)
    report['checked_at']=(datetime.now(UTC)-timedelta(days=2)).isoformat()
    delivered=Candidate('delivered','office','AI contest','https://school.edu.tw/sent','','test',
        category='ai_competition',status=Status.TELEGRAM_SENT,competition=report,telegram_message_id=42)
    repo.save(delivered)
    class Model:
        async def screen_competition(self,candidate,sources):
            calls.append(candidate.id)
            raise RuntimeError('Gemini API returned HTTP 429')
    class Screener(CompetitionScreener):
        async def sources(self,text):return SOURCES
    class Source:
        last_report=[]
        async def discover(self):
            return [Candidate('fresh','office','AI software hackathon\nhttps://school.edu.tw/fresh',
                'https://school.edu.tw/fresh','','announcement:test',category='ai_competition')],0
    workflow.competition_screener=Screener(Model(),('edu.tw',));workflow.announcement_source=Source()
    result=run_immediate(workflow.discover(()))
    assert calls==['delivered'] and result['model_evaluations_attempted']==1
    assert result['model_rate_limited']==1 and result['screen_leads_created']==1
    assert result['screen_attempts']==0 and telegram.cards==[]
