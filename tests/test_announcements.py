import asyncio
from datetime import UTC, datetime, timedelta
import io

import httpx

from app.announcements import AnnouncementSource, entries
from app.competitions import CompetitionScreener, TRUNCATED_MARKER, allowed_url, pdf_text
from app.models import Candidate, Status
from app.storage import InMemoryRepository
from tests.test_workflow import make_workflow, run_immediate


HOSTS = ("edu.tw", "gov.tw")
BASE = "https://campus.edu.tw/news/"


def text_pdf(text="Substantial AI generation is allowed.", pages=1):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 300 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_campus_html_titles_and_urls_are_deduplicated_and_not_assumed_low_competition():
    body = '''<a href="/entry?Lang=zh-tw" title="AI 影片競賽">AI 影片競賽</a>
    <a href="/entry?Lang=zh-tw">AI 影片競賽</a>
    <a href="/awards">AI 影片競賽得獎名單</a>
    <a href="/sport">籃球競賽</a><a href="https://evil.test/entry">AI 影片競賽</a>'''
    rows = entries(body, BASE, HOSTS)
    assert len(rows) == 1
    assert rows[0].text.splitlines()[0] == "AI 影片競賽"
    assert rows[0].search_term.startswith("announcement:")
    assert rows[0].competition == {}


def test_public_rss_and_atom_are_supported_without_executing_embedded_content():
    rss = '<?xml version="1.0"?><rss><channel><item><title>Student AI video contest</title><link>https://campus.edu.tw/contest</link></item></channel></rss>'
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI design competition</title><link href="https://campus.edu.tw/contest"/></entry></feed>'
    assert len(entries(rss, BASE, HOSTS)) == 1
    assert len(entries(atom, BASE, HOSTS)) == 1


def test_one_failed_board_does_not_hide_other_boards_and_no_redirect_is_followed():
    def handler(request):
        if request.url.path == "/bad":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text='<a href="/contest">AI video competition</a>')

    source = AnnouncementSource(("https://campus.edu.tw/bad", BASE), HOSTS, transport=httpx.MockTransport(handler))
    rows, errors = asyncio.run(source.discover())
    assert errors == 1 and len(rows) == 1
    assert [item["status"] for item in source.last_report] == ["HTTPStatusError", "ok"]


def test_more_than_twelve_boards_rotate_by_half_day(monkeypatch):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, headers={"content-type": "text/html"}, text="empty"))
    urls = tuple(f"https://campus.edu.tw/board{i}" for i in range(13))
    source = AnnouncementSource(urls, HOSTS, transport=transport)
    monkeypatch.setattr("app.announcements.time.time", lambda: 0)
    asyncio.run(source.discover())
    assert len(source.last_report) == 12
    monkeypatch.setattr("app.announcements.time.time", lambda: 43200)
    asyncio.run(source.discover())
    assert [item["url"] for item in source.last_report] == [urls[-1]]


def test_safe_cms_navigation_is_allowed_but_actions_and_duplicate_keys_are_not():
    assert allowed_url("https://campus.edu.tw/p/406-1.php?Lang=zh-tw", HOSTS)
    assert allowed_url("https://news.gov.tw/item?id=123&module=news", HOSTS)
    assert not allowed_url("https://campus.edu.tw/?token=private", HOSTS)
    assert not allowed_url("https://campus.edu.tw/?Lang=zh-tw&lang=en", HOSTS)
    assert not allowed_url("https://cse.ntou.edu.tw/app/index.php?Action=delete&Type=mobile_rcg_mstr&Nbr=1", HOSTS)


def test_text_pdf_is_read_but_malformed_and_excessive_documents_stay_unknown():
    assert "AI generation is allowed" in pdf_text(text_pdf())
    assert pdf_text(b"not a PDF") == ""
    assert pdf_text(text_pdf(pages=21)) == TRUNCATED_MARKER


def test_campus_html_pdf_attachment_is_fetched_within_two_document_budget():
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=text_pdf())
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text='<p>Official contest announcement</p><a href="/rules.pdf">簡章</a><a href="/more.pdf">更多</a>')

    screener = CompetitionScreener(None, HOSTS, transport=httpx.MockTransport(handler))
    sources = asyncio.run(screener.sources("https://campus.edu.tw/entry"))
    assert len(fetched) == 2
    assert "AI generation is allowed" in sources["https://campus.edu.tw/rules.pdf"]


def test_screening_claim_blocks_overlap_and_recovers_expired_lease():
    repo = InMemoryRepository()
    candidate = Candidate("c", "x", "AI contest", BASE, "", "contest", status=Status.COMPETITION_PENDING_SCREEN)
    repo.save(candidate)
    assert repo.claim_for_screen("c") is not None
    assert repo.claim_for_screen("c") is None
    candidate.updated_at = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    assert repo.claim_for_screen("c") is not None


def test_detached_firestore_style_records_are_delivered_after_screening():
    class DetachedRepo(InMemoryRepository):
        def get(self, key):
            candidate = super().get(key)
            return Candidate.from_dict(candidate.to_dict()) if candidate else None

    class Source:
        async def discover(self):
            return [Candidate("c", "office", "AI video contest", "https://campus.edu.tw/entry", "", "announcement:" + BASE)], 0

    class Screener:
        hosts = HOSTS

        async def screen(self, candidate):
            candidate.category = "ai_competition"
            candidate.first_round_score = 90
            candidate.competition = {"decision": "eligible", "facts": {"ai_policy": {"value": "broad_allowed"}}}

    workflow, _, telegram, sender = make_workflow()
    workflow.repository = DetachedRepo()
    workflow.announcement_source = Source()
    workflow.competition_screener = Screener()
    result = run_immediate(workflow.discover(()))
    assert result["announcements_discovered"] == 1 and result["cards_sent"] == 1
    assert sender.sent == []


def test_time_budget_preserves_new_leads_and_reports_unattempted_search_terms(monkeypatch):
    clock = [0]
    monkeypatch.setattr("app.workflow.time.monotonic", lambda: clock[0])

    class SlowSource:
        async def discover(self):
            clock[0] = 450
            return [Candidate("c", "office", "AI video contest", "https://campus.edu.tw/entry", "", "announcement:" + BASE)], 0

    class Screener:
        hosts = HOSTS

        async def screen(self, candidate):
            raise AssertionError("An analysis must not start without enough remaining time")

    workflow, repo, telegram, _ = make_workflow()
    workflow.announcement_source, workflow.competition_screener = SlowSource(), Screener()
    result = run_immediate(workflow.discover(("AI contest", "video contest")))
    assert result["search_terms_deferred"] == 2
    assert result["competitions_screened"] == 0
    assert len(repo.find_by_status([Status.COMPETITION_PENDING_SCREEN])) == 1
