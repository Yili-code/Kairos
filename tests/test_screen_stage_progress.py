from datetime import UTC, datetime, timedelta
import hashlib

from app.competitions import CompetitionScreener, evaluate
from app.models import Candidate, Status
from tests.test_competitions import SOURCES, valid_report
from tests.test_workflow import make_workflow, run_immediate


def row(repo, suffix):
    url = "https://school.edu.tw/" + suffix
    candidate = Candidate("contest-" + hashlib.sha256(url.encode()).hexdigest()[:24], "office", "AI contest " + url, url, "", "announcement:test", category="ai_competition", status=Status.COMPETITION_PENDING_SCREEN)
    repo.save(candidate)
    return candidate


def test_unknown_information_is_saved_without_being_counted_as_terminal_or_notified():
    workflow, repo, telegram, _ = make_workflow()
    candidate = row(repo, "unknown")
    class Model:
        async def screen_competition(self, candidate, sources):
            raw = valid_report()
            raw["facts"].pop("attendance")
            return raw
    class Screener(CompetitionScreener):
        async def sources(self, text): return SOURCES
    workflow.competition_screener = Screener(Model(), ("edu.tw",))
    result = run_immediate(workflow.discover(()))
    assert result["screen_checks_completed"] == result["screen_results_saved"] == 1
    assert result["screen_waiting_information"] == 1 and result["screen_completed"] == 0
    report = result["screen_candidate_reports"][0]
    assert report["last_successful_step"] == "result_saved"
    assert report["stop_reason"] == "awaiting_information" and report["model_calls"] == 1
    assert report["notification"] == "not_eligible" and "attendance" in report["unknown_fields"]
    assert repo.get(candidate.id).competition["screening_progress"]["result_saved"]
    assert not telegram.cards


def test_unexpected_failure_releases_claim_with_cooldown_and_other_work_completes():
    workflow, repo, telegram, _ = make_workflow()
    failed = row(repo, "failed")
    healthy = row(repo, "healthy")
    class Screener:
        hosts = ("edu.tw",)
        calls = []
        async def screen(self, candidate):
            self.calls.append(candidate.id)
            if candidate.id == failed.id:
                raise RuntimeError("private provider detail")
            raw = valid_report()
            raw["facts"]["attendance"]["value"] = "onsite"
            candidate.competition = evaluate(raw, SOURCES)
    workflow.competition_screener = screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert result["screen_completed"] == result["screen_checks_completed"] == 1
    assert result["screen_results_saved"] == 2 and result["candidate_errors"] == 1
    assert repo.get(failed.id).status == Status.COMPETITION_PENDING_SCREEN
    assert repo.get(healthy.id).status == Status.SKIPPED
    assert "private provider detail" not in str(repo.get(failed.id).to_dict())
    assert repo.get(failed.id).competition["screening_progress"]["error_type"] == "RuntimeError"
    for _ in range(5):run_immediate(workflow.discover(()))
    assert screener.calls.count(failed.id) == 1
    for _ in range(3):
        repo.get(failed.id).competition["retry_after"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        run_immediate(workflow.discover(()))
    assert screener.calls.count(failed.id) == 3
    assert repo.get(failed.id).competition["screening_progress"]["next_action"] == "manual_review"
    assert not telegram.cards


def test_stale_result_is_reported_as_conflict_not_success():
    workflow, repo, _, _ = make_workflow()
    candidate = row(repo, "conflict")
    class Screener:
        hosts = ("edu.tw",)
        async def screen(self, current):
            repo.get(current.id).answers = {"interest": "no"}
            current.competition = evaluate(valid_report(), SOURCES)
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert result["screen_result_conflicts"] == 1
    assert result["screen_checks_completed"] == result["screen_results_saved"] == 0
    assert repo.get(candidate.id).answers == {"interest": "no"}


def test_blocked_official_handoffs_cannot_consume_entire_fetch_batch():
    workflow, repo, telegram, _ = make_workflow()
    blocked = []
    for i in range(8):
        url = "https://www.contestwatchers.com/entry-" + str(i)
        candidate = Candidate("contest-" + hashlib.sha256(url.encode()).hexdigest()[:24], "office", "AI contest " + url, url, "", "announcement:test", category="ai_competition", status=Status.COMPETITION_PENDING_SCREEN)
        repo.save(candidate)
        blocked.append(candidate)
    healthy = row(repo, "later-healthy")
    class Screener:
        hosts = ("contestwatchers.com", "edu.tw")
        calls = []
        async def screen(self, candidate):
            self.calls.append(candidate.id)
            if candidate.id == healthy.id:
                raw = valid_report()
                raw["facts"]["attendance"]["value"] = "onsite"
                candidate.competition = evaluate(raw, SOURCES)
            else:
                candidate.competition = {"decision": "pending", "facts": {}, "sources": [],
                    "fetch_report": [{"url": "https://organizer.test", "status": "official_link_not_allowed", "attempts": 0}]}
    workflow.competition_screener = screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert len(screener.calls) == 3 and healthy.id in screener.calls
    assert result["screen_origin_deferred"] == 6
    assert result["screen_external_blocked"] == 2
    assert result["screen_completed"] == 1
    assert repo.get(healthy.id).status == Status.SKIPPED
    assert not telegram.cards
