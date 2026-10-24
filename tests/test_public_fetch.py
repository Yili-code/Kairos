import asyncio
import httpx

from app.competitions import allowed_url
from app.public_fetch import fetch_public


def fetch(handler, url='https://campus.edu.tw/start'):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public(client, url, lambda target: allowed_url(target, ('edu.tw',)))
    return asyncio.run(run())


def test_safe_redirect_uses_final_url_and_declared_encoding():
    def handler(request):
        if request.url.path == '/start':
            return httpx.Response(301, headers={'location': '/rules'})
        return httpx.Response(200, headers={'content-type': 'text/html; charset=big5'}, content='競賽規則'.encode('big5'))
    page = fetch(handler)
    assert page.url == 'https://campus.edu.tw/rules'
    assert page.text() == '競賽規則' and page.attempts == 2


def test_unsafe_redirect_never_reaches_private_destination():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    assert fetch(handler).status == 'redirect_blocked'
    assert len(calls) == 1


def test_transient_failure_retries_but_permanent_failure_does_not():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, headers={'content-type': 'text/html'}, text='Rules')
    assert fetch(handler).status == 'ok' and len(calls) == 2
    assert fetch(lambda _: httpx.Response(403)).attempts == 1


def test_redirect_loop_has_a_hard_hop_limit():
    page = fetch(lambda request: httpx.Response(302, headers={'location': str(request.url) + 'x'}))
    assert page.status == 'redirect_limit' and page.attempts == 3


def test_campus_meta_refresh_resolves_relative_public_listing():
    def handler(request):
        if request.url.path == '/start':
            return httpx.Response(200,headers={'content-type':'text/html'},text='<meta http-equiv="refresh" content="0; url=web/index.jsp">')
        return httpx.Response(200,headers={'content-type':'text/html'},text='Actual contest listing')
    page = fetch(handler)
    assert page.url == 'https://campus.edu.tw/web/index.jsp'
    assert page.text() == 'Actual contest listing' and page.attempts == 2


def test_meta_refresh_cannot_bypass_redirect_validation_or_hop_limit():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,headers={'content-type':'text/html'},text='<meta http-equiv="refresh" content="0; url=http://127.0.0.1/private">')
    assert fetch(handler).status == 'redirect_blocked' and len(calls) == 1
    page = fetch(lambda r:httpx.Response(200,headers={'content-type':'text/html'},text='<meta http-equiv="refresh" content="0; url='+str(r.url)+'x">'))
    assert page.status == 'redirect_limit' and page.attempts == 3


def test_unknown_charset_and_malformed_html_do_not_crash_the_fetch_batch():
    page = fetch(lambda _:httpx.Response(200,headers={'content-type':'text/html; charset=not-a-codec'},content=b'<p>Rules</p>'))
    assert page.status == 'ok' and page.text() == '<p>Rules</p>'
    page = fetch(lambda _:httpx.Response(200,headers={'content-type':'text/html'},text='<![invalid]>'))
    assert page.status == 'malformed_html'
