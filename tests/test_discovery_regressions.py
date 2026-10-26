"""Observed public-source misses; discovery is not a qualification assertion."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.announcements import AnnouncementSource, entries
from app.competitions import allowed_url
from app.config import DEFAULT_RULES_HOSTS
from app.discovery_feeds import DEVPOST_LIST, devpost_next_page

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def test_real_devpost_listing_includes_paypal_and_titles_without_contest_words():
    rows = entries((FIXTURES / "devpost-open.json").read_text(), DEVPOST_LIST, DEFAULT_RULES_HOSTS)
    assert {r.permalink for r in rows} == {
        "https://paypalaihackathon.devpost.com/", "https://code-for-humanity.devpost.com/",
        "https://nebiusglobalaihackathon.devpost.com/"}
    assert all(r.competition == {} for r in rows)


def test_real_epic_atom_feed_and_film_fest_caption_recover_observed_misses():
    rows = entries((FIXTURES / "epic-feed.xml").read_text(), "https://www.unrealengine.com/en-US/rss", DEFAULT_RULES_HOSTS)
    assert [r.permalink for r in rows] == ["https://www.unrealengine.com/news/2026-epic-ai-megajam"]
    details = {}
    rows = entries((FIXTURES / "film-directory.html").read_text(encoding="utf-8"),
                   "https://aifilmcontests.com/", DEFAULT_RULES_HOSTS, diagnostics=details)
    assert [r.permalink for r in rows] == ["https://cuefilmfest.com"]
    # The news link is not an official rule page; do not pretend this gap is repaired.
    assert not any("naver" in r.permalink for r in rows)


def test_listing_endpoint_allows_only_exact_read_only_public_query():
    assert allowed_url(DEVPOST_LIST, DEFAULT_RULES_HOSTS)
    for url in [DEVPOST_LIST + "&token=secret", DEVPOST_LIST + "&page=2",
                DEVPOST_LIST.replace("status%5B%5D=open", "status%5B%5D=closed"),
                DEVPOST_LIST.replace("per_page=20", "per_page=1000"),
                DEVPOST_LIST.replace("page=1", "page=1001"),
                DEVPOST_LIST.replace("devpost.com/", "devpost.com.evil.test/"),
                DEVPOST_LIST.replace("https://", "https://user:secret@"),
                DEVPOST_LIST.replace("/api/hackathons", "/api/delete")]:
        assert not allowed_url(url, DEFAULT_RULES_HOSTS), url


def test_listing_pagination_reads_first_page_then_rotates_without_unbounded_crawl():
    body = (FIXTURES / "devpost-open.json").read_text()
    second = devpost_next_page(body, DEVPOST_LIST, 0)
    third = devpost_next_page(body, DEVPOST_LIST, 1)
    assert second.endswith("page=2") and third.endswith("page=3")
    assert devpost_next_page(body, second, 1) is None
    assert devpost_next_page(body, DEVPOST_LIST, 2) == second


def test_malformed_listing_is_visible_and_does_not_hide_healthy_feed():
    async def check():
        def response(request):
            if request.url.host == "devpost.com":
                return httpx.Response(200, headers={"content-type": "application/json"}, json={"hackathons": "wrong"})
            return httpx.Response(200, headers={"content-type": "application/atom+xml"},
                                  text=(FIXTURES / "epic-feed.xml").read_text())
        source = AnnouncementSource((DEVPOST_LIST, "https://www.unrealengine.com/en-US/rss"),
                                    DEFAULT_RULES_HOSTS, transport=httpx.MockTransport(response))
        rows, errors = await source.discover()
        assert len(rows) == 1 and errors == 1
        assert source.last_report[0]["status"] == "parse_error"
    asyncio.run(check())


def test_new_listing_retains_six_document_and_two_listing_page_limits():
    calls = []
    async def check():
        def response(request):
            calls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  text=(FIXTURES / "devpost-open.json").read_text())
        source = AnnouncementSource((DEVPOST_LIST,), DEFAULT_RULES_HOSTS, transport=httpx.MockTransport(response))
        rows, errors = await source.discover()
        assert len(rows) == 3 and errors == 0
        assert all(not row.competition for row in rows)
        assert len(calls) == 2
        assert source.last_report[0]["listing_total"] == 52
    asyncio.run(check())


def test_valid_feed_with_browser_script_trailer_is_read_without_executing_it():
    body = (FIXTURES / "epic-feed.xml").read_text() + "<script>throw new Error('never execute');</script>"
    rows = entries(body, "https://www.unrealengine.com/en-US/rss", DEFAULT_RULES_HOSTS)
    assert len(rows) == 1 and "MegaJam" in rows[0].text
    for bad in [body + "<div>not a feed</div>", "<feed>broken</feed><script>ignored</script>"]:
        if "broken" in bad:
            bad = bad.replace("broken", "<unclosed>")
        with pytest.raises(ValueError, match="Malformed announcement feed"):
            entries(bad, "https://www.unrealengine.com/en-US/rss", DEFAULT_RULES_HOSTS)
