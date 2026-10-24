"""Bounded public announcement discovery, including small campus and foundation calls."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.parse import urlsplit

import httpx

from app.competitions import allowed_url, normalize
from app.models import Candidate
from app.public_fetch import fetch_public


CONTEST_TITLE = re.compile(r"競賽|比賽|徵件|徵選|徵稿|文學獎|作品募集|挑戰賽|contest|competition|call for entr|open call|prizes?|awards?|film festival|challenge", re.I)
SPORT_TITLE = re.compile(r"籃球|排球|羽球|桌球|棒球|足球|游泳|田徑|馬拉松|basketball|volleyball|marathon", re.I)
NON_ENTRY_TITLE = re.compile(r"學術期刊|學報|論叢|合唱比賽|call for papers|journal submissions", re.I)
MAX_BOARDS = 24
MAX_LISTING_PAGES = 2
DISCOVERY_TIMEOUT = 60.0
# Directory copy is a lead only; send organizer/platform links to the rules screener.
DIRECTORY_HOSTS = {"aifilmcontests.com"}


class AnnouncementLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.words: list[str] = []
        self.title = ""
        self.image_title = ""
        self.next_links: list[str] = []
        self.is_next = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and "next" in (attributes.get("rel") or "").split():
            self.next_links.append(attributes.get("href") or "")
        if tag == "a":
            self.href = attributes.get("href") or ""
            self.title = attributes.get("title") or ""
            self.words = []
            self.image_title = ""
            self.is_next = "next" in (attributes.get("rel") or "").split()
        elif tag == "img" and self.href and attributes.get("alt"):
            self.image_title = attributes["alt"]

    def handle_data(self, data):
        if self.href:
            self.words.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            label = normalize(" ".join(self.words)) or self.title or self.image_title
            self.links.append((self.href, label))
            if self.is_next or re.fullmatch(r"下一頁|下頁|Next(?: page)?|[›»]", label, re.I):
                self.next_links.append(self.href)
            self.href = ""


def next_listing(body: str, base: str, hosts: tuple[str, ...]) -> str | None:
    parser = AnnouncementLinks()
    parser.feed(body)
    for href in parser.next_links:
        try:
            url = urljoin(base, href)
        except ValueError:
            continue
        if not allowed_url(url, hosts):
            continue
        if url != base and urlsplit(url).hostname == urlsplit(base).hostname and allowed_url(url, hosts):
            return url
    return None


def entries(body: str, base: str, hosts: tuple[str, ...]) -> list[Candidate]:
    parser = AnnouncementLinks()
    parser.feed(body)
    links = parser.links
    # RSS/Atom are optional sources under the same bounded, public-only fetch policy.
    if body.lstrip().startswith("<?xml") or body.lstrip().startswith(("<rss", "<feed")):
        try:
            root = ET.fromstring(body)
            for item in root.findall(".//item"):
                links.append((item.findtext("link", ""), item.findtext("title", "")))
            for item in root.findall("{http://www.w3.org/2005/Atom}entry"):
                link = item.find("{http://www.w3.org/2005/Atom}link")
                if link is not None:
                    links.append((link.get("href", ""), item.findtext("{http://www.w3.org/2005/Atom}title", "")))
        except ET.ParseError:
            pass
    found = {}
    for href, title in links:
        # A generic call may accept proposals, data or software without naming an artifact.
        # Discovery is deliberately broad; official rules still determine eligibility.
        if not CONTEST_TITLE.search(title) or SPORT_TITLE.search(title) or NON_ENTRY_TITLE.search(title):
            continue
        if re.search(r"得獎名單|獲獎名單|競賽結果|恭賀|頒獎典禮|圓滿落幕|評審肯定|成果報導|winners? announced|award winners|award-winning", title, re.I):
            continue
        try:
            url = urljoin(base, href)
        except ValueError:
            continue
        if not allowed_url(url, hosts):
            continue
        path = urlsplit(url).path.rstrip('/').lower()
        if (urlsplit(url).hostname or '').removeprefix('www.') in {'contestwatchers.com', 'graphiccompetitions.com'} and (
            path in {'', '/about', '/archive', '/latest-contests', '/suggest-contest', '/submit-contest', '/how-to-organize-successful-international-contests'}
            or path.startswith(('/category/', '/tag/', '/page/'))
        ):
            continue
        if re.fullmatch(r"(?:交流)?競賽(?:[&／/]獎勵)?|比賽|徵件|contests?|competitions?|awards?", title, re.I):
            continue
        if url.rstrip("/") == base.rstrip("/") or href.startswith("#"):
            continue
        if (urlsplit(url).hostname or "").removeprefix("www.") in DIRECTORY_HOSTS:
            continue
        candidate_id = "notice-" + hashlib.sha256(url.encode()).hexdigest()[:24]
        if url not in found or len(title) > len(found[url].text.splitlines()[0]):
            found[url] = Candidate(candidate_id, "public_announcement", title[:600] + "\n" + url,
                                  url, "", "announcement:" + base, category="ai_competition")
    return list(found.values())[:20]


class AnnouncementSource:
    def __init__(self, urls: tuple[str, ...], hosts: tuple[str, ...], *, transport=None, seed_pages=()):
        self.urls = urls
        self.hosts = hosts
        self.transport = transport
        self.seed_pages = seed_pages
        self.last_report: list[dict] = []

    async def discover(self) -> tuple[list[Candidate], int]:
        candidates, errors = {}, 0
        for title, url in self.seed_pages:
            if allowed_url(url, self.hosts):
                candidate_id = 'notice-' + hashlib.sha256(url.encode()).hexdigest()[:24]
                candidates[url] = Candidate(candidate_id, 'curated_public_source', title + '\n' + url,
                                            url, '', 'announcement:curated', category='ai_competition')
        self.last_report = []
        urls = tuple(dict.fromkeys(self.urls))
        batch_count = max(1, (len(urls) + MAX_BOARDS - 1) // MAX_BOARDS)
        start = (int(time.time()) // 43200 % batch_count) * MAX_BOARDS
        selected = urls[start:start + MAX_BOARDS]
        semaphore = asyncio.Semaphore(4)

        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False,
                                     transport=self.transport) as client:
            async def board(base):
                rows, receipts = {}, []
                current, visited = base, set()
                try:
                    async with asyncio.timeout(DISCOVERY_TIMEOUT):
                        async with semaphore:
                            for _ in range(MAX_LISTING_PAGES):
                                if current in visited:
                                    break
                                visited.add(current)
                                page = await fetch_public(client, current, lambda target: allowed_url(target, self.hosts))
                                status = 'unsupported_content' if page.status == 'ok' and 'application/pdf' in page.content_type else page.status
                                receipt = {"url": current, "board": base, "status": status, "attempts": page.attempts}
                                receipts.append(receipt)
                                if status != 'ok':
                                    break
                                leads = entries(page.text(), page.url, self.hosts)
                                receipt.update(resolved_url=page.url, leads=len(leads))
                                for candidate in leads:
                                    rows.setdefault(candidate.permalink, candidate)
                                current = next_listing(page.text(), page.url, self.hosts)
                                if not current:
                                    break
                except TimeoutError:
                    receipts.append({"url": current or base, "board": base, "status": "discovery_timeout"})
                except (ValueError, AssertionError):
                    receipts.append({"url": current or base, "board": base, "status": "parse_error"})
                return list(rows.values()), receipts

            for rows, receipts in await asyncio.gather(*(board(url) for url in selected)):
                self.last_report.extend(receipts)
                errors += sum(row['status'] != 'ok' for row in receipts)
                for candidate in rows:
                    candidates.setdefault(candidate.permalink, candidate)
        return list(candidates.values()), errors
