from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol
import uuid

from app.models import Candidate


def card_claimable(candidate):
    if candidate.status != 'discovered' or candidate.card_attempts >= 3:return False
    if not candidate.card_retry_after:return True
    try:
        due = datetime.fromisoformat(candidate.card_retry_after)
        return bool(due.tzinfo and due <= datetime.now(UTC))
    except (ValueError, TypeError):return False


def screen_claimable(candidate: Candidate) -> bool:
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


class Repository(Protocol):
    def get(self, candidate_id: str) -> Candidate | None: ...
    def save(self, candidate: Candidate) -> None: ...
    def create_if_absent(self, candidate: Candidate) -> bool: ...
    def find_by_status(self, statuses: Iterable[str], limit: int = 50) -> list[Candidate]: ...
    def claim_for_send(self, candidate_id: str, draft_hash: str, attempt_id: str) -> Candidate | None: ...
    def claim_for_card(self, candidate_id: str) -> Candidate | None: ...
    def claim_for_screen(self, candidate_id: str) -> Candidate | None: ...
    def finish_card(self, candidate_id: str, attempt_id: str, status: str, **fields) -> bool: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.items: dict[str, Candidate] = {}

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

    def find_by_status(self, statuses: Iterable[str], limit: int = 50) -> list[Candidate]:
        allowed = set(statuses)
        return [item for item in self.items.values() if item.status in allowed][:limit]

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

    def claim_for_screen(self, candidate_id: str) -> Candidate | None:
        candidate = self.get(candidate_id)
        if not candidate or not screen_claimable(candidate):
            return None
        candidate.status = "competition_screening"
        self.save(candidate)
        return candidate


class FirestoreRepository:
    def __init__(self, project: str, database: str, collection: str) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project or None, database=database)
        self.collection = self.client.collection(collection)

    def get(self, candidate_id: str) -> Candidate | None:
        snapshot = self.collection.document(candidate_id).get(timeout=5, retry=None)
        return Candidate.from_dict(snapshot.to_dict()) if snapshot.exists else None

    def save(self, candidate: Candidate) -> None:
        candidate.updated_at = datetime.now(UTC).isoformat()
        self.collection.document(candidate.id).set(candidate.to_dict(), merge=True, timeout=5, retry=None)

    def create_if_absent(self, candidate: Candidate) -> bool:
        from google.api_core.exceptions import AlreadyExists

        try:
            self.collection.document(candidate.id).create(candidate.to_dict(), timeout=5, retry=None)
            return True
        except AlreadyExists:
            return False

    def find_by_status(self, statuses: Iterable[str], limit: int = 50) -> list[Candidate]:
        values = list(statuses)
        if not values:
            return []
        query = self.collection.where("status", "in", values).limit(limit)
        return [Candidate.from_dict(doc.to_dict()) for doc in query.stream(timeout=10, retry=None)]

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

    def claim_for_screen(self, candidate_id: str) -> Candidate | None:
        from google.cloud import firestore

        reference = self.collection.document(candidate_id)

        @firestore.transactional
        def claim(transaction):
            snapshot = reference.get(transaction=transaction, timeout=5, retry=None)
            if not snapshot.exists:
                return None
            candidate = Candidate.from_dict(snapshot.to_dict())
            if not screen_claimable(candidate):
                return None
            candidate.status = "competition_screening"
            candidate.updated_at = datetime.now(UTC).isoformat()
            transaction.update(reference, {"status": candidate.status, "updated_at": candidate.updated_at})
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
