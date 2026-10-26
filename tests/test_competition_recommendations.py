from app.competitions import evaluate
from tests.test_competitions import valid_report,SOURCES,NOW,capture_card
from copy import deepcopy
import pytest
from app.telegram import competition_recommendation


def test_card_distinguishes_pending_research_from_starting_work_and_links_eligibility():
    report=evaluate(valid_report(),SOURCES,now=NOW)
    report['decision']='pending'
    text=capture_card(report)
    assert '\n待確認\n推薦程度：' in text
    assert '尚未確認適合投入' not in text
    assert '是否值得投入' not in text
    assert text.count('>依據</a>')==3
    assert '非實測' in text


def test_recommendation_is_a_preference_tier_not_a_qualification_or_win_probability():
    report = evaluate(valid_report(), SOURCES, now=NOW)
    original = deepcopy(report)
    assert competition_recommendation(report) == '暫不評級｜成功率資料不足'
    report['facts']['registration_fee']['value'] = 'paid'
    assert competition_recommendation(report) == '暫不評級｜成功率資料不足'
    report['decision'] = 'pending'
    report['rank'] = 999
    assert competition_recommendation(report) == '暫不評級'
    report['estimate']['total_hours'] = 12
    assert competition_recommendation(report) == '暫不評級'
    report['decision'] = 'rejected'
    assert competition_recommendation(report) == '不推薦'
    assert original['decision'] == 'eligible'


@pytest.mark.parametrize('field,value,reason', [
    ('ai_share', .49, 'AI')])
def test_known_estimate_conflicts_are_low_even_when_qualification_is_pending(field, value, reason):
    report = evaluate(valid_report(), SOURCES, now=NOW)
    report['decision'] = 'pending'
    report['estimate'][field] = value
    report['estimate']['uncertain'] = True
    assert competition_recommendation(report).startswith('低｜')
    assert reason in competition_recommendation(report)
    assert report['decision'] == 'pending'


@pytest.mark.parametrize('field,value', [('total_hours', None), ('total_hours', 0),
    ('total_hours', float('nan')), ('ai_share', True), ('ai_share', 2), ('extra_tools_twd', -1)])
def test_missing_or_invalid_estimates_do_not_get_a_positive_recommendation(field, value):
    report = evaluate(valid_report(), SOURCES, now=NOW)
    report['estimate'][field] = value
    assert competition_recommendation(report) == '暫不評級'


def test_uncertain_estimates_and_unknown_preferences_do_not_get_positive_tiers():
    report = evaluate(valid_report(), SOURCES, now=NOW)
    report['estimate']['uncertain'] = True
    assert competition_recommendation(report) == '暫不評級'
    report['estimate']['uncertain'] = False
    report['facts']['attendance']['value'] = 'unknown'
    assert competition_recommendation(report) == '暫不評級'


def test_exact_policy_boundaries_remain_eligible_for_recommendation():
    report = evaluate(valid_report(), SOURCES, now=NOW)
    report['estimate'].update(total_hours=6, ai_share=.5, extra_tools_twd=300)
    assert competition_recommendation(report) == '暫不評級｜成功率資料不足'


@pytest.mark.parametrize('field,value', [('total_hours', 30), ('extra_tools_twd', 5000)])
def test_cost_and_hours_are_not_negative_tiers_without_return_evidence(field, value):
    report = evaluate(valid_report(), SOURCES, now=NOW)
    report['estimate'][field] = value
    assert competition_recommendation(report) == '暫不評級｜成功率資料不足'
