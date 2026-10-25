from datetime import datetime, UTC, timedelta
from scripts.audit_scan_acceptance import queue_summary, run_summary
from app.models import Candidate, Status


def test_cooling_pending_work_is_not_reported_as_completed():
    now = datetime.now(UTC)
    row = Candidate('cooling', 'x', 'contest', 'https://example.test/', '', 'test',
        status=Status.COMPETITION_PENDING_SCREEN, screen_attempts=2,
        competition={'retry_after': (now + timedelta(hours=12)).isoformat(),
                     'fetch_report': [{'status': 'http_403'}]})
    result = queue_summary([row.to_dict()], now=now)
    assert result['pending'] == result['cooling_or_leased'] == 1
    assert result['due'] == result['unattempted'] == 0
    assert result['pending_rule_fetch_statuses'] == {'http_403': 1}


def test_pending_receipts_and_missing_receipts_do_not_verify_eligible_delivery():
    first = Candidate('pending', 'x', 'contest', 'https://example.test/', '', 'test',
        status=Status.TELEGRAM_SENT, telegram_message_id=123, competition={'decision': 'pending'})
    second = Candidate('missing', 'x', 'contest', 'https://example.test/2', '', 'test',
        status=Status.TELEGRAM_SENT, competition={'decision': 'eligible'})
    result = queue_summary([first.to_dict(), second.to_dict()])
    assert result['delivered_missing_receipt'] == ['missing']
    assert result['eligible_delivered_candidates'] == []


def test_receipts_preserve_source_failure_and_omit_page_text():
    rows = [{'run_id': 'run-test', 'started_at': 1000, 'finished_at': 1105, 'status': 'partial',
             'counts': {'screen_completed': 0, 'announcement_source_errors': 1,
                        'announcement_source_report': [{'url': 'https://example.test/', 'status': 'http_403'}]}}]
    result = run_summary(rows)[0]
    assert result['duration_seconds'] == 105
    assert result['source_failures'] == [{'url': 'https://example.test/', 'status': 'http_403'}]
    assert result['counts']['screen_completed'] == 0
    assert 'announcement_source_report' not in result['counts']
