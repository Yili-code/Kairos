"""Bounded public announcement discovery, including small campus and foundation calls."""
from __future__ import annotations

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


CONTEST_TITLE = re.compile(r"競賽|比賽|徵件|徵選|徵稿|文學獎|作品募集|contest|competition|call for entr|open call|awards?|film festival|challenge", re.I)
ARTIFACT_TITLE = re.compile(r"\bAI\b|生成|短片|短影音|影片|影音|設計|海報|創意|徵文|寫作|文學|書法|插畫|漫畫|動畫|音樂|攝影|essay|writing|design|video|film|generative|poster|poetry|illustrat|animation|music|creative", re.I)
# Directory copy is a lead only; send organizer/platform links to the rules screener.
DIRECTORY_HOSTS = {"aifilmcontests.com"}


class AnnouncementLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.words: list[str] = []
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attributes = dict(attrs)
            self.href = attributes.get("href") or ""
            self.title = attributes.get("title") or ""
            self.words = []

    def handle_data(self, data):
        if self.href:
            self.words.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, normalize(" ".join(self.words)) or self.title))
            self.href = ""


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
        if not CONTEST_TITLE.search(title) or not ARTIFACT_TITLE.search(title):
            continue
        if re.search(r"得獎名單|獲獎名單|競賽結果|恭賀|頒獎典禮|圓滿落幕|評審肯定|成果報導|winners? announced|award winners", title, re.I):
            continue
        url = urljoin(base, href)
        if url.rstrip("/") == base.rstrip("/") or href.startswith("#"):
            continue
        if (urlsplit(url).hostname or "").removeprefix("www.") in DIRECTORY_HOSTS:
            continue
        if not allowed_url(url, hosts):
            continue
        candidate_id = "notice-" + hashlib.sha256(url.encode()).hexdigest()[:24]
        found[url] = Candidate(candidate_id, "public_announcement", title[:600] + "\n" + url,
                               url, "", "announcement:" + base, category="ai_competition")
    return list(found.values())[:20]


class AnnouncementSource:
    def __init__(self, urls: tuple[str, ...], hosts: tuple[str, ...], *, transport=None):
        self.urls = urls
        self.hosts = hosts
        self.transport = transport
        self.last_report: list[dict] = []

    async def discover(self) -> tuple[list[Candidate], int]:
        candidates, errors = {}, 0
        self.last_report = []
        batch_count = max(1, (len(self.urls) + 11) // 12)
        start = (int(time.time()) // 43200 % batch_count) * 12
        selected = self.urls[start:start + 12]
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False,
                                     transport=self.transport) as client:
            for url in selected:
                if not allowed_url(url, self.hosts):
                    errors += 1
                    self.last_report.append({"url": url, "status": "unsupported"})
                    continue
                page = await fetch_public(client, url, lambda target: allowed_url(target, self.hosts))
                if page.status != "ok" or "application/pdf" in page.content_type:
                    errors += 1
                    self.last_report.append({"url": url, "status": page.status, "attempts": page.attempts})
                    continue
                leads = entries(page.text(), page.url, self.hosts)
                self.last_report.append({"url": url, "resolved_url": page.url, "status": "ok",
                                         "leads": len(leads), "attempts": page.attempts})
                for candidate in leads:
                    candidates.setdefault(candidate.permalink, candidate)
        return list(candidates.values()), errors
