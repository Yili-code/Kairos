import hashlib
from datetime import UTC, datetime, timedelta

from app.competitions import CompetitionScreener, evaluate
from app.models import Candidate, Status
from tests.test_competitions import SOURCES, valid_report
from tests.test_workflow import make_workflow, run_immediate


def lead(url, title="AI contest"):
    return Candidate("contest-" + hashlib.sha256(url.encode()).hexdigest()[:24], "office", title + "\n" + url,
                     url, "", "announcement:test", category="ai_competition",
                     status=Status.COMPETITION_PENDING_SCREEN)


def test_new_software_lead_and_old_backlog_both_progress_with_existing_budget():
    workflow, repo, _, _ = make_workflow()
    calls = []
    for i in range(8):
        row = lead("https://school.edu.tw/old/" + str(i))
        repo.save(row)
        row.updated_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    class Model:
        async def screen_competition(self, candidate, sources):
            calls.append(candidate.id)
            return valid_report()
    class Screener(CompetitionScreener):
        async def sources(self, text):
            return SOURCES
    fresh = [lead("https://school.edu.tw/new/" + str(i), "Software AI Hackathon") for i in range(5)]
    class Source:
        last_report = []
        async def discover(self):
            return fresh, 0
    workflow.competition_screener = Screener(Model(), ("edu.tw",))
    workflow.announcement_source = Source()
    result = run_immediate(workflow.discover(()))
    assert calls[0] == fresh[0].id
    assert calls[1:] == sorted(lead("https://school.edu.tw/old/" + str(i)).id for i in range(8))[:2]
    assert result["model_evaluations_attempted"] == 3
    assert all(repo.get(row.id) for row in fresh)
    assert result["screen_leads_created"] == 5
    assert repo.get(fresh[-1].id).screen_attempts == 0


def test_failed_new_source_does_not_prevent_old_work_and_repeated_listing_is_not_new_again():
    workflow, repo, _, _ = make_workflow()
    old = lead("https://school.edu.tw/old")
    repo.save(old)
    new = lead("https://school.edu.tw/new", "Software Hackathon")
    calls = []
    class Screener:
        hosts = ("edu.tw",)
        async def screen(self, candidate):
            calls.append(candidate.id)
            if candidate.id == new.id:
                candidate.competition = {"decision": "pending", "facts": {}, "sources": [],
                    "retry_after": (datetime.now(UTC) + timedelta(hours=4)).isoformat()}
            else:
                candidate.competition = evaluate(valid_report(), SOURCES)
    class Source:
        last_report = []
        async def discover(self):
            return [new], 0
    workflow.competition_screener = Screener()
    workflow.announcement_source = Source()
    first = run_immediate(workflow.discover(()))
    assert calls == [new.id, old.id]
    second = run_immediate(workflow.discover(()))
    assert second["screen_leads_created"] == 0 and calls == [new.id, old.id]
    assert first["screen_completed"] == 1


def test_refresh_fresh_candidate_and_backlog_share_three_model_calls():
    workflow, repo, telegram, _ = make_workflow()
    calls = []
    delivered = lead("https://school.edu.tw/delivered")
    delivered.status = Status.TELEGRAM_SENT
    delivered.telegram_message_id = 42
    repo.save(delivered)
    old = lead("https://school.edu.tw/backlog")
    repo.save(old)
    new = lead("https://school.edu.tw/fresh", "Software Hackathon")
    class Model:
        async def screen_competition(self, candidate, sources):
            calls.append(candidate.id)
            return valid_report()
    class Screener(CompetitionScreener):
        async def sources(self, text):
            return SOURCES
    class Source:
        last_report = []
        async def discover(self):
            return [new], 0
    async def edit(candidate, *, edit):
        assert edit
        return 42
    telegram.send_competition = edit
    workflow.competition_screener = Screener(Model(), ("edu.tw",))
    workflow.announcement_source = Source()
    result = run_immediate(workflow.discover(()))
    assert calls == [delivered.id, new.id, old.id]
    assert result["model_evaluations_attempted"] == 3
    assert result["card_updates_sent"] == 1


def test_retained_unattempted_software_lead_keeps_priority_after_its_discovery_round():
    workflow, repo, _, _ = make_workflow()
    old_ids = []
    for i in range(6):
        row = lead('https://school.edu.tw/generic/' + str(i))
        repo.save(row)
        row.updated_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        old_ids.append(row.id)
    retained = lead('https://school.edu.tw/retained', 'PayPal-style AI Hackathon')
    repo.save(retained)
    calls = []
    class Model:
        async def screen_competition(self, candidate, sources):
            calls.append(candidate.id)
            return valid_report()
    class Screener(CompetitionScreener):
        async def sources(self, text):
            return SOURCES
    workflow.competition_screener = Screener(Model(), ('edu.tw',))
    result = run_immediate(workflow.discover(()))
    assert calls[0] == retained.id
    assert calls[1:] == sorted(old_ids)[:2]
    assert result['model_evaluations_attempted'] == 3
