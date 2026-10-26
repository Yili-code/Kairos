def test_no_purchase_is_necessary_is_entry_permission_not_free_production_tools():
    from app.competitions import evaluate
    from tests.test_competitions import valid_report, SOURCES, URL, NOW
    raw = valid_report()
    quote = 'No purchase is necessary to enter.'
    raw['facts']['registration_fee'] = {'value': 'free', 'quote': quote, 'url': URL}
    raw['estimate']['extra_tools_twd'] = None
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['registration_fee']['value'] == 'free'
    assert report['estimate']['extra_tools_twd'] is None
    assert report['decision'] == 'pending'


def test_actual_devpost_no_purchase_or_payment_clause_establishes_free_entry():
    from app.competitions import evaluate
    from tests.test_competitions import valid_report, SOURCES, URL, NOW
    quote = "NO PURCHASE OR PAYMENT NECESSARY TO ENTER OR WIN."
    raw = valid_report()
    raw['facts']['registration_fee'] = {'value': 'free', 'quote': quote, 'url': URL}
    raw['estimate']['extra_tools_twd'] = None
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['registration_fee']['value'] == 'free'
    assert report['estimate']['extra_tools_twd'] is None
    assert report['decision'] == 'pending'


def test_no_payment_for_spectators_does_not_establish_free_entry():
    from app.competitions import evaluate
    from tests.test_competitions import valid_report, SOURCES, URL, NOW
    quote = "NO PURCHASE OR PAYMENT NECESSARY TO VIEW THE EVENT."
    raw = valid_report()
    raw['facts']['registration_fee'] = {'value': 'free', 'quote': quote, 'url': URL}
    report = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote}, now=NOW)
    assert report['facts']['registration_fee']['value'] == 'unknown'
