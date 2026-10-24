from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    DISCOVERED = "discovered"
    COMPETITION_PENDING_SCREEN = "competition_pending_screen"
    COMPETITION_SCREENING = "competition_screening"
    SHORTLISTED = "shortlisted"
    TELEGRAM_SENDING = "telegram_sending"
    TELEGRAM_SENT = "telegram_sent"
    TELEGRAM_UNCERTAIN = "telegram_uncertain"
    TELEGRAM_FAILED = "telegram_failed"
    QUESTIONNAIRE = "questionnaire"
    EVALUATED = "evaluated"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    SKIPPED = "skipped"
    DM_UNAVAILABLE = "dm_unavailable"
    SEND_UNCERTAIN = "send_uncertain"
    SEND_FAILED = "send_failed"


@dataclass
class Candidate:
    id: str
    username: str
    text: str
    permalink: str
    timestamp: str
    search_term: str
    category: str = "other"
    first_round_score: int = 0
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    competition: dict[str, Any] = field(default_factory=dict)
    status: str = Status.DISCOVERED
    answers: dict[str, str] = field(default_factory=dict)
    fit_score: int | None = None
    interest_score: int | None = None
    assessment: str = ""
    draft_message: str = ""
    draft_hash: str = ""
    approval_hash: str = ""
    send_attempt_id: str = ""
    telegram_message_id: int | None = None
    card_attempt_id: str = ""
    card_attempts: int = 0
    card_retry_after: str = ""
    card_last_error: str = ""
    sent_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candidate":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed})
