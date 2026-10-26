import hashlib

from app.competitions import evaluate
from app.config import DEFAULT_COMPETITION_COMPANIONS
from app.models import Candidate, Status
from tests.test_competitions import valid_report, SOURCES
from tests.test_workflow import make_workflow, run_immediate

PRIMARY, COMPANIONS = next(iter(DEFAULT_COMPETITION_COMPANIONS.items()))
ALIAS = COMPANIONS[0]


def existing(repo):
    row = Candidate('contest-'+hashlib.sha256(PRIMARY.encode()).hexdigest()[:24], 'office', PRIMARY, PRIMARY, '',
                    'announcement:curated', category='ai_competition', status=Status.TELEGRAM_SENT,
                    telegram_message_id=123, competition=evaluate(valid_report(), SOURCES))
    repo.save(row)
    return row


def test_reviewed_alias_is_deduplicated_before_fetching_or_model_screening():
    workflow, repo, telegram, _ = make_workflow()
    row = existing(repo)
    class Screener:
        hosts = ('edu.tw',)
        async def screen(self, candidate):
            raise AssertionError('Known delivered source alias must not be screened twice')
    class Source:
        last_report=[]
        async def discover(self):
            return [Candidate('notice','office','AI calligraphy competition\n'+ALIAS,ALIAS,'','announcement:test')],0
    workflow.competition_screener=Screener();workflow.announcement_source=Source()
    result=run_immediate(workflow.discover(()))
    assert result['screen_leads_created']==0 and result['screen_attempts']==0
    assert len(repo.items)==1 and telegram.cards==[]


def test_manual_alias_recheck_updates_the_known_primary_message():
    workflow, repo, telegram, _ = make_workflow()
    row=existing(repo);edits=[]
    class Screener:
        hosts=('edu.tw',)
        async def screen(self,candidate):
            candidate.competition=evaluate(valid_report(),SOURCES)
    async def edit(candidate,*,edit):
        assert edit
        edits.append(candidate.telegram_message_id)
        return 123
    workflow.competition_screener=Screener();telegram.send_competition=edit
    run_immediate(workflow.handle_text('/competition '+ALIAS))
    assert edits==[123] and telegram.cards==[] and len(repo.items)==1
