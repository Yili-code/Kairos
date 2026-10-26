import asyncio
from pathlib import Path

import httpx

from app.competitions import CompetitionScreener, PageText
from app.models import Candidate
from tests.test_competitions import SOURCES, valid_report

DIRECTORY = "https://www.contestwatchers.com/tactical-urbanism-now-2026-architecture-competition/"
HTML = Path("tests/fixtures/screening/contestwatchers-official-link.html").read_text()


def row():
    return Candidate("c", "office", DIRECTORY, DIRECTORY, "", "announcement:test")


def test_actual_directory_label_is_discovered_but_does_not_expand_host_permissions():
    parser = PageText(base_url=DIRECTORY)
    parser.feed(HTML)
    assert not parser.rule_links
    assert parser.official_links == ["https://www.terravivacompetitions.com/tactical-urbanism-competition-2026/"]
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML)
    class Model:
        async def screen_competition(self, candidate, sources):
            raise AssertionError("A directory summary must not consume a model call")
    async def check():
        screener = CompetitionScreener(Model(), ("contestwatchers.com",), transport=httpx.MockTransport(handler))
        result = await screener.screen(row())
        assert result.competition["sources"] == []
        assert result.competition["decision"] == "pending"
        assert any(r["status"] == "official_link_not_allowed" for r in result.competition["fetch_report"])
    asyncio.run(check())
    assert requests == [DIRECTORY]


def test_existing_allowed_official_handoff_reaches_model_and_can_complete():
    official = next(iter(SOURCES))
    requests = []
    class Model:
        calls = 0
        async def screen_competition(self, candidate, sources):
            self.calls += 1
            assert DIRECTORY not in sources and official in sources
            return valid_report()
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML.replace("https://www.terravivacompetitions.com/tactical-urbanism-competition-2026/", official) if str(request.url) == DIRECTORY else next(iter(SOURCES.values())))
    async def check():
        model = Model()
        screener = CompetitionScreener(model, ("contestwatchers.com", "devpost.com"), transport=httpx.MockTransport(handler))
        result = await screener.screen(row())
        assert result.competition["decision"] == "eligible"
        assert model.calls == 1
    asyncio.run(check())
    assert requests == [DIRECTORY, official]


def test_navigation_footer_and_registration_buttons_do_not_become_official_rules():
    parser = PageText(base_url=DIRECTORY)
    parser.feed('<nav><a href="https://unrelated.test">Official Website</a></nav><footer><a href="https://footer.test">Official Website</a></footer><a href="https://register.test">Register now</a>')
    assert parser.official_links == []



def test_actual_campus_announcement_official_label_before_url_anchor_is_followed():
    parser = PageText(base_url="https://careercenter.ncu.edu.tw/news/show/3038")
    url = "https://contest.bhuntr.com/tw/bv0y72cyl602gt5zz4/home/"
    parser.feed('<p>詳細徵件辦法及投稿資訊可參考官方網站：<img src="icon.png"><a href="' + url + '">' + url + '</a></p>')
    assert parser.official_links == [url]
    parser.feed('<p><a href="https://unrelated.test">https://unrelated.test</a></p>')
    assert parser.official_links == [url]


def test_missing_dynamic_official_rules_do_not_spend_model_budget_on_parent_summary():
    campus = "https://school.edu.tw/news/3038"
    official = "https://contest.bhuntr.com/tw/event/home/"
    requests = []
    class Model:
        async def screen_competition(self, candidate, sources):
            raise AssertionError("Required official rules were not read")
    def handler(request):
        requests.append(str(request.url))
        body = ('<p>詳細徵件辦法及投稿資訊可參考官方網站：<a href="' + official + '">' + official + '</a></p>') if str(request.url) == campus else '<title>Event</title><div id="core-mount-point"></div><script src="app.js"></script>'
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)
    async def check():
        screener = CompetitionScreener(Model(), ("edu.tw", "bhuntr.com"), transport=httpx.MockTransport(handler))
        candidate = Candidate("campus", "office", campus, campus, "", "announcement:test")
        result = await screener.screen(candidate, model_budget=lambda: (_ for _ in ()).throw(AssertionError("Must not take model slot")))
        assert result.competition["verification_error"] == "official_content_unavailable"
        assert result.competition["decision"] == "pending"
        assert result.competition["sources"] == [campus]
        assert result.competition["fetch_report"][-1]["status"] == "dynamic_rules_unavailable"
        assert result.competition["fetch_report"][-1]["required_for_rules"]
    asyncio.run(check())
    assert requests == [campus, official]


def test_directory_official_pdf_handoff_remains_readable(monkeypatch):
    official = "https://sample.devpost.com/entry-rules.pdf"
    monkeypatch.setattr("app.competitions.pdf_text", lambda body: next(iter(SOURCES.values())))
    class Model:
        async def screen_competition(self, candidate, sources):
            assert list(sources) == [official]
            raw = valid_report()
            for fact in raw["facts"].values():fact["url"] = official
            return raw
    def handler(request):
        if str(request.url) == DIRECTORY:
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<a href="' + official + '">Download rules</a>')
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"controlled PDF adapter")
    async def check():
        screener = CompetitionScreener(Model(), ("contestwatchers.com", "devpost.com"), transport=httpx.MockTransport(handler))
        result = await screener.screen(row())
        assert result.competition["decision"] == "eligible"
        assert result.competition["fetch_report"][-1]["required_for_rules"]
    asyncio.run(check())


def test_actual_graphic_competitions_official_label_retains_decorative_arrow():
    parser = PageText(base_url="https://graphiccompetitions.com/example/")
    parser.feed('<a href="https://www.klphotoawards.com">Visit official website<span>↗</span></a>')
    assert parser.official_links == ["https://www.klphotoawards.com"]


def test_actual_mixed_event_catalogue_cannot_supply_a_different_contests_prize():
    url = 'https://curiousrefuge.com/ai-filmmaking-competitions'
    html = '<h2>AI Film Trailer Competition</h2><p>The winner takes home an Apple Vision Pro!</p><h2>Holiday Competition</h2><p>Earn cash prizes!</p>'
    class Model:
        async def screen_competition(self, candidate, sources):
            raise AssertionError('Do not mix rewards from different event cards')
    def handler(request):return httpx.Response(200, headers={'content-type':'text/html'}, text=html)
    async def check():
        screener = CompetitionScreener(Model(), ('curiousrefuge.com',), transport=httpx.MockTransport(handler))
        candidate = Candidate('catalogue', 'office', '2026 AI Holiday Film Competition ' + url, url, '', 'announcement:test')
        result = await screener.screen(candidate)
        assert result.competition['decision'] == 'pending'
        assert result.competition['sources'] == []
        assert any(r['status'] == 'event_specific_rules_required' for r in result.competition['fetch_report'])
        single = await screener.sources('https://curiousrefuge.com/ai-film-trailer-competition')
        assert single
    asyncio.run(check())


def test_reviewed_existing_candidate_gets_scoped_rules_despite_directory_failure(monkeypatch):
    from app import competitions
    official = next(iter(SOURCES))
    monkeypatch.setattr(competitions, 'VERIFIED_RULE_COMPANIONS', {DIRECTORY: ((official, 'AI'),)})
    class Model:
        calls = 0
        async def screen_competition(self, candidate, sources):
            self.calls += 1
            return valid_report()
    def handler(request):
        return httpx.Response(403 if str(request.url) == DIRECTORY else 200,
            headers={'content-type': 'text/html'}, text=next(iter(SOURCES.values())))
    async def check():
        model = Model()
        screener = CompetitionScreener(model, ('contestwatchers.com',), transport=httpx.MockTransport(handler))
        result = await screener.screen(row())
        assert result.competition['decision'] == 'eligible'
        assert model.calls == 1
        assert screener.hosts == ('contestwatchers.com',)
        assert competitions.verification_origin(DIRECTORY) == 'sample.devpost.com'
    asyncio.run(check())


def test_reviewed_rules_edition_mismatch_blocks_model(monkeypatch):
    from app import competitions
    official = next(iter(SOURCES))
    monkeypatch.setattr(competitions, 'VERIFIED_RULE_COMPANIONS', {DIRECTORY: ((official, 'Specific edition absent'),)})
    class Model:
        async def screen_competition(self, *args):
            raise AssertionError('Wrong edition must not be assessed')
    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=next(iter(SOURCES.values())))
    async def check():
        result = await CompetitionScreener(Model(), ('contestwatchers.com',), transport=httpx.MockTransport(handler)).screen(row())
        assert result.competition['decision'] == 'pending'
        assert any(r['status'] == 'event_scope_changed' for r in result.competition['fetch_report'])
    asyncio.run(check())


def test_ban_on_fully_ai_work_does_not_establish_ban_on_partial_ai():
    from app.competitions import evaluate
    url = 'https://chicagolatinofilmfestival.org/poster-contest-2'
    quote = 'Fully AI-produced works will not be considered.'
    for value in ('limited', 'prohibited'):
        result = evaluate({'facts': {'ai_policy': {'value': value, 'quote': quote, 'url': url}}}, {url: quote})
        assert result['facts']['ai_policy']['value'] == 'unknown'
        assert result['decision'] == 'pending'
