"""Durable scan receipts and a shared lease; health is not scan success."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, UTC
import hashlib
import json
import logging
import time
import uuid

LOG = logging.getLogger(__name__)
ISSUES = ('search_errors', 'competition_errors', 'competition_source_errors', 'card_errors',
          'announcement_source_errors', 'announcement_parse_failures', 'announcement_unreadable_pages',
          'search_terms_deferred', 'candidate_errors', 'competition_rule_fetch_errors', 'card_uncertain_recovered',
          'model_rate_limited', 'search_halted', 'announcement_deferred_pages',
          'screen_queue_due', 'screen_queue_sample_saturated', 'card_update_errors',
          'card_failed_remaining', 'card_uncertain_remaining', 'stale_sent_remaining',
          'card_queue_due', 'notification_queue_sample_saturated')


def finish_state(control, run_id, outcome, counts, error_type, now):
    summary = {'run_id': run_id, 'status': outcome, 'finished_at': now,
               'counts': counts, 'error_type': error_type}
    signature = hashlib.sha256(json.dumps([outcome, error_type,
        sorted(k for k in ISSUES if counts.get(k, 0))]).encode()).hexdigest()
    streak = control.get('consecutive_failures', 0) + 1 if outcome != 'succeeded' else 0
    repeated = signature == control.get('failure_signature')
    alert = outcome != 'succeeded' and repeated and streak >= 2 and control.get('alert_signature') != signature
    updated = {**control, 'lease_until': 0, 'last_finished': summary,
               'consecutive_failures': streak, 'failure_signature': signature if streak else '',
               'alert_signature': signature if alert else control.get('alert_signature', '') if streak else ''}
    if outcome == 'succeeded':
        updated['last_full_success'] = summary
    return updated, summary, alert


class MemoryScanStore:
    def __init__(self):self.control = {};self.runs = {}
    def start(self, run_id, now):
        if self.control.get('lease_until', 0) > now:return False
        previous = self.control.get('run_id')
        if previous and self.runs.get(previous, {}).get('status') == 'running':
            self.runs[previous].update(status='abandoned', finished_at=now)
        self.control.update(run_id=run_id, lease_until=now + 600, started_at=now)
        self.runs[run_id] = {'status': 'running', 'started_at': now}
        return True
    def finish(self, run_id, outcome, counts, error_type, now):
        if self.control.get('run_id') != run_id:return False
        self.control, summary, alert = finish_state(self.control, run_id, outcome, counts, error_type, now)
        self.runs[run_id].update(summary)
        return alert
    def status(self):return deepcopy(self.control)


class FirestoreScanStore:
    def __init__(self, client, collection='kairos_scan_runs'):
        self.client = client;self.collection = client.collection(collection)
    def start(self, run_id, now):
        from google.cloud import firestore
        ref = self.collection.document('control')
        @firestore.transactional
        def claim(transaction):
            row = ref.get(transaction=transaction, timeout=5).to_dict() or {}
            if row.get('lease_until', 0) > now:return False
            previous = row.get('run_id')
            if previous and row.get('lease_until', 0):
                transaction.update(self.collection.document(previous), {'status': 'abandoned', 'finished_at': now})
            transaction.set(ref, {**row, 'run_id': run_id, 'started_at': now, 'lease_until': now + 600})
            transaction.set(self.collection.document(run_id), {'status': 'running', 'started_at': now})
            return True
        return claim(self.client.transaction())
    def finish(self, run_id, outcome, counts, error_type, now):
        from google.cloud import firestore
        ref = self.collection.document('control')
        @firestore.transactional
        def complete(transaction):
            row = ref.get(transaction=transaction, timeout=5).to_dict() or {}
            if row.get('run_id') != run_id:return False
            updated, summary, alert = finish_state(row, run_id, outcome, counts, error_type, now)
            transaction.set(ref, updated)
            transaction.update(self.collection.document(run_id), summary)
            return alert
        return complete(self.client.transaction())
    def status(self):return self.collection.document('control').get(timeout=5, retry=None).to_dict() or {}


class ScanRunner:
    def __init__(self, store, telegram, *, timeout=480):
        self.store, self.telegram, self.timeout = store, telegram, timeout
    async def run(self, work):
        run_id = 'run-' + uuid.uuid4().hex
        if not await asyncio.to_thread(self.store.start, run_id, time.time()):
            return {'scan_status': 'busy'}
        outcome, counts, error_type = 'failed', {}, ''
        try:
            async with asyncio.timeout(self.timeout):
                counts = await work()
            outcome = 'partial' if any(counts.get(k, 0) for k in ISSUES) else 'succeeded'
            return {**counts, 'scan_status': outcome, 'run_id': run_id}
        except (Exception, asyncio.CancelledError) as exc:
            error_type = type(exc).__name__
            raise
        finally:
            alert = await asyncio.shield(asyncio.to_thread(self.store.finish, run_id, outcome, counts, error_type, time.time()))
            LOG.info('scan_finished %s', json.dumps({'run_id': run_id, 'status': outcome, 'counts': counts, 'error_type': error_type}))
            if alert:
                try:
                    await self.telegram.notify('Kairos 連續掃描未完整成功，請用 /status 查看結果。此類失敗暫不重複通知。')
                except Exception:
                    LOG.warning('scan_alert_delivery_uncertain run_id=%s', run_id)


def status_text(state):
    def stamp(value):
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(value, UTC).astimezone(ZoneInfo('Asia/Taipei')).strftime('%m/%d %H:%M') if value else '尚無紀錄'
    last = state.get('last_finished', {})
    success = state.get('last_full_success', {})
    running = state.get('lease_until', 0) > time.time()
    stale = bool(state.get('lease_until') and not running)
    issues = ', '.join(f'{k}={last.get("counts", {}).get(k)}' for k in ISSUES if last.get('counts', {}).get(k)) or '無已記錄問題'
    queue = state.get('queue', {})
    return (f'Kairos 自動執行狀態（臺灣時間）\n目前：{"執行中" if running else "上輪中斷，等下輪恢復" if stale else "待命"}\n'
            f'最後完成：{stamp(last.get("finished_at"))} · {last.get("status", "未知")}\n'
            f'最後完整成功：{stamp(success.get("finished_at"))}\n連續未完整成功：{state.get("consecutive_failures", 0)}\n'
            f'{issues}\n待評估：{queue.get("competition_pending_screen", 0)}；送達不明：{queue.get("telegram_uncertain", 0)}；通知待修復：{queue.get("telegram_failed", 0)}\n'
            f'已送評估需重查：{state.get("stale_sent_assessments", 0)}（最多檢查 500 筆）\n'
            '送達不明須人工核對，不會自動重送。完整成功指在單輪設定上限內完成，不代表所有候選均已評估或推薦仍有效。')
