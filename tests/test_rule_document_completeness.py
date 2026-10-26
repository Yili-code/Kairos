import asyncio

import httpx

from app.competitions import CompetitionScreener, MAX_RULE_TEXT, MAX_TOTAL_RULE_TEXT, TRUNCATED_MARKER
from app.models import Candidate


def test_official_36k_rules_remain_complete_and_footer_does_not_pollute_review():
    calls = []
    body = "<nav><a href='https://info.devpost.com/about'>About</a></nav>"
    body += "<main>Official PayPal-style rules. " + "Full competition clause. " * 1500 + " Entrants keep ownership.</main>"
    body += "<footer><a href='https://info.devpost.com/legal/terms-of-service'>Terms</a></footer>"
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)
    screener = CompetitionScreener(None, ("devpost.com",), transport=httpx.MockTransport(response))
    sources = asyncio.run(screener.sources("https://sample.devpost.com/rules"))
    assert len(calls) == len(sources) == 1
    page = next(iter(sources.values()))
    assert "Entrants keep ownership." in page and TRUNCATED_MARKER not in page
    assert 32_000 < len(page) < MAX_RULE_TEXT


def test_explicit_competition_body_terms_still_followed_and_long_rules_stay_unverified():
    body = "<main>" + "Long official clause. " * 3000 + "<a href='/terms'>Contest terms</a></main>"
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)
    screener = CompetitionScreener(None, ("school.edu.tw",), transport=httpx.MockTransport(response))
    sources = asyncio.run(screener.sources("https://school.edu.tw/rules"))
    assert calls == ["https://school.edu.tw/rules", "https://school.edu.tw/terms"]
    assert all(TRUNCATED_MARKER in page for page in sources.values())


def test_javascript_shell_is_not_sent_to_paid_model_as_complete_rules():
    class Model:
        calls = 0
        async def screen_competition(self, candidate, sources):
            self.calls += 1
            raise AssertionError("No actual rules were retrieved")
    model = Model()
    def response(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
            text="<html><title>Festival rules</title><div id='root'></div><script src='/app.js'></script></html>")
    screener = CompetitionScreener(model, ("cuefilmfest.com",), transport=httpx.MockTransport(response))
    candidate = Candidate("cue", "office", "https://cuefilmfest.com/terms-and-conditions", "https://cuefilmfest.com", "", "announcement:test")
    asyncio.run(screener.screen(candidate))
    assert model.calls == 0 and candidate.competition["decision"] == "pending"
    assert candidate.competition["sources"] == []
    assert candidate.competition["fetch_report"][0]["status"] == "dynamic_rules_unavailable"


def test_total_text_budget_is_preserved_with_larger_individual_documents():
    def response(request):
        links = ''.join(f"<a href='/rules-{i}'>Rules</a>" for i in range(8))
        return httpx.Response(200, headers={"content-type": "text/html"}, text="A" * (MAX_RULE_TEXT + 10) + links)
    screener = CompetitionScreener(None, ("school.edu.tw",), transport=httpx.MockTransport(response))
    sources = asyncio.run(screener.sources("https://school.edu.tw/rules"))
    assert len(sources) <= 4
    assert sum(len(v.split(TRUNCATED_MARKER)[0].strip()) for v in sources.values()) <= MAX_TOTAL_RULE_TEXT
    assert screener.last_report[-1]["status"] == "text_budget_exhausted"


def test_official_rule_navigation_is_retained_while_navigation_copy_is_excluded():
    def response(request):
        if request.url.path == "/rules":
            body = "<nav>Navigation only<a href='/timeline'>Timeline</a><a href='/terms'>Terms</a></nav><main>Event rules</main>"
        else:
            body = "Official event deadline or ownership clause."
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)
    screener = CompetitionScreener(None, ("postmeaning.art",), transport=httpx.MockTransport(response))
    sources = asyncio.run(screener.sources("https://postmeaning.art/rules"))
    assert set(sources) == {"https://postmeaning.art/rules", "https://postmeaning.art/timeline", "https://postmeaning.art/terms"}
    assert "Navigation only" not in sources["https://postmeaning.art/rules"]
