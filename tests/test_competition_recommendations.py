from app.competitions import evaluate
from tests.test_competitions import valid_report,SOURCES,NOW,capture_card


def test_card_distinguishes_pending_research_from_starting_work_and_links_eligibility():
    report=evaluate(valid_report(),SOURCES,now=NOW)
    report['decision']='pending'
    text=capture_card(report)
    assert '待確認｜尚未確認適合投入' in text
    assert '是否值得投入' not in text
    assert text.count('>依據</a>')==3
    assert '非實測' in text
