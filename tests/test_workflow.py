from __future__ import annotations

from app.dm_sender import DisabledDMSender, SendReceipt
from app.models import Candidate, Status
from app.storage import InMemoryRepository
from app.workflow import Workflow, message_hash


class FakeThreads:
    async def search(self, query: str, *, limit: int = 20):
        return [Candidate("1", "builder", "Remote AI hackathon looking for a Python teammate. DM me.", "https://example.test/1", "", query)]


class FakeTelegram:
    def __init__(self) -> None:
        self.cards = []
        self.questions = []
        self.drafts = []
        self.notifications = []
        self.callbacks = []
        self.free_text_prompts = []
        self.generation_errors = []

    async def send_candidate(self, candidate):
        self.cards.append(candidate.id)
        return 101
    async def send_question(self, candidate, question, options): self.questions.append((candidate.id, question, options))
    async def send_draft(self, candidate): self.drafts.append(candidate.draft_message)
    async def send_free_text_prompt(self, candidate, purpose, question): self.free_text_prompts.append((candidate.id, purpose, question))
    async def send_generation_error(self, candidate): self.generation_errors.append(candidate.id)
    async def notify(self, text): self.notifications.append(text)
    async def answer_callback(self, callback_id, text): self.callbacks.append((callback_id, text))


class FailingCardTelegram(FakeTelegram):
    async def send_candidate(self, candidate):
        self.cards.append(candidate.id)
        raise RuntimeError("telegram response was not confirmed")


class FakeLLM:
    async def assess_and_draft(self, candidate):
        return {
            "fit_score": 82,
            "interest_score": int(candidate.answers.get("interest", "4")),
            "assessment": "Strong scope fit; verify expected weekly commitment.",
            "language": "en",
            "draft_message": "Hi, I am interested in the hackathon. What scope and weekly commitment do you expect?",
        }


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, username, message):
        self.sent.append((username, message))
        return SendReceipt("sent", "ok")


class FailingLLM:
    async def assess_and_draft(self, candidate):
        raise RuntimeError("provider unavailable")


def make_workflow(sender=None):
    repo = InMemoryRepository()
    telegram = FakeTelegram()
    sender = sender or FakeSender()
    workflow = Workflow(repo, FakeThreads(), telegram, FakeLLM(), sender, shortlist_threshold=55, per_term_limit=20, max_cards=3)
    return workflow, repo, telegram, sender


def run_immediate(coroutine):
    """Drive fake-I/O coroutines without opening sockets in restricted Windows CI."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Test coroutine unexpectedly waited on real asynchronous I/O")


def test_discovery_deduplicates_and_sends_one_card() -> None:
    workflow, repo, telegram, _ = make_workflow()
    first = run_immediate(workflow.discover(("hackathon",)))
    second = run_immediate(workflow.discover(("hackathon",)))
    assert first["cards_sent"] == 1
    assert second["cards_sent"] == 0
    assert telegram.cards == ["1"]
    assert repo.get("1").status == Status.TELEGRAM_SENT
    assert repo.get("1").telegram_message_id == 101


def test_uncertain_card_delivery_is_recorded_without_automatic_resend() -> None:
    workflow, repo, _, _ = make_workflow()
    telegram = FailingCardTelegram()
    workflow.telegram = telegram

    first = run_immediate(workflow.discover(("hackathon",)))
    second = run_immediate(workflow.discover(("hackathon",)))

    assert first["cards_sent"] == 0
    assert first["card_errors"] == 1
    assert second["cards_sent"] == 0
    assert second["card_errors"] == 0
    assert telegram.cards == ["1"]
    assert repo.get("1").status == Status.TELEGRAM_UNCERTAIN
    assert repo.get("1").telegram_message_id is None


def test_exact_displayed_draft_can_be_approved_and_sent() -> None:
    workflow, repo, telegram, sender = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.DRAFT_READY)
    candidate.draft_message = "Current draft"
    candidate.draft_hash = message_hash(candidate.draft_message)
    repo.save(candidate)
    run_immediate(workflow.handle_callback("cb", "q:1:approve"))
    assert sender.sent == [("builder", "Current draft")]
    assert repo.get("1").status == Status.SENT
    run_immediate(workflow.handle_callback("cb2", "q:1:approve"))
    assert sender.sent == [("builder", "Current draft")]


def test_changed_draft_is_blocked() -> None:
    workflow, repo, telegram, sender = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.DRAFT_READY)
    candidate.draft_message = "Changed after preview"
    candidate.draft_hash = message_hash("Original preview")
    repo.save(candidate)
    run_immediate(workflow.handle_callback("cb", "q:1:approve"))
    assert sender.sent == []
    assert repo.get("1").status == Status.DRAFT_READY
    assert "draft changed" in telegram.notifications[-1]


def test_disabled_sender_fails_closed() -> None:
    workflow, repo, telegram, _ = make_workflow(DisabledDMSender())
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.DRAFT_READY)
    candidate.draft_message = "Approved draft"
    candidate.draft_hash = message_hash(candidate.draft_message)
    repo.save(candidate)
    run_immediate(workflow.handle_callback("cb", "q:1:approve"))
    assert repo.get("1").status == Status.SEND_FAILED
    assert "disabled" in telegram.notifications[-1]


def test_free_text_reply_is_bound_to_the_replied_candidate() -> None:
    workflow, repo, telegram, _ = make_workflow()
    first = Candidate("1", "first", "post", "url", "", "hackathon", status=Status.QUESTIONNAIRE)
    first.answers["step"] = "awaiting_note"
    second = Candidate("2", "second", "post", "url", "", "hackathon", status=Status.QUESTIONNAIRE)
    second.answers["step"] = "awaiting_note"
    repo.save(first)
    repo.save(second)

    handled = run_immediate(workflow.handle_text(
        "Need clearer ownership.",
        reply_to_text="What concern should Kairos consider?\n\n[Kairos:1:note]",
    ))

    assert handled is True
    assert repo.get("1").answers["note"] == "Need clearer ownership."
    assert repo.get("1").status == Status.DRAFT_READY
    assert repo.get("2").answers.get("note") is None


def test_ambiguous_free_text_does_not_mutate_any_candidate() -> None:
    workflow, repo, telegram, _ = make_workflow()
    for candidate_id in ("1", "2"):
        candidate = Candidate(candidate_id, "builder", "post", "url", "", "hackathon", status=Status.QUESTIONNAIRE)
        candidate.answers["step"] = "awaiting_note"
        repo.save(candidate)

    handled = run_immediate(workflow.handle_text("This is ambiguous."))

    assert handled is True
    assert all(repo.get(candidate_id).answers.get("note") is None for candidate_id in ("1", "2"))
    assert "Reply directly" in telegram.notifications[-1]


def test_hackathon_questionnaire_asks_for_preferred_role() -> None:
    workflow, repo, telegram, _ = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", category="hackathon", status=Status.QUESTIONNAIRE)
    candidate.answers["step"] = "capacity"
    repo.save(candidate)

    run_immediate(workflow.handle_callback("cb", "q:1:capacity_fits"))

    assert repo.get("1").answers["step"] == "preferred_role"
    assert telegram.questions[-1][1] == "Which role would you prefer to own?"


def test_generation_failure_is_recoverable_without_losing_answers() -> None:
    workflow, repo, telegram, _ = make_workflow()
    workflow.llm = FailingLLM()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.QUESTIONNAIRE)
    candidate.answers = {"interest": "5", "step": "awaiting_note"}
    repo.save(candidate)

    handled = run_immediate(workflow.handle_text("Need a clear role."))

    assert handled is True
    stored = repo.get("1")
    assert stored.status == Status.EVALUATED
    assert stored.answers["step"] == "generation_failed"
    assert stored.answers["note"] == "Need a clear role."
    assert telegram.generation_errors == ["1"]


def test_retry_draft_is_blocked_without_a_failed_generation() -> None:
    workflow, repo, telegram, _ = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.DRAFT_READY)
    repo.save(candidate)

    run_immediate(workflow.handle_callback("cb", "q:1:retry_draft"))

    assert telegram.callbacks[-1] == ("cb", "Nothing to retry")


def test_duplicate_start_callback_does_not_restart_questionnaire() -> None:
    workflow, repo, telegram, _ = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.TELEGRAM_SENT)
    repo.save(candidate)

    run_immediate(workflow.handle_callback("cb1", "q:1:start"))
    run_immediate(workflow.handle_callback("cb2", "q:1:start"))

    assert repo.get("1").answers["step"] == "interest"
    assert len(telegram.questions) == 1
    assert telegram.callbacks[-1] == ("cb2", "This action is no longer active")


def test_stale_skip_cannot_overwrite_a_sent_candidate() -> None:
    workflow, repo, telegram, _ = make_workflow()
    candidate = Candidate("1", "builder", "post", "url", "", "hackathon", status=Status.SENT)
    repo.save(candidate)

    run_immediate(workflow.handle_callback("cb", "q:1:skip"))

    assert repo.get("1").status == Status.SENT
    assert telegram.callbacks[-1] == ("cb", "This action is no longer active")
