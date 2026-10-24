from datetime import UTC, datetime

from app.competition_decisions import resolve_deadline, validate_eligibility
from app.profile import PROFILE
from app.competitions import evaluate
from tests.test_competitions import valid_report, SOURCES, NOW, capture_card


NYCU = 'https://sdgs.nycu.edu.tw/sdgs/ch/app/news/view?id=39599&module=headnews'


def test_explicit_noon_deadline_beats_the_short_date_only_title():
    text = '2026年。10/19徵件截止。徵件截止｜2026/10/19（一）中午12:00。'
    fact,_ = resolve_deadline({}, {NYCU:text})
    assert fact['value'] == '2026-10-19T12:00:00+08:00'
    assert '24:00' not in fact.get('defaults','')
    assert '中午12:00' in fact['quote']


def test_english_deadline_uses_the_closing_date_not_opening_or_local_render_time():
    text = ('Entries open 1 July 2026 at 12:00 am (Australia/Melbourne). '
            'Entries close 30 November 2026 at 11:59 pm (Australia/Melbourne) '
            'Your local time: 30 November 2026 at 12:59 pm. Judging 15 February 2027.')
    fact,_=resolve_deadline({}, {'https://www.postmeaning.art/timeline':text})
    assert fact['value']=='2026-11-30T23:59:00+11:00'


def test_conflicting_precise_times_do_not_fall_back_to_midnight():
    fact,diagnostic=resolve_deadline({}, {NYCU:'截止2026/11/16 12:00。截止2026/11/16 17:00。'})
    assert fact['value']=='unknown' and diagnostic=='conflicting_deadline_times'


def test_timezone_offset_alone_is_not_a_submission_clock():
    fact,_=resolve_deadline({}, {NYCU:'Deadline 2026-11-16 UTC+08:00.'})
    assert fact['value']=='2026-11-17T00:00:00+08:00'


def test_unrelated_country_exclusions_do_not_establish_a_positive_eligibility_grant():
    fact={'value':'eligible','quote':'Blocked countries: Afghanistan, Belarus, Iran, Russia.','url':'https://www.postmeaning.art/rules'}
    result,reason=validate_eligibility(fact,PROFILE)
    assert result['value']=='unknown' and reason=='missing_positive_eligibility_evidence'


def test_model_cannot_mark_another_universitys_closed_call_eligible():
    fact={'value':'eligible','quote':'參賽資格｜陽明交大在校學生及在職教職員，個人或團隊皆可。','url':NYCU}
    result,reason=validate_eligibility(fact,PROFILE)
    assert result['value']=='ineligible' and reason=='restricted_to_other_institution'


def test_residence_is_not_citizenship_and_unrestricted_entry_is_preserved():
    fact={'value':'eligible','quote':'Only citizens of Taiwan with a valid ROC passport are eligible to enter.','url':NYCU}
    assert validate_eligibility(fact,PROFILE)[0]['value']=='unknown'
    fact['quote']='不限年齡、國籍及居住地，每人限一件。'
    assert validate_eligibility(fact,PROFILE)[0]['value']=='eligible'


def test_parenthesized_roc_year_and_explicit_hour_remain_exact():
    source = '徵件期程：自公告日起至本（114）年9月12日下午5時止受理申請。'
    fact,_=resolve_deadline({}, {'https://academic.site.nthu.edu.tw/notice':source})
    assert fact['value']=='2025-09-12T17:00:00+08:00'


def test_omitted_rights_can_recover_a_literal_winner_clause_but_not_site_copyright():
    from app.competition_decisions import recover_explicit_rights,UNKNOWN
    url='https://calligraphy.tku.edu.tw/rules.pdf'
    quote='得獎者需同意該作品之圖文使用權讓與主辦單位，以利藝文推廣。'
    fact,recovered=recover_explicit_rights(dict(UNKNOWN),{url:quote})
    assert recovered and fact['value'].startswith('得獎者需同意') and fact['url']==url
    assert not recover_explicit_rights(dict(UNKNOWN),{url:'網站作者保留著作權，禁止轉載。'})[1]


def test_conflicting_licensing_clauses_do_not_get_arbitrarily_recovered():
    from app.competition_decisions import recover_explicit_rights,UNKNOWN
    sources={'https://campus.edu.tw/a':'參賽者同意作品使用權讓與主辦單位。',
             'https://campus.edu.tw/b':'參賽者保留作品使用權與著作權。'}
    assert not recover_explicit_rights(dict(UNKNOWN),sources)[1]
