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
    assert 'retain ownership' in text and '免權利金' in text and '行銷宣傳' in text
    assert '非專屬' in text and '全球' in text and '複製' in text and '散布' in text


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


def test_mixed_prize_headline_is_not_presented_as_a_verified_cash_amount():
    quote = ('Grand Prize $50,000 Includes: Cash Award AKOOL Membership / Credits '
             'Official AKOOL Creator Recognition Featured Filmmaker Spotlight Featured Case Study')
    raw = valid_report()
    raw['facts']['prize'] = {'value': '$50,000', 'quote': quote, 'url': URL}
    sources = {URL: SOURCES[URL] + ' ' + quote}
    report = evaluate(raw, sources, now=NOW)
    assert report['facts']['prize']['value'] == 'unknown'
    assert report['decision'] == 'pending'
    assert report['fact_diagnostics']['prize'] == 'mixed_prize_package_cash_breakdown_unknown'
    assert '現金拆分待確認' in capture_card(report)


def test_explicit_top_logo_requirement_survives_a_short_deliverables_summary():
    quote = 'The AKOOL logo MUST BE prominently displayed at the top of the video.'
    report = evaluate(valid_report(), {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert '交件限制：' + quote in capture_card(report)


def test_conditional_licence_is_not_summarized_as_unconditional_permission():
    from app.telegram import licence_highlights
    quote='By entering, you grant a non-exclusive worldwide licence subject to a separate agreement.'
    assert licence_highlights(quote)==quote


def test_compact_licence_does_not_reverse_nontransferable_or_negated_rights():
    from app.telegram import licence_highlights
    result=licence_highlights('By entering, you grant a non-exclusive worldwide non-transferable licence.')
    assert '不可轉讓' in result and '含轉讓' not in result
    for quote in ['A non-exclusive worldwide licence with no sublicensing.',
                  'A non-exclusive worldwide licence plus an exclusive option.']:
        assert licence_highlights(quote)==quote
