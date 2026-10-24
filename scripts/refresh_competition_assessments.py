"""Explicit, silent assessment refresh. Defaults to a dry run; never runs workflows."""
from __future__ import annotations

import argparse
from datetime import datetime, UTC, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ASSESSMENT_FIELDS = {
    'decision', 'rank', 'blockers', 'facts', 'sources', 'fact_diagnostics',
    'checked_at', 'verification_questions', 'estimate', 'fetch_report',
    'source_hashes', 'discovery_signal', 'decision_conditions',
}


def assessment_patch(current, report, expected_url):
    if current.get('category') != 'ai_competition' or current.get('permalink') != expected_url:
        raise ValueError('Candidate identity changed')
    if expected_url not in report.get('sources', []) or not report.get('facts'):
        raise ValueError('Refresh lacks primary-source evidence')
    if report.get('decision') not in {'eligible', 'pending', 'rejected'}:
        raise ValueError('Invalid assessment decision')
    checked = datetime.fromisoformat(report['checked_at'])
    now = datetime.now(UTC)
    if not checked.tzinfo or not now - timedelta(days=1) <= checked <= now + timedelta(minutes=5):
        raise ValueError('Assessment is stale or has an invalid clock')
    return {'competition.' + key: value for key, value in report.items() if key in ASSESSMENT_FIELDS}


def refresh_reference(reference, client, item, *, apply=False):
    snapshot = reference.get()
    if not snapshot.exists or snapshot.update_time.isoformat() != item['expected_update_time']:
        raise ValueError('Snapshot changed; regenerate the plan')
    current = snapshot.to_dict()
    report = json.loads(Path(item['report_path']).read_text(encoding='utf-8'))
    patch = assessment_patch(current, report, item['expected_url'])
    if apply:
        # The server also rejects writes racing after the read. No status, answers,
        # notification receipt, inquiry state, or top-level timestamps are touched.
        reference.update(patch, option=client.write_option(last_update_time=snapshot.update_time))
    return {'candidate_id': item['candidate_id'], 'applied': apply,
            'status_preserved': current.get('status'), 'fields': sorted(patch)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from google.cloud import firestore
    from google.oauth2.credentials import Credentials
    from verify_competition_production import cloud_value
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    client = firestore.Client(project=plan['project'], database=plan['database'],
                              credentials=Credentials(cloud_value('auth', 'print-access-token')))
    results = [refresh_reference(client.collection(plan['collection']).document(item['candidate_id']),
                                 client, item, apply=args.apply) for item in plan['items']]
    print(json.dumps({'results': results, 'notifications_sent': 0, 'organizer_contacts': 0}))


if __name__ == '__main__':
    main()
