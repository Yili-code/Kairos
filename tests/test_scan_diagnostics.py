from app.models import Candidate
from app.competitions import CompetitionScreener
from tests.test_workflow import make_workflow, run_immediate


def test_insufficient_rules_are_not_reported_as_a_model_failure():
    class Source:
        last_report=[]
        async def discover(self):return [Candidate('empty','office','AI contest\nhttps://school.edu.tw/entry',
            'https://school.edu.tw/entry','','announcement:test',category='ai_competition')],0
    class Model:
        async def screen_competition(self,candidate,sources):return {'facts':{}}
    class Screener(CompetitionScreener):
        async def sources(self,text):return {'https://school.edu.tw/entry':'Public page without entry rules.'}
    workflow,_,_,_=make_workflow();workflow.announcement_source=Source();workflow.competition_screener=Screener(Model(),('edu.tw',))
    result=run_immediate(workflow.discover(()))
    assert result['competition_errors']==1 and result['competition_info_insufficient']==1
    assert result['competition_model_errors']==0 and result['cards_sent']==0
