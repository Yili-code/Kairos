"""Official rules must be reachable through bounded public application pages."""
import asyncio
import httpx

from app.competitions import CompetitionScreener, MAX_RULE_DOCUMENTS


def test_follows_official_application_and_hyphenated_rules_without_submitting():
    requests = []
    pages = {
        '/aifilmchallenge': '<a href="https://info.akool.com/film-challenge-application">Submit your film</a>',
        '/film-challenge-application': '<a href="/film-challenge-rules-regulations?utm_source=chatgpt.com&amp;hsLang=en">Official rules</a>'
                                       '<form action="/submit" method="post"><button>Enter</button></form>',
        '/film-challenge-rules-regulations': 'Only premium accounts receive the bonus. You retain ownership.',
    }
    def handler(request):
        requests.append((request.method, str(request.url)))
        return httpx.Response(200, text=pages[request.url.path], headers={'Content-Type': 'text/html'})
    screener = CompetitionScreener(None, ('akool.com',), transport=httpx.MockTransport(handler))
    sources = asyncio.run(screener.sources('https://akool.com/aifilmchallenge'))
    assert 'https://info.akool.com/film-challenge-rules-regulations?hsLang=en' in sources
    assert len(requests) == 3
    assert all(method == 'GET' for method, _ in requests)


def test_hyphenated_navigation_preserves_host_and_document_limits():
    requests = []
    links = ''.join(f'<a href="/contest-{i}-rules">Rules</a>' for i in range(20))
    links += '<a href="https://untrusted.example/official-rules">Rules</a>'
    links += '<a href="http://127.0.0.1/official-rules">Rules</a>'
    links += '<a href="/official-rules?token=private&amp;utm_source=test">Rules</a>'
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=links, headers={'Content-Type': 'text/html'})
    screener = CompetitionScreener(None, ('akool.com',), transport=httpx.MockTransport(handler))
    sources = asyncio.run(screener.sources('https://akool.com/aifilmchallenge'))
    assert len(sources) == len(requests) == MAX_RULE_DOCUMENTS
    assert all(url.startswith('https://akool.com/') for url in requests)
    assert all('token=' not in url for url in requests)

