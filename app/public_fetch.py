"""Bounded public-page retrieval with validated redirects and inspectable failures."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from app.discovery_feeds import devpost_listing_url
from app.economics import CBC_URL


class MetaRefresh(HTMLParser):
    """Read declarative navigation only; never evaluate scripts."""
    target: str | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag != 'meta' or (values.get('http-equiv') or '').lower() != 'refresh':
            return
        match = re.fullmatch(r"\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.+?)\s*", values.get('content') or '', re.I)
        if match and self.target is None:
            self.target = match[1].strip("\"'")


@dataclass
class PublicPage:
    url: str
    status: str
    body: bytes = b""
    content_type: str = ""
    encoding: str = "utf-8"
    attempts: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False
    retry_at: float | None = None

    def text(self) -> str:
        try:
            return self.body.decode(self.encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def retry_after(value: str, now: float) -> float:
    """Return an absolute operational cooldown, never a cached 429 response."""
    try:
        seconds = int(value)
        if seconds >= 0:
            return now + max(60, seconds)
    except (ValueError, OverflowError):
        pass
    try:
        closing = parsedate_to_datetime(value)
        if closing.tzinfo is None:
            closing = closing.replace(tzinfo=UTC)
        return max(now + 60, closing.timestamp())
    except (ValueError, TypeError, OverflowError):
        return now + 12 * 3600

async def fetch_public(client: httpx.AsyncClient, url: str, allowed, *, limit=1_000_000, pdf_limit=3_000_000, before_request=None) -> PublicPage:
    """At most three hops and one retry per hop; never follow an unchecked URL."""
    attempts = 0
    current = url
    for hop in range(3):
        if not allowed(current):
            return PublicPage(current, "unsupported", attempts=attempts)
        for retry in range(2):
            attempts += 1
            try:
                if before_request:
                    blocked = await before_request(current)
                    if blocked:
                        blocked.attempts = attempts - 1
                        return blocked
                async with client.stream("GET", current, headers={"User-Agent": "Kairos/0.3 public-contest-review"}) as response:
                    headers = {key: response.headers[key] for key in ('retry-after', 'cache-control', 'etag', 'last-modified') if key in response.headers}
                    if response.status_code == 429:
                        return PublicPage(current, 'http_429', attempts=attempts, headers=headers)
                    if response.status_code in {500, 502, 503, 504} and retry == 0:
                        await asyncio.sleep(0.25)
                        continue
                    if response.is_redirect:
                        target = urljoin(current, response.headers.get("location", ""))
                        if target == current or not allowed(target):
                            return PublicPage(current, "redirect_blocked", attempts=attempts)
                        current = target
                        break
                    if response.status_code != 200:
                        return PublicPage(current, f"http_{response.status_code}", attempts=attempts)
                    kind = response.headers.get("content-type", "").lower()
                    if not (any(item in kind for item in ("html", "xml", "rss", "atom", "application/pdf"))
                            or ("application/json" in kind and (devpost_listing_url(current) or current == CBC_URL))):
                        return PublicPage(current, "unsupported_content", attempts=attempts)
                    body = bytearray()
                    effective_limit = pdf_limit if "application/pdf" in kind else limit
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > effective_limit:
                            return PublicPage(current, "too_large", attempts=attempts)
                    page = PublicPage(current, "ok" if body else "empty", bytes(body), kind,
                                      response.encoding or "utf-8", attempts, headers)
                    if 'html' in kind:
                        navigation = MetaRefresh()
                        try:
                            navigation.feed(page.text())
                        except (ValueError, AssertionError):
                            return PublicPage(current, 'malformed_html', attempts=attempts)
                        if navigation.target:
                            target = urljoin(current, navigation.target)
                            if target == current or not allowed(target):
                                return PublicPage(current, 'redirect_blocked', attempts=attempts)
                            current = target
                            break
                    return page
            except (httpx.TimeoutException, httpx.NetworkError):
                if retry == 0:
                    continue
                return PublicPage(current, "network_error", attempts=attempts)
            except (httpx.HTTPError, ValueError):
                return PublicPage(current, "transport_error", attempts=attempts)
        else:
            return PublicPage(current, "retry_exhausted", attempts=attempts)
    return PublicPage(current, "redirect_limit", attempts=attempts)
