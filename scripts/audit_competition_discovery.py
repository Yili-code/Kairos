"""Read-only public listing audit: no model, storage, Telegram or organizer email calls."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.announcements import AnnouncementSource, MAX_BOARDS
from app.config import Settings
from app.fetch_policy import PublicFetcher


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
            'unique_leads': len(candidates),
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'eligibility_assessed': False,
        },
        'receipts': receipts,
        'leads': [{'title': row.text.splitlines()[0], 'url': row.permalink,
                   'discovered_from': row.search_term} for row in candidates.values()],
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
