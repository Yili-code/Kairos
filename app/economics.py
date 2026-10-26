"""Conditional cost comparisons; break-even thresholds are never winning probabilities."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import re

import httpx
from app.competition_policy import COMPETITION_POLICY

CBC_URL = "https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day"


def money(value):
    if not isinstance(value, str):
        return None
    currencies = set()
    for code, pattern in {'TWD': r'NT\$|TWD|NTD|新[臺台]幣', 'USD': r'US\$|USD|美元|美金'}.items():
        if re.search(pattern, value, re.I):
            currencies.add(code)
    numeric_text = re.sub(r'NT\$|US\$|TWD|NTD|USD|新[臺台]幣|美元|美金', ' ', value, flags=re.I)
    if re.search(r'[-−]\s*\d|\d[eE][+-]?\d', numeric_text):
        return None
    amounts = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', numeric_text)
    if len(currencies) != 1 or len(amounts) != 1 or re.search(r'總獎金|獎金池|prize pool|in prizes|total prizes', value, re.I):
        return None
    try:
        amount = Decimal(amounts[0].replace(',', ''))
        if re.search(r'萬元', value):
            amount *= 10000
        if not amount.is_finite() or amount < 0:
            return None
        converted = float(amount)
        if not math.isfinite(converted):
            return None
        return {'amount': converted, 'currency': currencies.pop()}
    except (InvalidOperation, OverflowError):
        return None


def cbc_reference(body, *, now=None):
    now = now or datetime.now(UTC)
    rows = json.loads(body)
    if not isinstance(rows, list) or len(rows) > 20000:
        raise ValueError('Invalid exchange reference')
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    quotes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            day = datetime.strptime(row['日期'], '%Y%m%d').date()
            if isinstance(row['NTD_USD'], bool):
                continue
            rate = float(row['NTD_USD'])
            if math.isfinite(rate) and 0 < rate < 1000 and today - timedelta(days=7) <= day <= today:
                quotes.append((day, rate))
        except (KeyError, ValueError, TypeError):
            continue
    if not quotes:
        return {'status': 'stale_or_unavailable', 'source': CBC_URL}
    day = max(item[0] for item in quotes)
    rates = {rate for stamp, rate in quotes if stamp == day}
    if len(rates) != 1:
        return {'status': 'conflicting_exchange_reference', 'source': CBC_URL}
    rate = rates.pop()
    return {'status': 'ok', 'twd_per_usd': rate, 'reference_date': day.isoformat(),
            'source': CBC_URL, 'checked_at': now.isoformat(), 'basis': 'interbank_closing_reference'}


class ExchangeReference:
    def __init__(self, fetcher):
        self.fetcher = fetcher

    async def snapshot(self):
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            page = await self.fetcher(client, CBC_URL, lambda target: target == CBC_URL)
        if page.status != 'ok':
            return {'status': page.status, 'source': CBC_URL}
        try:
            return cbc_reference(page.text())
        except (ValueError, TypeError):
            return {'status': 'invalid_exchange_reference', 'source': CBC_URL}


def economic_review(report, reference=None, *, now=None):
    now = now or datetime.now(UTC)
    if reference:
        try:
            day = datetime.fromisoformat(reference.get("reference_date", "")).date()
            checked = datetime.fromisoformat(reference.get("checked_at", ""))
            valid_reference = (reference.get("source") == CBC_URL and checked.tzinfo
                and now - timedelta(days=1) <= checked <= now + timedelta(minutes=5)
                and now.date() - timedelta(days=7) <= day <= now.date())
        except (ValueError, TypeError):
            valid_reference = False
        if not valid_reference:
            reference = {"status": "stale_or_unavailable", "source": CBC_URL}
    facts = report.get('facts', {})
    estimate = report.get('estimate', {})
    def grounded(key):
        fact = facts.get(key, {})
        return fact.get('quote') and fact.get('url') in report.get('sources', [])
    def number(value):
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
    def twd(amount):
        if not amount:
            return None
        if amount['currency'] == 'TWD':
            return amount['amount']
        if (reference or {}).get('status') == 'ok':
            rate = reference.get('twd_per_usd')
            if number(rate) and rate > 0:
                return amount['amount'] * rate
        return None
    def grounded_amount(key):
        fact = facts.get(key, {})
        amount = money(fact.get('value')) if grounded(key) else None
        if not amount:
            return None
        quote = fact.get('quote', '')
        tokens = {'USD': r'US\$|USD|美元|美金', 'TWD': r'NT\$|TWD|NTD|新[臺台]幣'}[amount['currency']]
        numeric = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
        for match in re.finditer(rf'(?:{tokens})\s*\$?\s*({numeric})(萬元)?|({numeric})\s*(萬元)?\s*(?:{tokens})', quote, re.I):
            value = (match[1] or match[3]).replace(',', '')
            number_value = float(value) * (10000 if match[2] or match[4] else 1)
            if number_value == amount['amount']:
                return amount
        return None
    award = grounded_amount('prize') if grounded('prize') and grounded('prize_kind') and facts['prize_kind']['value'] == 'cash' else None
    fee_fact = facts.get('registration_fee', {})
    fee_is_documented = bool(re.search(r'報名費|參賽費|entry fee|registration fee', facts.get('registration_amount', {}).get('quote', ''), re.I))
    fee = (0 if fee_fact.get('value') == 'free' and grounded('registration_fee') else
           twd(grounded_amount('registration_amount')) if fee_fact.get('value') == 'paid' and grounded('registration_amount') and fee_is_documented else None)
    tools, hours = estimate.get('extra_tools_twd'), estimate.get('total_hours')
    award_twd = twd(award)
    scenarios = []
    if fee is not None and number(tools) and number(hours) and hours > 0:
        for wage in COMPETITION_POLICY['time_value_scenarios_twd_per_hour']:
            cost = fee + tools + hours * wage
            threshold = cost / award_twd if award_twd and award_twd > 0 else None
            if not math.isfinite(cost) or (threshold is not None and not math.isfinite(threshold)):
                continue
            scenarios.append({'hourly_value_twd': wage, 'cost_twd': round(cost, 2),
                              'break_even_probability': threshold})
    return {'status': 'conditional_scenarios' if scenarios else 'insufficient_cost_data',
            'success_probability': None, 'success_probability_status': 'unknown',
            'success_probability_reason': '沒有足夠的有效參賽數、可比作品及評審結果支持個人得獎率',
            'cash_award': award, 'award_twd_reference': award_twd, 'registration_cost_twd': fee,
            'exchange_reference': reference, 'scenarios': scenarios,
            'time_values_are_personal_wage': False, 'includes_tax_and_transfer_fees': False,
            'estimate_uncertain': estimate.get('uncertain') is not False,
            'noncash_value_twd': None, 'expected_net_return': None}
