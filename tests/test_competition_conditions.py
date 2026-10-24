from app.competition_decisions import explicit_decision_conditions
from app.competitions import evaluate
from tests.test_competitions import valid_report, SOURCES, NOW, URL, capture_card


def test_retained_ownership_does_not_hide_a_separate_marketing_licence():
    quote = ('By entering COMING NEVER, you grant AKOOL a non-exclusive, worldwide, royalty-free license '
             'to feature, display, reproduce, distribute, publish, and promote your submitted content '
             "in connection with the challenge and AKOOL's marketing and promotional activities.")
    sources = {URL: SOURCES[URL] + ' You retain ownership of your work. ' + quote}
    raw = valid_report()
    raw['facts']['rights'] = {'value': 'You retain ownership of your work.',
                             'quote': 'You retain ownership of your work.', 'url': URL}
    report = evaluate(raw, sources, now=NOW)
    assert report['decision_conditions'] == [{'kind': 'licence', 'quote': quote, 'url': URL}]
    text = capture_card(report)
    assert 'retain ownership' in text and 'royalty-free license' in text and 'marketing' in text


def test_conditional_bonus_is_visible_even_when_the_prize_fact_only_names_the_grand_prize():
    quote = 'Only premium Akool accounts will receive the $100 bonus. Each account is limited to 1 creator bonus.'
    report = evaluate(valid_report(), {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['decision_conditions'][0]['quote'] == quote
    assert '獎勵限制：Only premium' in capture_card(report)
    assert explicit_decision_conditions({URL: 'Up to $100 bonus! You retain ownership.'}) == []


def test_validated_human_only_rule_is_shown_even_if_deliverables_summary_omits_it():
    report = evaluate(valid_report(), SOURCES, now=NOW)
    quote = '文字內容須為自我創寫，不得抄襲或運用AI生成。'
    report['estimate']['production_components'] = [
        {'human_only': True, 'rule_quote': quote, 'rule_url': URL},
        {'human_only': True, 'rule_quote': 'invented', 'rule_url': 'https://untrusted.example/'},
    ]
    text = capture_card(report)
    assert '須本人完成：' + quote in text
    assert 'invented' not in text
