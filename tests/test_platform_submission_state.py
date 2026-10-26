import asyncio
from pathlib import Path
import httpx
import hashlib
from app.competition_decisions import canonical_contest_url
from app.competitions import CompetitionScreener, PageText
from app.models import Candidate, Status
from tests.test_competitions import SOURCES, valid_report
from tests.test_workflow import make_workflow

URL = 'https://itch.io/jam/cali-game-jam-4-edicion-colombia-solidaria-2026'
HTML = Path('tests/fixtures/screening/itch-closed-submission.html').read_text()


def test_real_native_closed_widget_finishes_without_model_or_budget_slot():
    class Model:
        async def screen_competition(self, *args):
            raise AssertionError('Closed native submissions need no model')
    def budget(): raise AssertionError('Must preserve model slot')
    def handler(request): return httpx.Response(200, headers={'content-type': 'text/html'}, text=HTML)
    async def check():
        row = Candidate('closed', 'office', URL, URL, '', 'announcement:test')
        report = (await CompetitionScreener(Model(), ('itch.io',), transport=httpx.MockTransport(handler)).screen(row, model_budget=budget)).competition
        assert report['decision'] == 'rejected'
        assert report['assessment_method'] == 'platform_submission_state'
        assert report['platform_submission']['quote'] in ' '.join(PageTextData(HTML))
        assert report['platform_submission']['url'] == URL
        assert report['facts']['deadline']['value'] == 'unknown'
    asyncio.run(check())


def PageTextData(html):
    parser = PageText(base_url=URL); parser.feed(html); return parser.parts


def test_user_authored_closed_text_and_other_hosts_cannot_close_submission():
    for url, html in [
        (URL, '<div class="jam_content user_formatted">' + HTML + '</div>'),
        ('https://unrelated.test/jam/fake', HTML),
        (URL, '<div class="jam_content">Submission is closed and voting is now in progress</div>'),
        (URL, HTML.replace('during_voting', 'before_submit')),
    ]:
        parser = PageText(base_url=url); parser.feed(html)
        assert not parser.submission_closed


def test_closed_candidate_saves_and_leaves_model_slot_for_next_candidate():
    workflow, repo, telegram, _ = make_workflow()
    workflow.competition_screen_limit = 1
    ids = {label: 'contest-' + hashlib.sha256(canonical_contest_url(url).encode()).hexdigest()[:24]
           for label, url in [('closed', URL), ('healthy', next(iter(SOURCES)))]}
    for label, url in [('closed', URL), ('healthy', next(iter(SOURCES)))]:
        rid = ids[label]
        repo.save(Candidate(rid, 'office', url, url, '', 'announcement:test', category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN))
    class Model:
        calls = []
        async def screen_competition(self, candidate, sources):
            self.calls.append(candidate.id)
            report = valid_report(); report['facts']['attendance']['value'] = 'onsite'
            return report
    model = Model()
    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=HTML if str(request.url) == URL else next(iter(SOURCES.values())))
    workflow.competition_screener = CompetitionScreener(model, ('itch.io', 'devpost.com'), transport=httpx.MockTransport(handler))
    result = asyncio.run(workflow.discover(()))
    assert model.calls == [ids['healthy']]
    assert result['screen_completed'] == result['screen_results_saved'] == 2
    assert result['screen_platform_closed'] == result['screen_checks_completed'] == result['screen_model_calls'] == 1
    assert repo.get(ids['closed']).status == repo.get(ids['healthy']).status == Status.SKIPPED
    report = next(r for r in result['screen_candidate_reports'] if r['id'] == ids['closed'])
    assert report['stop_reason'] == 'platform_submission_closed' and report['model_calls'] == 0
    assert not report['assessment_completed'] and report['assessment_method'] == 'platform_submission_state'
    assert not telegram.cards
    asyncio.run(workflow.discover(()))
    assert model.calls == [ids['healthy']]
