from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.dm_sender import DMUnavailable, DMSenderError
from app.competitions import allowed_url, rules_urls, CompetitionScreener
from app.competition_decisions import recommendation_identity, assessment_current
from app.profile import PROFILE
from app.llm import GeminiClient
from app.models import Candidate, Status
from app.scoring import apply_score
from app.storage import Repository, card_claimable
from app.telegram import TelegramClient, TelegramRejected
from app.threads_client import ThreadsClient, ThreadsUnavailable


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
        announcement_source: Any = None,
        competition_mailer: Any = None,
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
        self.announcement_source = announcement_source
        # A configured mailbox does not authorize automatic third-party contact.
        self.competition_mailer = None

    async def discover(self, terms: tuple[str, ...]) -> dict[str, int]:
        created: dict[str, Candidate] = {}
        errors = 0
        screened = 0
        competition_errors = 0
        competition_model_errors = 0
        competition_info_insufficient = 0
        competition_decisions = {"eligible": 0, "pending": 0, "rejected": 0}
        competition_source_errors = 0
        competition_attempts = 0
        announcement_errors = 0
        announcements_discovered = 0
        deadline = time.monotonic() + 480
        deferred_terms = 0
        attempted_competitions: set[str] = set()
        candidate_errors = 0
        rule_fetch_errors = 0
        model_rate_limited = False
        model_evaluations_attempted = 0
        search_halted = False
        def take_model_slot():
            nonlocal model_evaluations_attempted
            if model_evaluations_attempted >= self.competition_screen_limit:return False
            model_evaluations_attempted += 1
            return True
        recovered_cards = 0
        for stuck in self.repository.find_by_status([Status.TELEGRAM_SENDING], limit=100):
            try:
                started = datetime.fromisoformat(stuck.updated_at)
                stale = started.tzinfo and started < datetime.now(UTC) - timedelta(minutes=10)
            except (ValueError, TypeError):
                stale = False
            if stale and self.repository.finish_card(stuck.id, stuck.card_attempt_id, Status.TELEGRAM_UNCERTAIN,
                                                     card_last_error='interrupted_delivery'):
                recovered_cards += 1

        def recover_empty_assessment(candidate):
            if (candidate and candidate.status == Status.DISCOVERED and candidate.category == 'ai_competition'
                    and ((candidate.competition.get('decision') == 'pending'
                          and not any(fact.get('quote') for fact in candidate.competition.get('facts', {}).values()))
                         or not assessment_current(candidate.competition, PROFILE))):
                candidate.status = Status.COMPETITION_PENDING_SCREEN
                self.repository.save(candidate)
            return candidate

        async def ingest_one(candidate):
            nonlocal screened, competition_errors, competition_source_errors, competition_attempts, rule_fetch_errors, model_rate_limited, competition_model_errors, competition_info_insufficient
            existing = recover_empty_assessment(self.repository.get(candidate.id))
            if existing and existing.status not in {Status.COMPETITION_PENDING_SCREEN, Status.COMPETITION_SCREENING}:
                return
            candidate = existing or candidate
            apply_score(candidate)
            if candidate.search_term.startswith("announcement:"):
                candidate.category = "ai_competition"
            if candidate.category == "ai_competition":
                urls = rules_urls(candidate.text, getattr(self.competition_screener, "hosts", ()))
                if urls:
                    candidate.id = "contest-" + hashlib.sha256(urls[0].encode()).hexdigest()[:24]
                    canonical = recover_empty_assessment(self.repository.get(candidate.id))
                    if canonical and canonical.status not in {Status.COMPETITION_PENDING_SCREEN, Status.COMPETITION_SCREENING}:
                        return
                    candidate = canonical or candidate
                if not self.competition_screener:
                    return
                if not self.repository.get(candidate.id):
                    candidate.status = Status.COMPETITION_PENDING_SCREEN
                    if self.repository.create_if_absent(candidate):
                        created[candidate.id] = candidate
                if (model_rate_limited or model_evaluations_attempted >= self.competition_screen_limit
                        or screened >= self.competition_screen_limit
                        or candidate.id in attempted_competitions
                        or competition_attempts >= self.competition_screen_limit * 3
                        or time.monotonic() > deadline - 90):
                    return
                candidate = self.repository.claim_for_screen(candidate.id)
                if not candidate:
                    return
                attempted_competitions.add(candidate.id)
                competition_attempts += 1
                if isinstance(self.competition_screener, CompetitionScreener):
                    await self.competition_screener.screen(candidate, model_budget=take_model_slot)
                else:
                    await self.competition_screener.screen(candidate)
                model_rate_limited = candidate.competition.get('analysis_error') == 'model_rate_limited'
                rule_fetch_errors += sum(row.get('status') != 'ok' for row in candidate.competition.get('fetch_report', []))
                if candidate.competition.get("sources"):
                    screened += 1
                decision = candidate.competition.get("decision", "pending")
                competition_decisions[decision] = competition_decisions.get(decision, 0) + 1
                candidate.status = Status.DISCOVERED
                facts = candidate.competition.get("facts", {})
                if not candidate.competition.get("sources"):
                    competition_source_errors += 1
                if not any(fact.get("quote") for fact in facts.values()):
                    competition_errors += 1
                    competition_model_errors += bool(candidate.competition.get('analysis_error'))
                    competition_info_insufficient += bool(candidate.competition.get('sources') and not candidate.competition.get('analysis_error'))
                    if candidate.competition.get('decision') == 'pending':
                        candidate.status = Status.COMPETITION_PENDING_SCREEN
                if candidate.competition.get("decision") == "rejected":
                    candidate.status = Status.SKIPPED
                self.repository.save(candidate)
                if candidate.id in created:
                    created[candidate.id] = candidate
            elif self.repository.create_if_absent(candidate):
                created[candidate.id] = candidate

        async def ingest(candidate):
            nonlocal candidate_errors
            try:
                await ingest_one(candidate)
            except Exception:
                candidate_errors += 1

        updates_sent = update_errors = 0
        # Refresh at most one delivered card per run using the shared model budget.
        for delivered in self.repository.find_by_status([Status.TELEGRAM_SENT], limit=500):
            if (delivered.category != 'ai_competition' or not delivered.telegram_message_id
                    or not self.competition_screener
                    or (assessment_current(delivered.competition, PROFILE)
                        and not delivered.competition.get('update_pending'))):
                continue
            try:
                if not delivered.competition.get('update_pending'):
                    if isinstance(self.competition_screener, CompetitionScreener):
                        await self.competition_screener.screen(delivered, model_budget=take_model_slot)
                    else:
                        await self.competition_screener.screen(delivered)
                    screened += bool(delivered.competition.get('sources'))
                    delivered.competition['update_pending'] = True
                    self.repository.save(delivered)
                # Repeating an edit of the same message is safe after a lost acknowledgement.
                await self.telegram.send_competition(delivered, edit=True)
                delivered.competition['update_pending'] = False
                self.repository.save(delivered)
                updates_sent += 1
            except Exception:
                update_errors += 1
            break

        # Last-attempt order prevents fresh and repeatedly failing calls starving old work.
        backlog = self.repository.find_by_status(
            [Status.COMPETITION_PENDING_SCREEN, Status.COMPETITION_SCREENING], limit=500)
        backlog_before = len(backlog)
        for candidate in backlog:
            await ingest(candidate)
        if self.announcement_source:
            try:
                leads, announcement_errors = await self.announcement_source.discover()
            except Exception:
                leads, announcement_errors = [], 1
            announcements_discovered = len(leads)
            # Fresh explicit AI calls should not wait behind generic design-award backlog.
            for candidate in sorted(leads, key=lambda item: (
                item.search_term == 'announcement:curated',
                bool(re.search(r"\bAI\b|生成式|人工智慧", item.text, re.I))), reverse=True):
                await ingest(candidate)
        for term_index, term in enumerate(terms):
            if time.monotonic() > deadline - 40:
                deferred_terms = len(terms) - term_index
                break
            candidates = None
            for _ in range(2):
                try:
                    candidates = await self.threads.search(term, limit=self.per_term_limit)
                    break
                except ThreadsUnavailable as exc:
                    if exc.status_code in {401, 403, 429}:
                        search_halted = True
                        deferred_terms = len(terms) - term_index - 1
                        break
                except Exception:
                    continue
            if candidates is None:
                errors += 1
                if search_halted:break
                continue
            for candidate in candidates:
                await ingest(candidate)

        # Stale queued assessments return to screening without being delivered first.
        for candidate in self.repository.find_by_status([Status.DISCOVERED], limit=500):
            recover_empty_assessment(candidate)
        # Keep cards beyond this run's delivery cap in a durable queue.
        queued = {candidate.id: candidate for candidate in self.repository.find_by_status([Status.DISCOVERED], limit=100)}
        queued.update(created)
        ranked = sorted(
            (candidate for candidate in queued.values() if card_claimable(candidate) and (
                candidate.first_round_score >= self.shortlist_threshold
                if candidate.category != "ai_competition"
                else candidate.competition.get("decision") == "eligible"
                or (candidate.competition.get("decision") == "pending" and any(
                    fact.get("quote") for fact in candidate.competition.get("facts", {}).values()))
            )),
            key=lambda candidate: candidate.first_round_score,
            reverse=True,
        )
        shortlist = []
        duplicate_cards_suppressed = 0
        seen_contests = {recommendation_identity(item) for item in self.repository.find_by_status(
            [Status.TELEGRAM_SENT, Status.TELEGRAM_UNCERTAIN], limit=100) if item.category == 'ai_competition'}
        selected_contests = set()
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
            if candidate.category == 'ai_competition':
                identity = recommendation_identity(candidate)
                if identity in seen_contests:
                    candidate.status = Status.SKIPPED
                    self.repository.save(candidate)
                    duplicate_cards_suppressed += 1
                    continue
                if identity in selected_contests:
                    duplicate_cards_suppressed += 1
                    continue
            pending = candidate.category == "ai_competition" and candidate.competition.get("decision") == "pending"
            if pending and pending_selected:
                continue
            if len(shortlist) >= self.max_cards:
                break
            shortlist.append(candidate)
            if candidate.category == 'ai_competition':
                selected_contests.add(recommendation_identity(candidate))
            pending_selected = pending_selected or pending
        sent = 0
        card_errors = 0
        for candidate in shortlist:
            outcome = await self._deliver_card(candidate.id)
            sent += outcome == 'sent'
            card_errors += outcome == 'failed'
        remaining = self.repository.find_by_status(
            [Status.COMPETITION_PENDING_SCREEN, Status.COMPETITION_SCREENING], limit=500)
        from app.storage import screen_claimable
        return {
            'card_updates_sent': updates_sent,
            'card_update_errors': update_errors,
            'screen_queue_before': backlog_before,
            'screen_queue_after': len(remaining),
            'screen_queue_due': sum(screen_claimable(item) for item in remaining),
            'screen_queue_sample_saturated': int(len(remaining) >= 500),
            'announcement_source_report': getattr(self.announcement_source, 'last_report', []),
            'candidate_errors': candidate_errors,
            'competition_rule_fetch_errors': rule_fetch_errors,
            'model_rate_limited': int(model_rate_limited),
            'model_evaluations_attempted': model_evaluations_attempted,
            'search_halted': int(search_halted),
            'card_uncertain_recovered': recovered_cards,
            "discovered": len(created),
            "shortlisted": len(shortlist),
            "cards_sent": sent,
            "card_errors": card_errors,
            "search_errors": errors,
            "competitions_screened": screened,
            "duplicate_competition_cards_suppressed": duplicate_cards_suppressed,
            "competition_fetch_attempts": competition_attempts,
            "competition_errors": competition_errors,
            "competition_model_errors": competition_model_errors,
            "competition_info_insufficient": competition_info_insufficient,
            "competition_source_errors": competition_source_errors,
            "competitions_eligible": competition_decisions["eligible"],
            "competitions_pending": competition_decisions["pending"],
            "competitions_rejected": competition_decisions["rejected"],
            "announcements_discovered": announcements_discovered,
            "announcement_source_errors": announcement_errors,
            "announcement_sources_checked": len(getattr(self.announcement_source, "last_report", [])),
            "announcement_parse_failures": sum(row.get('status') == 'parse_error' for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_unreadable_pages": sum(row.get('parse_status') == 'unreadable_or_dynamic' for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_confirmed_empty_pages": sum(row.get('parse_status') == 'no_announcements' for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_no_match_pages": sum(row.get('parse_status') == 'no_matching_titles' for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_filtered_pages": sum(row.get('parse_status') == 'filtered_out' for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_cache_hits": sum(bool(row.get('from_cache')) for row in getattr(self.announcement_source, 'last_report', [])),
            "announcement_deferred_pages": sum(row.get('status') in {'cooldown','source_busy','source_paced'} for row in getattr(self.announcement_source, 'last_report', [])),
            "search_terms_deferred": deferred_terms,
        }

    async def _deliver_card(self, candidate_id):
        candidate = self.repository.claim_for_card(candidate_id)
        if not candidate:return 'not_claimed'
        attempt = candidate.card_attempt_id
        try:
            message_id = await self.telegram.send_candidate(candidate)
        except TelegramRejected as exc:
            retry = exc.retryable and candidate.card_attempts < 3
            self.repository.finish_card(candidate.id, attempt, Status.DISCOVERED if retry else Status.TELEGRAM_FAILED,
                card_retry_after=(datetime.now(UTC) + timedelta(seconds=exc.retry_after)).isoformat() if retry else '',
                card_last_error=exc.code)
            return 'failed'
        except Exception:
            self.repository.finish_card(candidate.id, attempt, Status.TELEGRAM_UNCERTAIN, card_last_error='delivery_unknown')
            return 'failed'
        completed = self.repository.finish_card(candidate.id, attempt, Status.TELEGRAM_SENT,
                                                telegram_message_id=message_id, card_retry_after='', card_last_error='')
        return 'sent' if completed else 'failed'

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

        if candidate.category == 'ai_competition' and action == 'do_it' and not assessment_current(candidate.competition, PROFILE):
            await self.telegram.answer_callback(callback_id, '評估已過期或個人條件改變，請先用 /competition 網址重新核對。')
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
                await self.telegram.notify("用法：/competition https://活動主辦頁面\n目前支援：" + ", ".join(hosts)[:400] + "\n僅接受公開頁面；請移除追蹤參數與登入憑證。")
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
            candidate.status = Status.DISCOVERED
            candidate.card_attempts = 0
            candidate.card_retry_after = ''
            candidate.card_last_error = ''
            self.repository.save(candidate)
            await self._deliver_card(candidate.id)
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
