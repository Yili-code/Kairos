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
