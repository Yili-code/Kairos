"""Bounded public-page retrieval with validated redirects and inspectable failures."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


@dataclass
class PublicPage:
    url: str
    status: str
    body: bytes = b""
    content_type: str = ""
    encoding: str = "utf-8"
    attempts: int = 0

    def text(self) -> str:
        try:
            return self.body.decode(self.encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


async def fetch_public(client: httpx.AsyncClient, url: str, allowed, *, limit=1_000_000, pdf_limit=3_000_000) -> PublicPage:
    """At most three hops and one retry per hop; never follow an unchecked URL."""
    attempts = 0
    current = url
    for hop in range(3):
        if not allowed(current):
            return PublicPage(current, "unsupported", attempts=attempts)
        for retry in range(2):
            attempts += 1
            try:
                async with client.stream("GET", current, headers={"User-Agent": "Kairos/0.3 public-contest-review"}) as response:
                    if response.status_code in {429, 500, 502, 503, 504} and retry == 0:
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
                    if not any(item in kind for item in ("html", "xml", "rss", "atom", "application/pdf")):
                        return PublicPage(current, "unsupported_content", attempts=attempts)
                    body = bytearray()
                    effective_limit = pdf_limit if "application/pdf" in kind else limit
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > effective_limit:
                            return PublicPage(current, "too_large", attempts=attempts)
                    return PublicPage(current, "ok" if body else "empty", bytes(body), kind,
                                      response.encoding or "utf-8", attempts)
            except (httpx.TimeoutException, httpx.NetworkError):
                if retry == 0:
                    continue
                return PublicPage(current, "network_error", attempts=attempts)
            except (httpx.HTTPError, ValueError):
                return PublicPage(current, "transport_error", attempts=attempts)
        else:
            return PublicPage(current, "retry_exhausted", attempts=attempts)
    return PublicPage(current, "redirect_limit", attempts=attempts)
