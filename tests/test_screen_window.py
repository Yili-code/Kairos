import hashlib
from app.models import Candidate, Status
from app.competitions import evaluate
from app.storage import InMemoryRepository
from tests.test_workflow import make_workflow, run_immediate


def entry(url, *, failures=0):
    return Candidate('contest-' + hashlib.sha256(url.encode()).hexdigest()[:24], 'office', url, url, '',
        'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN,
        screen_failure_streak=failures, screen_attempts=failures)


def test_paused_first_page_cannot_permanently_hide_healthy_501st_candidate():
    workflow, repo, telegram, _ = make_workflow()
    for i in range(500):
        row = entry('https://school.edu.tw/paused/' + str(i), failures=3)
        repo.save(row)
        row.updated_at = '2026-01-01T00:00:00+00:00'
    healthy = entry('https://school.edu.tw/healthy-after-cap')
    repo.save(healthy)
    class Screener:
        hosts = ('edu.tw',)
        async def screen(self, candidate):
            assert candidate.id == healthy.id
            quote = 'All entrants must attend the final presentation on site in person.'
            candidate.competition = evaluate({'facts': {'attendance': {
                'value': 'onsite', 'quote': quote, 'url': candidate.permalink}}}, {candidate.permalink: quote})
    workflow.competition_screener = Screener()
    first = run_immediate(workflow.discover(()))
    second = run_immediate(workflow.discover(()))
    assert first['screen_attempts'] == 0
    assert second['screen_completed'] == second['screen_checks_completed'] == 1
    assert repo.get(healthy.id).status == Status.SKIPPED
    assert len([row for row in repo.items.values() if row.screen_failure_streak == 3]) == 500
    assert first['screen_queue_sample_saturated'] == 1
    assert second['screen_queue_sample_saturated'] == 0
    assert first['screen_queue_before'] == first['screen_queue_after'] == 501
    assert second['screen_queue_before'] == 501 and second['screen_queue_after'] == 500
    assert not telegram.cards


def test_cursor_handles_timestamp_ties_wraps_and_readonly_queries_do_not_advance_it():
    repo = InMemoryRepository()
    for i in range(3):
        row = Candidate(str(i), 'office', '', '', '', '', status=Status.COMPETITION_PENDING_SCREEN)
        repo.save(row)
        row.updated_at = '2026-01-01T00:00:00+00:00'
    repo.find_by_status([Status.COMPETITION_PENDING_SCREEN])
    repo.find_by_status([Status.COMPETITION_PENDING_SCREEN])
    assert [r.id for r in repo.screen_work_page(limit=2)] == ['0', '1']
    assert [r.id for r in repo.screen_work_page(limit=2)] == ['2']
    assert [r.id for r in repo.screen_work_page(limit=2)] == ['0', '1']


def test_firestore_cursor_initialization_does_not_require_an_unsupported_collection_path_property(monkeypatch):
    import sys
    import google.cloud
    from types import ModuleType, SimpleNamespace
    from app.storage import FirestoreRepository
    class Collection:
        def __init__(self, path):self.id = path.rsplit('/', 1)[-1]
        def document(self, doc_id):return SimpleNamespace(id=doc_id)
    class Client:
        def __init__(self, **kwargs):pass
        def collection(self, path):return Collection(path)
    firestore = ModuleType('google.cloud.firestore')
    firestore.Client = Client
    monkeypatch.setitem(sys.modules, 'google.cloud.firestore', firestore)
    monkeypatch.setattr(google.cloud, 'firestore', firestore, raising=False)
    first = FirestoreRepository('project', 'database', 'tests/first/kairos_opportunities')
    second = FirestoreRepository('project', 'database', 'tests/second/kairos_opportunities')
    assert first.collection.id == second.collection.id
    assert first.screen_cursor_reference.id != second.screen_cursor_reference.id
