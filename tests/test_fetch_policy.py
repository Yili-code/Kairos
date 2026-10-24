import asyncio
from email.utils import formatdate

import httpx

from app.fetch_policy import MemoryFetchState, PublicFetcher, key
from app.public_fetch import fetch_public, retry_after


URL = 'https://campus.edu.tw/notices'
ALLOWED = lambda url: url.startswith('https://campus.edu.tw/')


def test_429_is_not_retried_and_retry_after_is_preserved():
    async def run():
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(429, headers={'Retry-After': '7200'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            page = await fetch_public(client, URL, ALLOWED)
        assert page.status == 'http_429' and page.attempts == len(calls) == 1
        assert page.headers['retry-after'] == '7200'
    asyncio.run(run())


def test_cooldown_survives_new_fetcher_instances_and_does_not_cache_429_bodies():
    async def run():
        state, calls = MemoryFetchState(), []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(429,headers={'retry-after':'7200'},text='Not a contest')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await PublicFetcher(state,clock=lambda:1000,spacing=0)(client,URL,ALLOWED)
            second = await PublicFetcher(state,clock=lambda:1001,spacing=0)(client,URL+'/other',ALLOWED)
        assert first.retry_at == 8200
        assert second.status == 'cooldown' and second.attempts == 0 and len(calls) == 1
        assert not any(name.startswith('page-') for name in state.rows)
    asyncio.run(run())


def test_retry_after_handles_http_dates_and_invalid_headers_conservatively():
    assert retry_after(formatdate(9000,usegmt=True),1000) == 9000
    assert retry_after('',1000) == 1000+43200
    assert retry_after('-1',1000) == 1000+43200
    assert retry_after('0',1000) == 1060


def test_public_success_is_reused_but_private_or_uncacheable_pages_are_not():
    async def run(control):
        state, calls = MemoryFetchState(), []
        def handler(request):
            calls.append(request)
            return httpx.Response(200,headers={'content-type':'text/html','cache-control':control},text='Contest')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = PublicFetcher(state,clock=lambda:1000,spacing=0)
            await fetcher(client,URL,ALLOWED)
            second = await fetcher(client,URL,ALLOWED)
        return len(calls), second
    calls,page = asyncio.run(run('public, max-age=300'))
    assert calls == 1 and page.from_cache and page.attempts == 0
    for control in ['private, max-age=600','no-cache','no-store','max-age=0']:
        calls,page = asyncio.run(run(control))
        assert calls == 2 and not page.from_cache


def test_origin_lease_prevents_overlapping_workers_from_hitting_same_site():
    async def run():
        state, entered, finish = MemoryFetchState(), asyncio.Event(), asyncio.Event()
        async def handler(request):
            entered.set()
            await finish.wait()
            return httpx.Response(200,headers={'content-type':'text/html'},text='Contest')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = asyncio.create_task(PublicFetcher(state,spacing=0)(client,URL,ALLOWED))
            await entered.wait()
            second = await PublicFetcher(state,spacing=0)(client,URL+'/next',ALLOWED)
            finish.set()
            await first
        assert second.status == 'source_busy' and second.attempts == 0
    asyncio.run(run())


def test_redirect_target_obeys_its_own_cooldown_before_any_request():
    async def run():
        state,calls=MemoryFetchState(),[]
        state.rows[key('origin','other.edu.tw')]={'retry_at':9000}
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302,headers={'location':'https://other.edu.tw/rules'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            page=await PublicFetcher(state,clock=lambda:1000,spacing=0)(client,URL,lambda _:True)
        assert page.status == 'cooldown' and len(calls)==1
    asyncio.run(run())


def test_state_failure_does_not_bypass_rate_limit_protection():
    class FailedState(MemoryFetchState):
        async def get(self,name):
            raise RuntimeError('Unavailable')
    async def run():
        def handler(request):
            raise AssertionError('No HTTP request should be attempted')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await PublicFetcher(FailedState())(client,URL,ALLOWED)
    assert asyncio.run(run()).status == 'fetch_state_unavailable'


def test_expired_cooldown_and_expired_cache_allow_a_fresh_request():
    async def run():
        state,now,calls = MemoryFetchState(), [1000], []
        def handler(request):
            calls.append(request)
            if len(calls)==1:
                return httpx.Response(429,headers={'retry-after':'60'})
            return httpx.Response(200,headers={'content-type':'text/html','cache-control':'public,max-age=10'},text='Fresh rules')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher=PublicFetcher(state,clock=lambda:now[0],spacing=0)
            await fetcher(client,URL,ALLOWED)
            now[0]=1061
            assert (await fetcher(client,URL,ALLOWED)).status=='ok'
            now[0]=1062
            assert (await fetcher(client,URL,ALLOWED)).from_cache
            now[0]=1072
            assert not (await fetcher(client,URL,ALLOWED)).from_cache
        assert len(calls)==3
    asyncio.run(run())


def test_separate_requests_to_one_origin_are_paced_even_after_lease_release():
    import time
    async def run():
        calls=[]
        def handler(request):
            calls.append(time.monotonic())
            return httpx.Response(200,headers={'content-type':'text/html','cache-control':'no-store'},text='Rules')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher=PublicFetcher(spacing=.02)
            await fetcher(client,URL,ALLOWED)
            await fetcher(client,URL+'/next',ALLOWED)
        assert len(calls)==2 and calls[1]-calls[0]>=.018
    asyncio.run(run())


def test_fresh_rule_review_bypasses_success_cache_but_not_cooldown():
    async def run():
        state,calls=MemoryFetchState(),[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,headers={'content-type':'text/html'},text='Version '+str(len(calls)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher=PublicFetcher(state,clock=lambda:1000,spacing=0)
            await fetcher(client,URL,ALLOWED)
            assert (await fetcher(client,URL,ALLOWED)).text()=='Version 1'
            assert (await fetcher.fresh(client,URL,ALLOWED)).text()=='Version 2'
            state.rows[key('origin','campus.edu.tw')]={'retry_at':2000}
            assert (await fetcher.fresh(client,URL,ALLOWED)).status=='cooldown'
        assert len(calls)==2
    asyncio.run(run())
