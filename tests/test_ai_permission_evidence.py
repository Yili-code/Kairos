import pytest

from app.competitions import evaluate
from tests.test_competitions import valid_report, SOURCES, URL, NOW


@pytest.mark.parametrize("quote", [
    "Entrants must build or update an application that integrates the PayPal developer platform along with an AI tool, model, or platform of their choice.",
    "The hackathon project must use AI and machine learning APIs in its functionality.",
    "Build the next frontier of AI on open infrastructure.",
])
def test_observed_ai_product_requirement_does_not_grant_ai_authorship(quote):
    raw = valid_report()
    raw['facts']['ai_policy'] = {'value': 'broad_allowed', 'quote': quote, 'url': URL}
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['ai_policy']['value'] == 'unknown'
    assert report['fact_diagnostics']['ai_policy'] == 'missing_explicit_ai_creation_permission'
    assert report['decision'] == 'pending'


@pytest.mark.parametrize("quote", [
    "AI-generated and AI-assisted work is eligible.",
    "Substantial AI generation is allowed.",
    "Use any AI tools you like: coding agents, asset generation, audio, writing, anything.",
    "Entrants may use AI to generate code and artwork for their submission.",
    "本競賽作品圖像與影片可應用生成式 AI 工具，文字說明需自行撰寫。",
    "允許使用 AI 生成圖像與製作影片，請揭露使用工具。",
])
def test_explicit_creation_permission_keeps_component_restrictions_for_evaluation(quote):
    raw = valid_report()
    raw['facts']['ai_policy'] = {'value': 'broad_allowed', 'quote': quote, 'url': URL}
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['ai_policy']['value'] == 'broad_allowed'


@pytest.mark.parametrize("quote", [
    "AI-generated content is not allowed in submissions.",
    "You may not use AI to generate code for this submission.",
    "Do not create the work using AI tools.",
    "AI-generated work is prohibited even if tools are useful for learning.",
    "不得使用 AI 生成圖像與製作影片。",
])
def test_model_cannot_turn_a_sourced_creation_ban_into_broad_permission(quote):
    raw = valid_report()
    raw['facts']['ai_policy'] = {'value': 'broad_allowed', 'quote': quote, 'url': URL}
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['ai_policy']['value'] == 'unknown'
    assert report['decision'] == 'pending'
