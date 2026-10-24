"""Read-only public listing audit: no model, storage, Telegram or organizer email calls."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import re
from datetime import datetime, UTC
from pathlib import Path
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.announcements import AnnouncementSource, MAX_BOARDS
from app.config import Settings
from app.fetch_policy import PublicFetcher


def lead_quality(rows):
    """Flags are review hints, never sourced eligibility decisions or identity merges."""
    year = datetime.now(UTC).year
    groups, urls_by_identity, stale = {}, {}, []
    for row in rows:
        title, url = row['title'], row['url']
        years = [int(value) for value in re.findall(r'(?<!\d)(20\d{2})(?!\d)', title)]
        if years and max(years) < year:
            stale.append(url)
        quoted = re.findall(r'[「《](.{8,}?)[」》]', title)
        name = max(quoted, key=len) if quoted else re.sub(r'【[^】]*】', '', title)
        name = re.sub(r'[^\w]', '', name).casefold()
        groups.setdefault(name, []).append(url)
        parsed = urlsplit(str(httpx.URL(url)))
        identity = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(parse_qsl(parsed.query))), ''))
        urls_by_identity.setdefault(identity, []).append(url)
    return {
        'older_year_title_urls': stale,
        'possible_same_event_groups': [urls for name, urls in groups.items() if name and len(urls) > 1],
        'equivalent_url_groups': [urls for urls in urls_by_identity.values() if len(urls)>1],
        'all_leads_require_assessment': True,
    }


async def audit() -> dict:
    settings = Settings.from_env(require_secrets=False)
    urls = tuple(dict.fromkeys(settings.announcement_source_urls))
    started = time.monotonic()
    candidates, receipts = {}, []
    fetcher = PublicFetcher()
    for offset in range(0, len(urls), MAX_BOARDS):
        source = AnnouncementSource(urls[offset:offset + MAX_BOARDS], settings.competition_rules_hosts, fetcher=fetcher)
        rows, _ = await source.discover()
        receipts.extend(source.last_report)
        for candidate in rows:
            candidates.setdefault(candidate.permalink, candidate)
    return {
        'summary': {
            'configured_boards': len(urls),
            'pages_attempted': len(receipts),
            'statuses': dict(Counter(row['status'] for row in receipts)),
            'parse_statuses': dict(Counter(row.get('parse_status','not_parsed') for row in receipts)),
            'http_requests': sum(row.get('attempts',0) for row in receipts),
            'cache_hits': sum(row.get('from_cache',False) for row in receipts),
            'unique_leads': len(candidates),
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'eligibility_assessed': False,
        },
        'receipts': receipts,
        'leads': [{'title': row.text.splitlines()[0], 'url': row.permalink,
                   'discovered_from': row.search_term} for row in candidates.values()],
        'quality_flags': lead_quality([{'title':row.text.splitlines()[0], 'url':row.permalink} for row in candidates.values()]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('work/discovery-audit.json'))
    args = parser.parse_args()
    report = asyncio.run(audit())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=True))


if __name__ == '__main__':
    main()
