from app.competitions import evaluate
from tests.test_competitions import valid_report,SOURCES,NOW


def test_equivalent_query_urls_are_not_recommended_twice_in_one_or_later_scan():
    from app.models import Candidate
    from tests.test_workflow import make_workflow,run_immediate
    class Source:
        last_report=[]
        async def discover(self):
            return [Candidate(str(i),'office','AI contest\n'+url,url,'','announcement:test',category='ai_competition')
                    for i,url in enumerate(['https://campus.edu.tw/entry?id=1&lang=tw','https://campus.edu.tw/entry?lang=tw&id=1'])],0
    class Screener:
        hosts=('edu.tw',)
        async def screen(self,candidate):
            candidate.competition=evaluate(valid_report(),SOURCES,now=NOW)
            candidate.first_round_score=90
    workflow,_,telegram,_=make_workflow()
    workflow.announcement_source=Source()
    workflow.competition_screener=Screener()
    first=run_immediate(workflow.discover(()))
    second=run_immediate(workflow.discover(()))
    assert first['cards_sent']==1 and first['duplicate_competition_cards_suppressed']==1
    assert second['cards_sent']==0 and len(telegram.cards)==1
