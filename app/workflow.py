from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.dm_sender import DMUnavailable, DMSenderError
from app.competitions import allowed_url, rules_urls
from app.llm import GeminiClient
from app.models import Candidate, Status
from app.scoring import apply_score
from app.storage import Repository
from app.telegram import TelegramClient
from app.threads_client import ThreadsClient


def message_hash(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


class Workflow:
    def __init__(
        self,
        repository: Repository,
        threads: ThreadsClient,
        telegram: TelegramClient,
        llm: GeminiClient,
        dm_sender: Any,
        *,
        shortlist_threshold: int,
        per_term_limit: int,
        max_cards: int,
        competition_screener: Any = None,
        competition_screen_limit: int = 3,
    ) -> None:
        self.repository = repository
        self.threads = threads
        self.telegram = telegram
        self.llm = llm
        self.dm_sender = dm_sender
        self.shortlist_threshold = shortlist_threshold
        self.per_term_limit = per_term_limit
        self.max_cards = max_cards
        self.competition_screener = competition_screener
        self.competition_screen_limit = competition_screen_limit

    async def discover(self, terms: tuple[str, ...]) -> dict[str, int]:
        created: list[Candidate] = []
        errors = 0
        screened = 0
        competition_errors = 0
        for term in terms:
            candidates = None
            for _ in range(2):
                try:
                    candidates = await self.threads.search(term, limit=self.per_term_limit)
                    break
                except Exception:
                    continue
            if candidates is None:
                errors += 1
                continue
            for candidate in candidates:
                if self.repository.get(candidate.id):
                    continue
                apply_score(candidate)
                if candidate.category == "ai_competition":
                    urls = rules_urls(candidate.text, getattr(self.competition_screener, "hosts", ()))
                    if urls:
                        candidate.id = "contest-" + hashlib.sha256(urls[0].encode()).hexdigest()[:24]
                        if self.repository.get(candidate.id):
                            continue
                    if not self.competition_screener or screened >= self.competition_screen_limit:
                        # Do not persist unprocessed candidates: a later scan may screen them.
                        continue
                    screened += 1
                    await self.competition_screener.screen(candidate)
                    if not candidate.competition.get("facts"):
                        competition_errors += 1
                    if candidate.competition.get("decision") == "rejected":
                        candidate.status = Status.SKIPPED
                if self.repository.create_if_absent(candidate):
                    created.append(candidate)

        # Keep cards beyond this run's delivery cap in a durable queue.
        queued = {candidate.id: candidate for candidate in self.repository.find_by_status([Status.DISCOVERED], limit=100)}
        queued.update({candidate.id: candidate for candidate in created})
        ranked = sorted(
            (candidate for candidate in queued.values() if (
                candidate.first_round_score >= self.shortlist_threshold
                if candidate.category != "ai_competition"
                else candidate.competition.get("decision") in {"eligible", "pending"}
            )),
            key=lambda candidate: candidate.first_round_score,
            reverse=True,
        )
        shortlist = []
        pending_selected = False
        for candidate in ranked:
            if candidate.category == "ai_competition":
                deadline = candidate.competition.get("facts", {}).get("deadline", {}).get("value", "unknown")
                try:
                    closing = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    closing = None
                if closing and closing.tzinfo and closing <= datetime.now(UTC):
                    candidate.competition["decision"] = "rejected"
                    candidate.competition["blockers"] = ["已截止"]
                    candidate.status = Status.SKIPPED
                    self.repository.save(candidate)
                    continue
            pending = candidate.category == "ai_competition" and candidate.competition.get("decision") == "pending"
            if pending and pending_selected:
                continue
            if len(shortlist) >= self.max_cards:
                break
            shortlist.append(candidate)
            pending_selected = pending_selected or pending
        sent = 0
        card_errors = 0
        for candidate in shortlist:
            candidate = self.repository.claim_for_card(candidate.id)
            if not candidate:
                continue
            try:
                candidate.telegram_message_id = await self.telegram.send_candidate(candidate)
            except RuntimeError:
                candidate.status = Status.TELEGRAM_UNCERTAIN
                self.repository.save(candidate)
                card_errors += 1
                continue
            candidate.status = Status.TELEGRAM_SENT
            self.repository.save(candidate)
            sent += 1
        if terms and errors == len(terms):
            await self.telegram.notify("Opportunity scan failed for every search term. No results were evaluated.")
        return {
            "discovered": len(created),
            "shortlisted": len(shortlist),
            "cards_sent": sent,
            "card_errors": card_errors,
            "search_errors": errors,
            "competitions_screened": screened,
            "competition_errors": competition_errors,
        }

    async def handle_callback(self, callback_id: str, data: str) -> None:
        parts = data.split(":", 2)
        if len(parts) != 3 or parts[0] != "q":
            await self.telegram.answer_callback(callback_id, "Unsupported action")
            return
        candidate_id, action = parts[1], parts[2]
        candidate = self.repository.get(candidate_id)
        if not candidate:
            await self.telegram.answer_callback(callback_id, "Opportunity not found")
            return

        if candidate.category == "ai_competition" and action != "skip":
            # Contests are research/recommendation only, including forged/old approval callbacks.
            await self.telegram.answer_callback(callback_id, "競賽只提供評估，請自行決定報名與交件")
            return

        if action == "skip":
            if candidate.status not in {
                Status.TELEGRAM_SENT,
                Status.QUESTIONNAIRE,
                Status.EVALUATED,
                Status.DRAFT_READY,
            }:
                await self._reject_stale_callback(callback_id)
                return
            candidate.status = Status.SKIPPED
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Skipped")
            return
        if action == "start":
            if candidate.status != Status.TELEGRAM_SENT:
                await self._reject_stale_callback(callback_id)
                return
            candidate.status = Status.QUESTIONNAIRE
            candidate.answers["step"] = "interest"
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Questionnaire started")
            await self.telegram.send_question(candidate, "How interested are you?", [(str(i), f"interest_{i}") for i in range(1, 6)])
            return
        if action.startswith("interest_"):
            if not self._is_question_step(candidate, "interest"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["interest"] = action.rsplit("_", 1)[1]
            candidate.answers["step"] = "capacity"
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Saved")
            await self.telegram.send_question(candidate, "Does the expected workload fit 13–16 hours/week during term?", [
                ("Fits", "capacity_fits"),
                ("Stretch", "capacity_stretch"),
                ("No", "capacity_no"),
                ("Need details", "capacity_unknown"),
            ])
            return
        if action.startswith("capacity_"):
            if not self._is_question_step(candidate, "capacity"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["capacity"] = action.removeprefix("capacity_")
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Saved")
            await self._ask_category_detail(candidate)
            return
        if action.startswith("role_"):
            if not self._is_question_step(candidate, "preferred_role"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["preferred_role"] = action.removeprefix("role_")
            await self.telegram.answer_callback(callback_id, "Saved")
            await self._ask_motivation(candidate)
            return
        if action.startswith("compensation_"):
            if not self._is_question_step(candidate, "compensation_condition"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["compensation_condition"] = action.removeprefix("compensation_")
            await self.telegram.answer_callback(callback_id, "Saved")
            await self._ask_motivation(candidate)
            return
        if action.startswith("engagement_"):
            if not self._is_question_step(candidate, "engagement_preference"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["engagement_preference"] = action.removeprefix("engagement_")
            await self.telegram.answer_callback(callback_id, "Saved")
            await self._ask_motivation(candidate)
            return
        if action.startswith("motivation_"):
            if not self._is_question_step(candidate, "motivation"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["motivation"] = action.removeprefix("motivation_")
            candidate.answers["step"] = "concern"
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Saved")
            await self.telegram.send_question(candidate, "What is your biggest concern?", [
                ("None", "concern_none"), ("Time", "concern_time"), ("Pay", "concern_pay"),
                ("Scope", "concern_scope"), ("Trust", "concern_trust"), ("Other", "concern_other")
            ])
            return
        if action.startswith("concern_"):
            if not self._is_question_step(candidate, "concern"):
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["concern"] = action.removeprefix("concern_")
            if action == "concern_other":
                candidate.answers["step"] = "awaiting_note"
                self.repository.save(candidate)
                await self.telegram.answer_callback(callback_id, "Reply with your concern")
                await self.telegram.send_free_text_prompt(
                    candidate,
                    "note",
                    f"What concern should Kairos consider for @{candidate.username}?",
                )
                return
            await self.telegram.answer_callback(callback_id, "Generating assessment")
            await self._generate(candidate)
            return
        if action == "revise":
            if candidate.status != Status.DRAFT_READY or candidate.answers.get("step") != "draft_ready":
                await self._reject_stale_callback(callback_id)
                return
            candidate.answers["step"] = "awaiting_revision"
            self.repository.save(candidate)
            await self.telegram.answer_callback(callback_id, "Reply with revision instructions")
            await self.telegram.send_free_text_prompt(
                candidate,
                "revision",
                f"What should change in the draft for @{candidate.username}?",
            )
            return
        if action == "retry_draft":
            if candidate.status != Status.EVALUATED or candidate.answers.get("step") != "generation_failed":
                await self.telegram.answer_callback(callback_id, "Nothing to retry")
                return
            await self.telegram.answer_callback(callback_id, "Retrying drafting")
            await self._generate(candidate)
            return
        if action == "approve":
            await self.telegram.answer_callback(callback_id, "Approval received")
            await self._send_approved(candidate)
            return
        await self.telegram.answer_callback(callback_id, "Unsupported action")

    @staticmethod
    def _is_question_step(candidate: Candidate, expected_step: str) -> bool:
        return candidate.status == Status.QUESTIONNAIRE and candidate.answers.get("step") == expected_step

    async def _reject_stale_callback(self, callback_id: str) -> None:
        await self.telegram.answer_callback(callback_id, "This action is no longer active")

    async def handle_text(self, text: str, *, reply_to_text: str = "") -> bool:
        if text.split(maxsplit=1)[0:1] == ["/competition"]:
            parts = text.split(maxsplit=1)
            url = parts[1].strip() if len(parts) == 2 else ""
            hosts = getattr(self.competition_screener, "hosts", ())
            if not self.competition_screener or not allowed_url(url, hosts):
                await self.telegram.notify("用法：/competition https://活動主辦頁面\n目前支援 Devpost、Kaggle、獎金獵人；不接受追蹤參數或轉址連結。")
                return True
            source = rules_urls(url, hosts)[0]
            candidate_id = "contest-" + hashlib.sha256(source.encode()).hexdigest()[:24]
            candidate = self.repository.get(candidate_id)
            if candidate and candidate.status in {Status.TELEGRAM_SENDING, Status.TELEGRAM_UNCERTAIN}:
                await self.telegram.notify("前次卡片送達結果尚未確認，請先檢查 Telegram，避免重複發送。")
                return True
            candidate = candidate or Candidate(candidate_id, "organizer", url, url, "", "/competition")
            await self.competition_screener.screen(candidate)
            if candidate.competition.get("decision") == "rejected":
                candidate.status = Status.SKIPPED
                self.repository.save(candidate)
                await self.telegram.notify("此競賽不符條件：\n" + "\n".join(candidate.risks))
                return True
            candidate.status = Status.TELEGRAM_SENDING
            self.repository.save(candidate)
            try:
                candidate.telegram_message_id = await self.telegram.send_candidate(candidate)
            except RuntimeError:
                candidate.status = Status.TELEGRAM_UNCERTAIN
            else:
                candidate.status = Status.TELEGRAM_SENT
            self.repository.save(candidate)
            return True
        waiting = self.repository.find_by_status([Status.QUESTIONNAIRE, Status.DRAFT_READY], limit=20)
        candidates = [
            candidate for candidate in waiting
            if candidate.answers.get("step") in {"awaiting_note", "awaiting_revision"}
        ]
        if not candidates:
            return False

        marker = re.search(r"\[Kairos:([^:\]]+):(note|revision)\]", reply_to_text)
        if marker:
            candidate_id, purpose = marker.groups()
            candidate = self.repository.get(candidate_id)
            expected_step = "awaiting_note" if purpose == "note" else "awaiting_revision"
            if not candidate or candidate.answers.get("step") != expected_step:
                await self.telegram.notify("This reply request is no longer active. Open the current opportunity card instead.")
                return True
        elif len(candidates) == 1:
            candidate = candidates[0]
        else:
            await self.telegram.notify("More than one opportunity is waiting. Reply directly to the relevant Kairos question.")
            return True

        step = candidate.answers.get("step")
        if step == "awaiting_note":
            candidate.answers["note"] = text.strip()[:500]
        else:
            candidate.answers["revision_note"] = text.strip()[:500]
        await self._generate(candidate)
        return True

    async def _ask_category_detail(self, candidate: Candidate) -> None:
        if candidate.category == "hackathon":
            candidate.answers["step"] = "preferred_role"
            self.repository.save(candidate)
            await self.telegram.send_question(candidate, "Which role would you prefer to own?", [
                ("Backend", "role_backend"), ("AI", "role_ai"),
                ("Product", "role_product"), ("Flexible", "role_flexible"),
            ])
            return
        if candidate.category == "internship":
            candidate.answers["step"] = "compensation_condition"
            self.repository.save(candidate)
            await self.telegram.send_question(candidate, "What compensation condition applies?", [
                ("Paid required", "compensation_paid_required"),
                ("Need details", "compensation_need_details"),
                ("Trial only", "compensation_trial_only"),
            ])
            return
        if candidate.category == "paid_project":
            candidate.answers["step"] = "engagement_preference"
            self.repository.save(candidate)
            await self.telegram.send_question(candidate, "What engagement structure fits best?", [
                ("Fixed scope", "engagement_fixed_scope"),
                ("Hourly", "engagement_hourly"),
                ("Discuss", "engagement_discuss"),
            ])
            return
        await self._ask_motivation(candidate)

    async def _ask_motivation(self, candidate: Candidate) -> None:
        candidate.answers["step"] = "motivation"
        self.repository.save(candidate)
        await self.telegram.send_question(candidate, "What is the main value?", [
            ("Resume", "motivation_resume"),
            ("Competition", "motivation_competition"),
            ("Income", "motivation_income"),
        ])

    async def _generate(self, candidate: Candidate) -> None:
        candidate.answers["step"] = "generating"
        candidate.status = Status.EVALUATED
        self.repository.save(candidate)
        try:
            result = await self.llm.assess_and_draft(candidate)
        except RuntimeError:
            candidate.answers["step"] = "generation_failed"
            candidate.status = Status.EVALUATED
            self.repository.save(candidate)
            await self.telegram.send_generation_error(candidate)
            return
        candidate.fit_score = result["fit_score"]
        candidate.interest_score = result["interest_score"]
        candidate.assessment = result["assessment"]
        candidate.draft_message = result["draft_message"]
        if not candidate.draft_message:
            candidate.status = Status.EVALUATED
            self.repository.save(candidate)
            await self.telegram.notify("Drafting is unavailable until GEMINI_API_KEY is configured.")
            return
        candidate.draft_hash = message_hash(candidate.draft_message)
        candidate.approval_hash = ""
        candidate.answers["step"] = "draft_ready"
        candidate.status = Status.DRAFT_READY
        self.repository.save(candidate)
        await self.telegram.send_draft(candidate)

    async def _send_approved(self, candidate: Candidate) -> None:
        if candidate.category == "ai_competition":
            await self.telegram.notify("競賽不支援代為聯繫、報名、付費或交件。")
            return
        if candidate.status != Status.DRAFT_READY or not candidate.draft_message:
            await self.telegram.notify("Send blocked: there is no current draft ready for approval.")
            return
        current_hash = message_hash(candidate.draft_message)
        if current_hash != candidate.draft_hash:
            await self.telegram.notify("Send blocked: the draft changed after it was displayed.")
            return
        claimed = self.repository.claim_for_send(candidate.id, current_hash, str(uuid.uuid4()))
        if not claimed:
            await self.telegram.notify("Send blocked: this draft was already claimed or is no longer current.")
            return
        candidate = claimed
        try:
            await self.dm_sender.send(candidate.username, candidate.draft_message)
        except DMUnavailable:
            candidate.status = Status.DM_UNAVAILABLE
            self.repository.save(candidate)
            await self.telegram.notify("DM unavailable. No public reply was posted.")
        except DMSenderError as exc:
            candidate.status = Status.SEND_FAILED
            self.repository.save(candidate)
            await self.telegram.notify(f"Send blocked: {exc}")
        except Exception:
            candidate.status = Status.SEND_UNCERTAIN
            self.repository.save(candidate)
            await self.telegram.notify("Send result is uncertain. It will not be retried automatically; inspect Threads first.")
        else:
            from datetime import UTC, datetime

            candidate.status = Status.SENT
            candidate.sent_at = datetime.now(UTC).isoformat()
            self.repository.save(candidate)
            await self.telegram.notify(f"Private message sent to @{candidate.username}.")
