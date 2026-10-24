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


def test_ai_film_directory_discovers_platform_links_without_using_directory_as_rules():
    body = '''<a href="https://filmfreeway.com/new">AI Film Festival 2026</a>
    <a href="/contest/new">AI Film Contest details</a>
    <a href="#browse">AI Film Competitions</a>'''
    rows = entries(body, "https://aifilmcontests.com/", ("aifilmcontests.com", "filmfreeway.com"))
    assert [row.permalink for row in rows] == ["https://filmfreeway.com/new"]
    assert rows[0].competition == {}


def test_recap_and_listing_self_links_do_not_become_contests():
    body = '''<a href="/">Creative Design Competition Directory</a>
    <a href="/recap">文學獎 評審肯定多元題材</a>
    <a href="/open">AI書法比賽開放報名</a>'''
    assert [row.permalink for row in entries(body, 'https://campus.edu.tw/', HOSTS)] == ['https://campus.edu.tw/open']


def test_large_realistic_directory_is_read_but_unbounded_page_is_rejected():
    async def check(size):
        body = '<a href="/entry">AI Film Festival</a>' + ' ' * size
        source = AnnouncementSource((BASE,), HOSTS, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={'content-type': 'text/html'}, text=body)))
        return await source.discover()
    rows, errors = asyncio.run(check(635574))
    assert len(rows) == 1 and errors == 0
    rows, errors = asyncio.run(check(1_000_000))
    assert rows == [] and errors == 1


def test_one_failed_board_does_not_hide_other_boards_and_no_redirect_is_followed():
    def handler(request):
        if request.url.path == "/bad":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text='<a href="/contest">AI video competition</a>')

    source = AnnouncementSource(("https://campus.edu.tw/bad", BASE), HOSTS, transport=httpx.MockTransport(handler))
    rows, errors = asyncio.run(source.discover())
    assert errors == 1 and len(rows) == 1
    assert [item["status"] for item in source.last_report] == ["redirect_blocked", "ok"]


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
    assert allowed_url("https://tkutimes.tku.edu.tw/dtl.aspx?no=60832", HOSTS)
    assert allowed_url("https://cart.ntua.edu.tw/web/news/news_in.jsp?dm_no=DM1560757140522&np_no=NP1791778067267", HOSTS)
    assert not allowed_url("https://campus.edu.tw/?token=private", HOSTS)
    assert not allowed_url("https://campus.edu.tw/?Lang=zh-tw&lang=en", HOSTS)
    assert not allowed_url("https://cse.ntou.edu.tw/app/index.php?Action=delete&Type=mobile_rcg_mstr&Nbr=1", HOSTS)


def test_text_pdf_is_read_but_malformed_and_excessive_documents_stay_unknown():
    assert "AI generation is allowed" in pdf_text(text_pdf())
    assert pdf_text(b"not a PDF") == ""
    assert pdf_text(text_pdf(pages=21)) == TRUNCATED_MARKER


def test_campus_html_pdf_attachments_are_fetched_within_document_budget():
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=text_pdf())
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text='<p>Official contest announcement</p><a href="/rules.pdf">簡章</a><a href="/more.pdf">更多</a>')

    screener = CompetitionScreener(None, HOSTS, transport=httpx.MockTransport(handler))
    sources = asyncio.run(screener.sources("https://campus.edu.tw/entry"))
    assert len(fetched) == 3
    assert "AI generation is allowed" in sources["https://campus.edu.tw/rules.pdf"]


def test_related_rule_pages_cover_terms_and_deadlines_with_a_four_document_cap():
    fetched = []
    def handler(request):
        fetched.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='''<p>Official rules</p>
            <a href="/enter">Enter</a><a href="/rules">Rules</a><a href="/faq">FAQ</a>
            <a href="/timeline">Timeline</a><a href="/terms">Terms</a>
            <a href="https://evil.test/terms">Other terms</a>''')
    screener = CompetitionScreener(None, HOSTS, transport=httpx.MockTransport(handler))
    sources = asyncio.run(screener.sources('https://campus.edu.tw/rules'))
    assert fetched == ['https://campus.edu.tw/rules', 'https://campus.edu.tw/terms',
                       'https://campus.edu.tw/timeline', 'https://campus.edu.tw/enter']
    assert len(sources) == 4


def test_new_ai_call_is_screened_before_generic_backlog_and_fetch_failure_is_counted():
    workflow, repo, _, _ = make_workflow()
    workflow.competition_screen_limit = 1
    repo.save(Candidate('old', 'office', 'design competition', BASE + 'old', '', 'announcement:' + BASE,
                        category='ai_competition', status=Status.COMPETITION_PENDING_SCREEN))
    class Source:
        async def discover(self):
            return [Candidate('new', 'office', 'AI Film Festival', BASE + 'new', '', 'announcement:' + BASE)], 0
    calls = []
    class Screener:
        hosts = HOSTS
        async def screen(self, candidate):
            calls.append(candidate.permalink)
            candidate.competition = {'decision': 'pending', 'facts': {'ai_policy': {'value': 'unknown', 'quote': ''}}, 'sources': []}
    workflow.announcement_source, workflow.competition_screener = Source(), Screener()
    result = run_immediate(workflow.discover(()))
    assert calls == [BASE + 'new', BASE + 'old']
    assert result['competitions_pending'] == 2
    assert result['competition_errors'] == result['competition_source_errors'] == 2
    assert result['competitions_screened'] == 0
    assert result['competition_fetch_attempts'] == 2
    assert result['cards_sent'] == 0


def test_blocked_sources_have_a_separate_bounded_fetch_budget():
    workflow, _, _, _ = make_workflow()
    workflow.competition_screen_limit = 1
    class Source:
        async def discover(self):
            return [Candidate(str(i), 'office', 'AI Film Festival', BASE + str(i), '', 'announcement:' + BASE)
                    for i in range(10)], 0
    class Screener:
        hosts = HOSTS
        async def screen(self, candidate):
            candidate.competition = {'decision': 'pending', 'facts': {}, 'sources': []}
    workflow.announcement_source, workflow.competition_screener = Source(), Screener()
    result = run_immediate(workflow.discover(()))
    assert result['competition_fetch_attempts'] == result['competition_source_errors'] == 3
    assert result['competitions_screened'] == result['cards_sent'] == 0


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
