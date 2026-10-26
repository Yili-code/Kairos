from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol
import uuid
import hashlib

from app.models import Candidate


def card_claimable(candidate):
    if candidate.status != 'discovered' or candidate.card_attempts >= 3:return False
    if not candidate.card_retry_after:return True
    try:
        due = datetime.fromisoformat(candidate.card_retry_after)
        return bool(due.tzinfo and due <= datetime.now(UTC))
    except (ValueError, TypeError):return False


def screen_claimable(candidate: Candidate) -> bool:
    if candidate.screen_failure_streak >= 3:
        return False
    if candidate.status == "competition_pending_screen":
        retry_after = candidate.competition.get('retry_after')
        if retry_after:
            try:
                due = datetime.fromisoformat(retry_after)
                if not due.tzinfo or due > datetime.now(UTC):
                    return False
            except (ValueError, TypeError):
                return False
        return True
    if candidate.status != "competition_screening":
        return False
    try:
        updated = datetime.fromisoformat(candidate.updated_at)
        return bool(updated.tzinfo and updated < datetime.now(UTC) - timedelta(minutes=10))
    except (TypeError, ValueError):
        return False


def manual_screen_claimable(candidate: Candidate) -> bool:
    # An explicit owner review may retry paused work, but never overlap a live claim.
    if candidate.status in {'competition_pending_screen', 'discovered', 'skipped', 'telegram_failed'}:
        return True
    if candidate.status != 'competition_screening':
        return False
    try:
        updated = datetime.fromisoformat(candidate.updated_at)
        return bool(updated.tzinfo and updated < datetime.now(UTC) - timedelta(minutes=10))
    except (ValueError, TypeError):
        return False


SCREEN_RESULT_FIELDS = ('competition', 'first_round_score', 'reasons', 'risks', 'status',
                        'screen_failure_streak', 'card_attempts', 'card_retry_after', 'card_last_error')


class Repository(Protocol):
    def get(self, candidate_id: str) -> Candidate | None: ...
    def save(self, candidate: Candidate) -> None: ...
    def create_if_absent(self, candidate: Candidate) -> bool: ...
    def find_by_status(self, statuses: Iterable[str], limit: int | None = 50) -> list[Candidate]: ...
    def screen_work_page(self, limit: int = 500) -> list[Candidate]: ...
    def count_by_status(self, statuses: Iterable[str]) -> int: ...
    def claim_for_send(self, candidate_id: str, draft_hash: str, attempt_id: str) -> Candidate | None: ...
    def claim_for_card(self, candidate_id: str) -> Candidate | None: ...
    def claim_for_screen(self, candidate_id: str, *, manual: bool = False) -> Candidate | None: ...
    def finish_card(self, candidate_id: str, attempt_id: str, status: str, **fields) -> bool: ...
    def save_refresh(self, candidate: Candidate, expected: dict) -> bool: ...
    def save_screen_result(self, candidate: Candidate, expected: dict) -> bool: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.items: dict[str, Candidate] = {}
        self._screen_after: dict | None = None

    def get(self, candidate_id: str) -> Candidate | None:
        return self.items.get(candidate_id)

    def save(self, candidate: Candidate) -> None:
        candidate.updated_at = datetime.now(UTC).isoformat()
        self.items[candidate.id] = candidate

    def create_if_absent(self, candidate: Candidate) -> bool:
        if candidate.id in self.items:
            return False
        self.save(candidate)
        return True

    def save_refresh(self, candidate: Candidate, expected: dict) -> bool:
        current = self.get(candidate.id)
        if not current or current.status != 'telegram_sent' or current.to_dict() != expected:
            return False
        from copy import deepcopy
        for field in ('competition', 'first_round_score', 'reasons', 'risks'):
            setattr(current, field, deepcopy(getattr(candidate, field)))
        self.save(current)
        candidate.updated_at = current.updated_at
        return True

    def save_screen_result(self, candidate: Candidate, expected: dict) -> bool:
        from copy import deepcopy
        current = self.get(candidate.id)
        if (not current or current.status != 'competition_screening'
                or current.to_dict() != expected):
            return False
        for field in SCREEN_RESULT_FIELDS:
            setattr(current, field, deepcopy(getattr(candidate, field)))
        self.save(current)
        candidate.updated_at = current.updated_at
        return True

    def find_by_status(self, statuses: Iterable[str], limit: int | None = 50) -> list[Candidate]:
        allowed = set(statuses)
        return sorted((item for item in self.items.values() if item.status in allowed),
                      key=lambda item: (item.updated_at, item.id))[:limit]

    def count_by_status(self, statuses: Iterable[str]) -> int:
        allowed = set(statuses)
        return sum(item.status in allowed for item in self.items.values())

    def screen_work_page(self, limit: int = 500) -> list[Candidate]:
        if not 1 <= limit <= 500:
            raise ValueError('Screen window must be bounded')
        rows = self.find_by_status(['competition_pending_screen', 'competition_screening'], limit=None)
        after = self._screen_after
        page = [row for row in rows if after is None or
                (row.updated_at, row.id) > (after['updated_at'], after['id'])][:limit]
        if not page and after:
            page = rows[:limit]
        self._screen_after = ({'updated_at': page[-1].updated_at, 'id': page[-1].id}
                              if len(page) == limit else None)
        return page

    def claim_for_send(self, candidate_id: str, draft_hash: str, attempt_id: str) -> Candidate | None:
        candidate = self.get(candidate_id)
        if not candidate or candidate.status != "draft_ready" or candidate.draft_hash != draft_hash:
            return None
        candidate.status = "sending"
        candidate.approval_hash = draft_hash
        candidate.send_attempt_id = attempt_id
        self.save(candidate)
        return candidate

    def claim_for_card(self, candidate_id: str) -> Candidate | None:
        candidate = self.get(candidate_id)
        if not candidate or not card_claimable(candidate):
            return None
        candidate.status = "telegram_sending"
        candidate.card_attempt_id = uuid.uuid4().hex
        candidate.card_attempts += 1
        self.save(candidate)
        return candidate

    def finish_card(self, candidate_id, attempt_id, status, **fields):
        candidate = self.get(candidate_id)
        if not candidate or candidate.status != 'telegram_sending' or candidate.card_attempt_id != attempt_id:return False
        assert set(fields) <= {'telegram_message_id', 'card_retry_after', 'card_last_error'}
        candidate.status = status
        for key, value in fields.items():setattr(candidate, key, value)
        self.save(candidate)
        return True

    def claim_for_screen(self, candidate_id: str, *, manual: bool = False) -> Candidate | None:
        candidate = self.get(candidate_id)
        if not candidate or not (manual_screen_claimable(candidate) if manual else screen_claimable(candidate)):
            return None
        candidate.status = "competition_screening"
        candidate.screen_attempts += 1
        candidate.screen_failure_streak += 1
        self.save(candidate)
        return candidate


class FirestoreRepository:
    def __init__(self, project: str, database: str, collection: str) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project or None, database=database)
        self.collection_path = collection.strip("/")
        self.collection = self.client.collection(self.collection_path)
        cursor_key = hashlib.sha256(self.collection_path.encode()).hexdigest()
        self.screen_cursor_reference = self.client.collection('kairos_screen_cursors').document(cursor_key)

    def get(self, candidate_id: str) -> Candidate | None:
        snapshot = self.collection.document(candidate_id).get(timeout=5, retry=None)
        return Candidate.from_dict(snapshot.to_dict()) if snapshot.exists else None

    def save(self, candidate: Candidate) -> None:
        candidate.updated_at = datetime.now(UTC).isoformat()
        self.collection.document(candidate.id).set(candidate.to_dict(), merge=True, timeout=5, retry=None)

    def save_refresh(self, candidate: Candidate, expected: dict) -> bool:
        from google.cloud import firestore
        reference = self.collection.document(candidate.id)

        @firestore.transactional
        def update(transaction):
            snapshot = reference.get(transaction=transaction, timeout=5, retry=None)
            row = snapshot.to_dict() if snapshot.exists else {}
            if row.get('status') != 'telegram_sent' or Candidate.from_dict(row).to_dict() != expected:
                return None
            stamp = datetime.now(UTC).isoformat()
            transaction.update(reference, {
                **{field: getattr(candidate, field) for field in ('competition', 'first_round_score', 'reasons', 'risks')},
                'updated_at': stamp,
            })
            return stamp

        stamp = update(self.client.transaction())
        if stamp is None:
            return False
        candidate.updated_at = stamp
        return True

    def save_screen_result(self, candidate: Candidate, expected: dict) -> bool:
        from google.cloud import firestore
        reference = self.collection.document(candidate.id)
        @firestore.transactional
        def update(transaction):
            snapshot = reference.get(transaction=transaction, timeout=5, retry=None)
            row = snapshot.to_dict() if snapshot.exists else {}
            if row.get('status') != 'competition_screening' or Candidate.from_dict(row).to_dict() != expected:
                return None
            stamp = datetime.now(UTC).isoformat()
            transaction.update(reference, {
                **{field: getattr(candidate, field) for field in SCREEN_RESULT_FIELDS}, 'updated_at': stamp})
            return stamp
        stamp = update(self.client.transaction())
        if stamp is None:
            return False
        candidate.updated_at = stamp
        return True

    def create_if_absent(self, candidate: Candidate) -> bool:
        from google.api_core.exceptions import AlreadyExists

        try:
            self.collection.document(candidate.id).create(candidate.to_dict(), timeout=5, retry=None)
            return True
        except AlreadyExists:
            return False

    def find_by_status(self, statuses: Iterable[str], limit: int | None = 50) -> list[Candidate]:
        values = list(statuses)
        if not values:
            return []
        query = self.collection.where("status", "in", values).order_by("updated_at")
        if limit is not None:
            query = query.limit(limit)
        return [Candidate.from_dict(doc.to_dict()) for doc in query.stream(timeout=10, retry=None)]

    def count_by_status(self, statuses: Iterable[str]) -> int:
        values = list(statuses)
        if not values:
            return 0
        result = self.collection.where('status', 'in', values).count(alias='total').get(timeout=10, retry=None)
        return int(result[0][0].value)

    def screen_work_page(self, limit: int = 500) -> list[Candidate]:
        from google.cloud import firestore
        if not 1 <= limit <= 500:
            raise ValueError('Screen window must be bounded')
        reference = self.screen_cursor_reference
        snapshot = reference.get(timeout=5, retry=None)
        expected = snapshot.to_dict() if snapshot.exists else {}
        after = expected.get('after')
        query = (self.collection.where('status', 'in', ['competition_pending_screen', 'competition_screening'])
                 .order_by('updated_at').order_by('__name__'))
        page_query = query.start_after({'updated_at': after['updated_at'],
                          '__name__': self.collection.document(after['id'])}) if after else query
        documents = list(page_query.limit(limit).stream(timeout=10, retry=None))
        if not documents and after:
            documents = list(query.limit(limit).stream(timeout=10, retry=None))
        next_after = ({'updated_at': documents[-1].to_dict()['updated_at'], 'id': documents[-1].id}
                      if len(documents) == limit else None)
        if next_after != after:
            @firestore.transactional
            def advance(transaction):
                current = reference.get(transaction=transaction, timeout=5, retry=None)
                if (current.to_dict() if current.exists else {}) != expected:
                    return False
                transaction.set(reference, {'after': next_after, 'updated_at': datetime.now(UTC).isoformat()})
                return True
            advance(self.client.transaction())
        return [Candidate.from_dict(doc.to_dict()) for doc in documents]

    def claim_for_card(self, candidate_id: str) -> Candidate | None:
        from google.cloud import firestore

        reference = self.collection.document(candidate_id)

        @firestore.transactional
        def claim(transaction):
            snapshot = reference.get(transaction=transaction, timeout=5, retry=None)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict()
            candidate = Candidate.from_dict(data)
            if not card_claimable(candidate):
                return None
            patch = {'status': 'telegram_sending', 'updated_at': datetime.now(UTC).isoformat(),
                     'card_attempt_id': uuid.uuid4().hex, 'card_attempts': candidate.card_attempts + 1}
            data.update(patch)
            transaction.update(reference, patch)
            return Candidate.from_dict(data)

        return claim(self.client.transaction())

    def finish_card(self, candidate_id, attempt_id, status, **fields):
        from google.cloud import firestore
        assert set(fields) <= {'telegram_message_id', 'card_retry_after', 'card_last_error'}
        ref = self.collection.document(candidate_id)
        @firestore.transactional
        def finish(transaction):
            snapshot = ref.get(transaction=transaction, timeout=5, retry=None)
            if not snapshot.exists:return False
            row = snapshot.to_dict()
            if row.get('status') != 'telegram_sending' or row.get('card_attempt_id', '') != attempt_id:return False
            transaction.update(ref, {'status': status, 'updated_at': datetime.now(UTC).isoformat(), **fields})
            return True
        return finish(self.client.transaction())

    def claim_for_screen(self, candidate_id: str, *, manual: bool = False) -> Candidate | None:
        from google.cloud import firestore

        reference = self.collection.document(candidate_id)

        @firestore.transactional
        def claim(transaction):
            snapshot = reference.get(transaction=transaction, timeout=5, retry=None)
            if not snapshot.exists:
                return None
            candidate = Candidate.from_dict(snapshot.to_dict())
            if not (manual_screen_claimable(candidate) if manual else screen_claimable(candidate)):
                return None
            candidate.status = "competition_screening"
            candidate.screen_attempts += 1
            candidate.screen_failure_streak += 1
            candidate.updated_at = datetime.now(UTC).isoformat()
            transaction.update(reference, {"status": candidate.status, "updated_at": candidate.updated_at,
                "screen_attempts": candidate.screen_attempts, "screen_failure_streak": candidate.screen_failure_streak})
            return candidate

        return claim(self.client.transaction())

    def claim_for_send(self, candidate_id: str, draft_hash: str, attempt_id: str) -> Candidate | None:
        from google.cloud import firestore

        reference = self.collection.document(candidate_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def claim(active_transaction):
            snapshot = reference.get(transaction=active_transaction, timeout=5, retry=None)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict()
            if data.get("status") != "draft_ready" or data.get("draft_hash") != draft_hash:
                return None
            now = datetime.now(UTC).isoformat()
            updates = {
                "status": "sending",
                "approval_hash": draft_hash,
                "send_attempt_id": attempt_id,
                "updated_at": now,
            }
            active_transaction.update(reference, updates)
            data.update(updates)
            return Candidate.from_dict(data)

        return claim(transaction)
