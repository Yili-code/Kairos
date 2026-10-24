"""Read-only live round audit; existing provider access, no Telegram or Firestore writes."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.announcements import AnnouncementSource
from app.competitions import CompetitionScreener
from app.config import DEFAULT_ANNOUNCEMENT_URLS, DEFAULT_RULES_HOSTS, DEFAULT_COMPETITION_SEEDS
from app.llm import GeminiClient
from app.models import Candidate
from verify_competition_production import cloud_json, cloud_value

TARGETS = (
    ('書藝智生', 'https://tkutimes.tku.edu.tw/dtl.aspx?no=60832'),
    ('Post-Meaning Prize', 'https://www.postmeaning.art/rules'),
    ('AI ZONE', 'https://filmfreeway.com/AIZONEInternationalAIFilmFestival2026'),
)
LABELS = {'ai_policy': '大量 AI 製作許可', 'attendance': '完整出席義務', 'publicity': '自行公開展示權',
          'rights': '著作權與授權', 'recognition': '公開得獎紀錄', 'deadline': '完整截止時間及時區',
          'registration_fee': '報名費', 'deliverables': '完整交付規格', 'eligibility': '參賽資格', 'submission': '交件方式'}


def issues_for(cases, listings):
    issues = []
    for case in cases:
        report = case['report']
        failed = [row for row in report.get('fetch_report', []) if row['status'] != 'ok']
        if failed:
            issues.append({'case': case['name'], 'kind': 'fetch', 'problem': '規則頁讀取失敗：' + ', '.join(sorted({row['status'] for row in failed})), 'evidence': failed})
    for key, label in LABELS.items():
        for case in cases:
            report = case['report']
            if not report.get('sources'):
                continue
            if report.get('facts', {}).get(key, {}).get('value', 'unknown') == 'unknown':
                issues.append({'case': case['name'], 'kind': key, 'problem': label + '尚無可用規則證據', 'evidence': report.get('sources', [])})
    for case in cases:
        estimate = case['report'].get('estimate', {})
        if estimate.get('ai_share') is None or estimate.get('ai_share', 0) < .9:
            issues.append({'case': case['name'], 'kind': 'ai_share', 'problem': 'AI 製作比例未達或尚未確認 90%', 'evidence': estimate})
        if estimate.get('uncertain', True):
            issues.append({'case': case['name'], 'kind': 'feasibility', 'problem': '時間、工具額度或完整製作計畫仍不確定', 'evidence': estimate})
    if listings['errors']:
        issues.append({'case': '公告來源', 'kind': 'listing', 'problem': '部分公告頁讀取失敗', 'evidence': [row for row in listings['receipts'] if row['status'] != 'ok']})
    return issues


async def audit(args):
    service = cloud_json('run', 'services', 'describe', 'kairos', '--project=yili-chronos-prod', '--region=asia-east1')
    env = {row['name']: row for row in service['spec']['template']['spec']['containers'][0]['env']}
    ref = env['GEMINI_API_KEY']['valueFrom']['secretKeyRef']
    key = cloud_value('secrets', 'versions', 'access', ref['key'], '--secret=' + ref['name'], '--project=yili-chronos-prod')
    llm = GeminiClient(key, env['GEMINI_MODEL']['value'], fallback_model=env.get('GEMINI_FALLBACK_MODEL', {}).get('value', ''))

    async def screen(name, url):
        candidate = Candidate('round-audit', 'organizer', url, url, '', '/competition')
        await CompetitionScreener(llm, DEFAULT_RULES_HOSTS).screen(candidate)
        return {'name': name, 'url': url, 'report': candidate.competition}

    async def listing_audit():
        source = AnnouncementSource(DEFAULT_ANNOUNCEMENT_URLS, DEFAULT_RULES_HOSTS,
                                    seed_pages=DEFAULT_COMPETITION_SEEDS if args.round == 3 else ())
        leads, errors = await source.discover()
        return {'errors': errors, 'receipts': source.last_report, 'leads': [{'title': item.text.splitlines()[0], 'url': item.permalink} for item in leads]}

    results = await asyncio.gather(*(screen(name, url) for name, url in TARGETS), listing_audit())
    cases, listings = results[:-1], results[-1]
    problems = issues_for(cases, listings)
    report = {'round': args.round, 'checked_at': datetime.now(UTC).isoformat(), 'cases': cases,
              'listings': listings, 'issues': problems[:10], 'additional_issue_count': max(0, len(problems) - 10)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'round': args.round, 'listing_leads': len(listings['leads']), 'listing_errors': listings['errors'],
                     'cases': [{'name': item['name'], 'decision': item['report']['decision'],
                                'documents': len(item['report'].get('sources', [])),
                                'quoted_facts': sum(bool(f.get('quote')) for f in item['report'].get('facts', {}).values())} for item in cases],
                     'issues': [{'case': item['case'], 'problem': item['problem']} for item in report['issues']]}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=int, choices=(1, 2, 3), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(audit(args))
    except Exception as exc:
        print(json.dumps({'audit_failed': type(exc).__name__}))
        sys.exit(1)
