"""Bounded public announcement discovery, including small campus and foundation calls."""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import logging
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
NON_ENTRY_TITLE = re.compile(r"(?:期刊|學刊|季刊|學報|論叢|論衡|評論|專刊|叢刊|學誌|研究[》」]).*徵稿|學術期刊|合唱比賽|call for papers|journal submissions", re.I)
RECAP_TITLE = re.compile(r"得獎名單|獲獎名單|競賽結果|恭賀|頒獎典禮|圓滿落幕|評審肯定|成果報導|winners? announced|award winners|award-winning|獲.{0,35}(?:挑戰賽|競賽|比賽).{0,8}獎|\d+位.{0,12}高手集結", re.I)
MAX_BOARDS = 24
MAX_LISTING_PAGES = 2
DISCOVERY_TIMEOUT = 60.0
# Directory copy is a lead only; send organizer/platform links to the rules screener.
DIRECTORY_HOSTS = {"aifilmcontests.com"}
LOGGER = logging.getLogger(__name__)


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
        self.hidden = 0
        self.visible: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {'script','style','noscript'}:
            self.hidden += 1
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
        if not self.hidden:
            self.visible.append(data)
        if self.href and not self.hidden:
            self.words.append(data)

    def handle_endtag(self, tag):
        if tag in {'script','style','noscript'} and self.hidden:
            self.hidden -= 1
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


def entries(body: str, base: str, hosts: tuple[str, ...], *, diagnostics=None) -> list[Candidate]:
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
            raise ValueError('Malformed announcement feed') from None
    counts = Counter()
    contest_titles = 0
    found = {}
    for href, title in links:
        # A generic call may accept proposals, data or software without naming an artifact.
        # Discovery is deliberately broad; official rules still determine eligibility.
        if not CONTEST_TITLE.search(title):
            continue
        contest_titles += 1
        if title.lower().startswith('image source:'):
            counts['image_credit'] += 1
            continue
        if SPORT_TITLE.search(title) or (NON_ENTRY_TITLE.search(title) and not re.search(r'競賽|獎金|文學獎', title)):
            counts['not_entry_call'] += 1
            continue
        if RECAP_TITLE.search(title):
            counts['recap'] += 1
            continue
        try:
            url = urljoin(base, href)
        except ValueError:
            counts['malformed_url'] += 1
            continue
        if not allowed_url(url, hosts):
            counts['unsupported_url'] += 1
            continue
        path = urlsplit(url).path.rstrip('/').lower()
        if (urlsplit(url).hostname or '').removeprefix('www.') == 'curiousrefuge.com' and path == '/ai-filmmaking-competitions':
            # This is a multi-event archive, not the individual event claimed by a directory.
            counts['directory_target'] += 1
            continue
        if (urlsplit(url).hostname or '').removeprefix('www.') in {'contestwatchers.com', 'graphiccompetitions.com'} and (
            path in {'', '/about', '/archive', '/latest-contests', '/suggest-contest', '/submit-contest', '/how-to-organize-successful-international-contests'}
            or path.startswith(('/category/', '/tag/', '/page/'))
        ):
            counts['directory_navigation'] += 1
            continue
        if re.fullmatch(r"(?:交流)?競賽(?:[&／/]獎勵)?|比賽|徵件|contests?|competitions?|awards?", title, re.I):
            counts['generic_navigation'] += 1
            continue
        if url.rstrip("/") == base.rstrip("/") or href.startswith("#"):
            counts['self_navigation'] += 1
            continue
        if (urlsplit(url).hostname or "").removeprefix("www.") in DIRECTORY_HOSTS:
            counts['directory_navigation'] += 1
            continue
        candidate_id = "notice-" + hashlib.sha256(url.encode()).hexdigest()[:24]
        if url in found:
            counts['duplicate_link'] += 1
        if url not in found or len(title) > len(found[url].text.splitlines()[0]):
            found[url] = Candidate(candidate_id, "public_announcement", title[:600] + "\n" + url,
                                  url, "", "announcement:" + base, category="ai_competition")
    rows = list(found.values())[:20]
    if diagnostics is not None:
        if rows:
            status = 'leads_found'
        elif contest_titles:
            status = 'filtered_out'
        elif re.search(r'目前無公告|暫無公告|尚無公告|no announcements|no results found', ' '.join(parser.visible), re.I):
            status = 'no_announcements'
        elif '<script' in body.lower() and re.search(r'''<(?:div|main)[^>]*id=["'](?:app|root|main|__next)["'][^>]*>\s*</''',body,re.I):
            status = 'unreadable_or_dynamic'
        elif not links:
            status = 'unreadable_or_dynamic' if '<script' in body.lower() else 'no_public_links'
        else:
            status = 'no_matching_titles'
        diagnostics.update(parse_status=status, link_count=len(links), contest_titles=contest_titles,
                           excluded=dict(counts), truncated_leads=max(0, len(found)-len(rows)))
    return rows


class AnnouncementSource:
    def __init__(self, urls: tuple[str, ...], hosts: tuple[str, ...], *, transport=None, seed_pages=(), fetcher=None):
        self.urls = urls
        self.hosts = hosts
        self.transport = transport
        self.seed_pages = seed_pages
        self.fetcher = fetcher or fetch_public
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
                                page = await self.fetcher(client, current, lambda target: allowed_url(target, self.hosts))
                                status = 'unsupported_content' if page.status == 'ok' and 'application/pdf' in page.content_type else page.status
                                receipt = {"url": current, "board": base, "status": status, "attempts": page.attempts, "from_cache": page.from_cache, "retry_at": page.retry_at}
                                receipts.append(receipt)
                                if status != 'ok':
                                    break
                                details = {}
                                try:
                                    leads = entries(page.text(), page.url, self.hosts, diagnostics=details)
                                except (ValueError, AssertionError):
                                    receipt['status'] = 'parse_error'
                                    break
                                receipt.update(details)
                                receipt.update(resolved_url=page.url, leads=len(leads))
                                for candidate in leads:
                                    rows.setdefault(candidate.permalink, candidate)
                                current = next_listing(page.text(), page.url, self.hosts)
                                if not current:
                                    break
                except TimeoutError:
                    receipts.append({"url": current or base, "board": base, "status": "discovery_timeout"})
                except Exception:
                    receipts.append({"url": current or base, "board": base, "status": "source_exception"})
                return list(rows.values()), receipts

            for rows, receipts in await asyncio.gather(*(board(url) for url in selected)):
                self.last_report.extend(receipts)
                errors += sum(row['status'] != 'ok' for row in receipts)
                for receipt in receipts:
                    if receipt['status'] != 'ok' or receipt.get('parse_status') == 'unreadable_or_dynamic':
                        LOGGER.warning('public_discovery_issue host=%s status=%s parse_status=%s',
                                       urlsplit(receipt['url']).hostname, receipt['status'], receipt.get('parse_status','not_parsed'))
                for candidate in rows:
                    candidates.setdefault(candidate.permalink, candidate)
        return list(candidates.values()), errors
