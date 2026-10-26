import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest

from app.economics import CBC_URL, ExchangeReference, cbc_reference, economic_review, money
from app.fetch_policy import PublicFetcher
from app.competitions import CompetitionScreener
from app.models import Candidate

NOW = datetime(2026, 10, 26, 4, tzinfo=UTC)
URL = 'https://sample.devpost.com/rules'


def report():
    return {'sources': [URL], 'facts': {
        'prize': {'value': 'US$1,000', 'quote': 'The first place cash award is US$1,000.', 'url': URL},
        'prize_kind': {'value': 'cash', 'quote': 'The first place cash award is US$1,000.', 'url': URL},
        'registration_fee': {'value': 'free', 'quote': 'Entry is free.', 'url': URL}},
        'estimate': {'total_hours': 10, 'extra_tools_twd': 500, 'uncertain': False}}


def reference():
    return cbc_reference(json.dumps([{'日期': '20261022', 'NTD_USD': '32.508'}]), now=NOW)


def test_cost_scenarios_are_not_personal_wages_or_estimated_winning_probabilities():
    data = report(); original = deepcopy(data)
    result = economic_review(data, reference(), now=NOW)
    assert [row['cost_twd'] for row in result['scenarios']] == [3500, 6500, 10500]
    assert result['scenarios'][0]['break_even_probability'] == pytest.approx(3500/32508)
    assert result['success_probability'] is result['expected_net_return'] is None
    assert result['time_values_are_personal_wage'] is False
    assert result['includes_tax_and_transfer_fees'] is False and data == original


@pytest.mark.parametrize('value', ['USD -1000', '-US$1000', 'USD 1e3', '$1000', 'USD1000 and USD2000',
                                  'USD 1000 prize pool', 'TWD 1,0,0', 'US$1000 and TWD1000'])
def test_ambiguous_negative_mixed_and_pool_amounts_are_not_single_cash_awards(value):
    assert money(value) is None


def test_quoted_currency_and_amount_must_support_the_listed_award():
    data = report(); data['facts']['prize']['value'] = 'USD 10000'
    result = economic_review(data, reference(), now=NOW)
    assert result['award_twd_reference'] is None
    assert all(row['break_even_probability'] is None for row in result['scenarios'])


def test_paid_entry_is_added_to_tools_and_time_without_guessing_unknown_fees():
    data = report()
    data['facts']['registration_fee']['value'] = 'paid'
    result = economic_review(data, reference(), now=NOW)
    assert result['scenarios'] == []
    data['facts']['registration_amount'] = {'value': 'USD 10', 'quote': 'The entry fee is USD 10.', 'url': URL}
    result = economic_review(data, reference(), now=NOW)
    assert result['scenarios'][0]['cost_twd'] == pytest.approx(3825.08)


def test_stale_missing_and_conflicting_currency_references_do_not_produce_thresholds():
    assert cbc_reference('[{"日期":"20260101","NTD_USD":"32"}]', now=NOW)['status'] == 'stale_or_unavailable'
    assert cbc_reference('[{"日期":"20261022","NTD_USD":"32"},{"日期":"20261022","NTD_USD":"33"}]', now=NOW)['status'] == 'conflicting_exchange_reference'
    stale = reference(); stale['checked_at'] = (NOW-timedelta(days=2)).isoformat()
    result = economic_review(report(), stale, now=NOW)
    assert result['scenarios'] and all(row['break_even_probability'] is None for row in result['scenarios'])


def test_domestic_award_needs_no_exchange_source_and_thresholds_are_not_clamped():
    data = report(); data['facts']['prize'] = {'value': '新台幣1,000', 'quote': '首獎新台幣1,000元。', 'url': URL}
    result = economic_review(data, now=NOW)
    assert result['scenarios'][0]['break_even_probability'] == 3.5
    assert result['success_probability'] is None


def test_exchange_failure_is_isolated_and_only_exact_public_endpoint_is_requested():
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    async def check():
        async def fetch(client, url, allowed):
            from app.public_fetch import fetch_public
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as active:
                return await fetch_public(active, url, allowed)
        snapshot = await ExchangeReference(fetch).snapshot()
        assert snapshot['status'] == 'redirect_blocked'
    asyncio.run(check())
    assert calls == [CBC_URL]


def test_actual_documented_cbc_shape_is_read_under_shared_fetch_limits():
    async def check():
        async def fetch(client, url, allowed):
            from app.public_fetch import fetch_public
            def response(request):
                return httpx.Response(200, headers={'content-type':'application/json'},
                    json=[{'日期':datetime.now(UTC).strftime('%Y%m%d'), 'NTD_USD':'32.508'}])
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as active:
                return await fetch_public(active,url,allowed)
        result = await ExchangeReference(fetch).snapshot()
        assert result['status'] == 'ok' and result['source'] == CBC_URL
    asyncio.run(check())


def test_monetary_overflow_does_not_turn_break_even_probability_into_zero():
    assert money('USD ' + '9'*500) is None


def test_a_prize_quote_cannot_establish_an_entry_fee():
    data = report();data['facts']['registration_fee']['value'] = 'paid'
    data['facts']['registration_amount'] = {'value':'USD 10', 'quote':'The cash award is USD 10.', 'url':URL}
    assert economic_review(data, reference(), now=NOW)['scenarios'] == []


def test_boolean_exchange_values_do_not_become_numeric_currency_rates():
    assert cbc_reference('[{"日期":"20261022","NTD_USD":true}]',now=NOW)['status'] == 'stale_or_unavailable'


def test_small_positive_break_even_threshold_is_not_displayed_as_zero():
    from app.competitions import evaluate
    from tests.test_competitions import valid_report, SOURCES, NOW as FIXTURE_NOW, capture_card
    data=evaluate(valid_report(),SOURCES,now=FIXTURE_NOW)
    url=next(iter(SOURCES))
    data['facts']['prize']={'value':'NT$1000000000','quote':'The first cash award is NT$1000000000.','url':url}
    text=capture_card(data)
    assert '&lt;0.1%' in text and '回本門檻 0.0%' not in text
