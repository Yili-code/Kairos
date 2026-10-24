from copy import deepcopy
from datetime import datetime, UTC, timedelta
from app.competition_decisions import assessment_current
from app.profile import PROFILE
from app.competitions import evaluate
from tests.test_competitions import valid_report, SOURCES
from tests.test_workflow import make_workflow, run_immediate
from app.models import Candidate, Status


def test_profile_policy_and_age_must_match_before_using_an_assessment():
    report=evaluate(valid_report(),SOURCES)
    assert assessment_current(report,PROFILE)
    changed=deepcopy(PROFILE);changed['education']['status']='changed'
    assert not assessment_current(report,changed)
    assert not assessment_current(report,PROFILE,now=datetime.now(UTC)+timedelta(hours=25))
    assert not assessment_current({'checked_at':datetime.now(UTC).isoformat()},PROFILE)


def test_stale_eligible_queue_is_not_sent_as_a_current_recommendation():
    workflow,repo,telegram,_=make_workflow()
    report=evaluate(valid_report(),SOURCES)
    report['checked_at']=(datetime.now(UTC)-timedelta(days=2)).isoformat()
    candidate=Candidate('stale','x','contest','https://sample.devpost.com/rules','','test',category='ai_competition',competition=report)
    repo.save(candidate)
    result=run_immediate(workflow.discover(()))
    assert result['cards_sent']==0 and telegram.cards==[]
    assert repo.get('stale').status==Status.COMPETITION_PENDING_SCREEN


def test_unchanged_source_does_not_reuse_old_eligibility_after_profile_context_changes():
    import hashlib
    from app.competitions import CompetitionScreener
    class Model:
        async def screen_competition(self,candidate,sources):return {'facts': {'eligibility': {'value': 'unknown'}}}
    class Screener(CompetitionScreener):
        async def sources(self,text):return SOURCES
    report=evaluate(valid_report(),SOURCES)
    report['source_hashes']={url:hashlib.sha256(text.encode()).hexdigest() for url,text in SOURCES.items()}
    report['context_hash']='previous-profile-context'
    candidate=Candidate('changed','x','contest','https://sample.devpost.com/rules','','test',competition=report)
    run_immediate(Screener(Model(),('devpost.com',)).screen(candidate))
    assert candidate.competition['facts']['eligibility']['value']=='unknown'
