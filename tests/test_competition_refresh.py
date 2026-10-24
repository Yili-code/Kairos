from datetime import datetime, UTC
import json
import pytest
from scripts.refresh_competition_assessments import assessment_patch, refresh_reference


URL = 'https://example.edu.tw/rules'


def report():
    return {'decision': 'pending', 'facts': {'rights': {'value': 'unknown'}},
            'sources': [URL], 'checked_at': datetime.now(UTC).isoformat(),
            'status': 'discovered', 'inquiry_status': 'email_sent', 'retry_after': 'bad'}


def test_refresh_changes_only_assessment_fields_and_never_resurrects_skipped_candidates():
    current = {'category': 'ai_competition', 'permalink': URL, 'status': 'skipped',
               'answers': {'interest': 'no'}, 'telegram_message_id': 42,
               'competition': {'inquiry_status': 'email_uncertain'}}
    patch = assessment_patch(current, report(), URL)
    assert all(key.startswith('competition.') for key in patch)
    assert not any(key in patch for key in ('status', 'answers', 'telegram_message_id',
                                           'competition.inquiry_status', 'competition.retry_after'))
    assert current['status'] == 'skipped'
    with pytest.raises(ValueError):
        assessment_patch(current, report(), URL + '?different=event')


def test_refresh_dry_run_and_stale_snapshot_cannot_write(tmp_path):
    path = tmp_path / 'report.json';path.write_text(json.dumps(report()), encoding='utf-8')
    stamp = datetime.now(UTC)
    class Snapshot:
        exists = True
        update_time = stamp
        def to_dict(self):return {'category': 'ai_competition', 'permalink': URL, 'status': 'telegram_sent'}
    class Reference:
        def get(self):return Snapshot()
        def update(self, *args, **kwargs):raise AssertionError('Dry run must not write')
    item = {'candidate_id': 'test', 'expected_update_time': stamp.isoformat(),
            'expected_url': URL, 'report_path': str(path)}
    assert refresh_reference(Reference(), None, item)['applied'] is False
    item['expected_update_time'] = 'older'
    with pytest.raises(ValueError, match='Snapshot changed'):
        refresh_reference(Reference(), None, item, apply=True)


def test_apply_uses_a_server_version_precondition_and_never_retries_a_conflict(tmp_path):
    path = tmp_path / 'report.json';path.write_text(json.dumps(report()), encoding='utf-8')
    stamp = datetime.now(UTC)
    class Snapshot:
        exists = True
        update_time = stamp
        def to_dict(self):return {'category': 'ai_competition', 'permalink': URL, 'status': 'skipped'}
    class Client:
        def write_option(self, *, last_update_time):
            assert last_update_time == stamp
            return 'server-version-guard'
    class Reference:
        calls = 0
        def get(self):return Snapshot()
        def update(self, patch, *, option):
            self.calls += 1
            assert option == 'server-version-guard'
            assert 'competition.decision' in patch and 'status' not in patch
            raise RuntimeError('Concurrent owner action')
    reference = Reference()
    item = {'candidate_id': 'test', 'expected_update_time': stamp.isoformat(),
            'expected_url': URL, 'report_path': str(path)}
    with pytest.raises(RuntimeError, match='Concurrent owner action'):
        refresh_reference(reference, Client(), item, apply=True)
    assert reference.calls == 1
