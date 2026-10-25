"""Read-only production acceptance snapshot; never scans, sends, or retries work."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Candidate
from app.storage import screen_claimable


TAIPEI = timezone(timedelta(hours=8))
SAMPLE_LIMIT = 1000


def stamp(seconds):
    return datetime.fromtimestamp(seconds, UTC).astimezone(TAIPEI).isoformat() if seconds else None


def queue_summary(rows, *, now=None):
    now = now or datetime.now(UTC)
    pending = [row for row in rows if row.get('status') in {
        'competition_pending_screen', 'competition_screening'}]
    untouched = [row for row in pending if not row.get('screen_attempts')
                 and not row.get('competition', {}).get('fetch_report')]
    due = [row for row in pending if screen_claimable(Candidate.from_dict(row))]
    attention = [row for row in pending if row.get('screen_failure_streak', 0) >= 3]
    def age(row, field):
        try:
            value = datetime.fromisoformat(row.get(field, ''))
            return max(0, int((now - value).total_seconds())) if value.tzinfo else None
        except (ValueError, TypeError):
            return None
    notifications = [row for row in rows if row.get('status') == 'telegram_sent']
    return {
        'sample_limit': SAMPLE_LIMIT,
        'sample_saturated': len(rows) > SAMPLE_LIMIT,
        'statuses': dict(Counter(row.get('status') for row in rows)),
        'pending': len(pending), 'due': len(due),
        'cooling_or_leased': len(pending) - len(due) - len(attention),
        'screen_attention_remaining': len(attention),
        'screen_attention_ids': [row['id'] for row in attention],
        'unattempted': len(untouched),
        'oldest_due_age_seconds': max((age(row, 'updated_at') or 0 for row in due), default=0),
        'oldest_unattempted_age_seconds': max((age(row, 'created_at') or 0 for row in untouched), default=0),
        'oldest_due': [{'id': row['id'], 'created_at': row.get('created_at'),
                        'last_updated_at': row.get('updated_at'),
                        'recorded_attempts': row.get('screen_attempts', 0)}
                       for row in sorted(due, key=lambda row: row.get('updated_at', ''))[:10]],
        'pending_rule_fetch_statuses': dict(Counter(receipt.get('status') for row in pending
            for receipt in row.get('competition', {}).get('fetch_report', []))),
        'delivered': len(notifications),
        'delivered_missing_receipt': [row['id'] for row in notifications if not row.get('telegram_message_id')],
        'pending_card_updates': sum(bool(row.get('competition', {}).get('update_pending')) for row in notifications),
        # These are candidates for verification, not proof of the original delivery content.
        'eligible_delivered_candidates': [row['id'] for row in notifications
            if row.get('competition', {}).get('decision') == 'eligible'
            and row.get('telegram_message_id') and not row['id'].startswith(('e2e-', 'reliability-e2e-'))],
    }


def run_summary(rows):
    result = []
    for row in sorted(rows, key=lambda row: row.get('started_at', 0)):
        counts = row.get('counts', {})
        result.append({
            'run_id': row.get('run_id'), 'started_at': stamp(row.get('started_at')),
            'finished_at': stamp(row.get('finished_at')), 'status': row.get('status'),
            'duration_seconds': round(row['finished_at'] - row['started_at'], 2)
                if row.get('finished_at') and row.get('started_at') else None,
            'counts': {key: value for key, value in counts.items() if isinstance(value, (int, float, bool))},
            'source_failures': [{'url': receipt.get('url'), 'status': receipt.get('status')}
                for receipt in counts.get('announcement_source_report', []) if receipt.get('status') != 'ok'],
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', default=(datetime.now(UTC) - timedelta(days=1)).isoformat())
    parser.add_argument('--output', type=Path, default=Path('work/acceptance-latest.json'))
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since.replace('Z', '+00:00'))
    if not since.tzinfo:
        parser.error('--since requires a timezone')
    from google.cloud import firestore
    from google.oauth2.credentials import Credentials
    from verify_competition_production import cloud_value
    from verify_competition_screening import cloud_json
    service = cloud_json('run', 'services', 'describe', 'kairos',
                         '--project=yili-chronos-prod', '--region=asia-east1')
    env = {item['name']: item for item in service['spec']['template']['spec']['containers'][0]['env']}
    def value(name):
        item = env[name]
        if 'value' in item:
            return item['value']
        ref = item['valueFrom']['secretKeyRef']
        return cloud_value('secrets', 'versions', 'access', ref['key'],
                           '--secret=' + ref['name'], '--project=yili-chronos-prod')
    client = firestore.Client(project='yili-chronos-prod', database=value('FIRESTORE_DATABASE'),
                              credentials=Credentials(cloud_value('auth', 'print-access-token')))
    statuses = ['competition_pending_screen', 'competition_screening', 'discovered',
                'telegram_sent', 'telegram_sending', 'telegram_failed', 'telegram_uncertain', 'send_uncertain']
    rows = [doc.to_dict() for doc in client.collection(value('FIRESTORE_COLLECTION'))
            .where('status', 'in', statuses).order_by('updated_at').limit(SAMPLE_LIMIT + 1)
            .stream(timeout=30, retry=None)]
    runs = [doc.to_dict() for doc in client.collection('kairos_scan_runs')
            .where('started_at', '>=', since.timestamp()).order_by('started_at', direction='DESCENDING')
            .limit(501).stream(timeout=30, retry=None) if doc.id != 'control']
    scheduler = cloud_json('scheduler', 'jobs', 'describe', 'kairos-opportunity-scan',
                           '--project=yili-chronos-prod', '--location=asia-east1')
    report = {
        'observed_at': datetime.now(UTC).astimezone(TAIPEI).isoformat(),
        'latest_ready_revision': service['status']['latestReadyRevisionName'],
        'traffic': [{'revision': row.get('revisionName'), 'percent': row.get('percent', 0)}
                    for row in service['status']['traffic']],
        'scheduler': {key: scheduler.get(key) for key in (
            'state', 'schedule', 'timeZone', 'lastAttemptTime', 'scheduleTime', 'status')},
        'queue': queue_summary(rows), 'runs_sample_saturated': len(runs) >= 500,
        'runs': run_summary(runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'runs'}, ensure_ascii=True))
    print(json.dumps({'recent_runs': report['runs'][-4:]}, ensure_ascii=True))


if __name__ == '__main__':
    main()
