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
    assert result['value']=='unknown' and reason=='affiliation_requires_confirmation'


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


def test_actual_korean_official_deadline_retains_explicit_kst_end_of_day():
    from app.competition_decisions import resolve_deadline
    url = 'https://korea.svaiff.com/film'
    original = '마감 2026.11.25(수) 24:00 KST = 미국 태평양시간 11.25(수) 07:00'
    fact, diagnostic = resolve_deadline({}, {url: original})
    assert fact['value'] == '2026-11-26T00:00:00+09:00'
    assert diagnostic == 'sourced_deadline'
    assert fact['url'] == url and fact['quote'] in original


def test_compact_am_and_pm_clock_suffixes_do_not_shift_midnight_by_twelve_hours():
    from app.competition_decisions import resolve_deadline
    url = 'https://event.devpost.com/rules'
    for clock, expected in [('12:00am', '00:00:00'), ('12:00pm', '12:00:00'), ('1:30pm', '13:30:00')]:
        fact, _ = resolve_deadline({}, {url: 'Deadline July 1, 2027 @ ' + clock + ' PST.'})
        assert fact['value'] == '2027-07-01T' + expected + '-08:00'


def test_actual_opencv_compact_pm_deadline_is_not_twelve_hours_early():
    from app.competition_decisions import resolve_deadline
    url = 'https://opencv26.devpost.com/rules'
    fact, _ = resolve_deadline({}, {url: 'Deadline: Oct 26, 2026 @ 11:45pm PDT'})
    assert fact['value'] == '2026-10-26T23:45:00-07:00'


def test_actual_date_before_label_timeline_does_not_borrow_winners_date():
    from app.competition_decisions import resolve_deadline
    url='https://akool.com/aifilmchallenge'
    text='Entries close December 20, 2026. Timeline Sept 15, 2026 Challenge opens Dec 20, 2026 Now open Submissions close Jan 15, 2027 Winners announced Meet the Judges'
    fact,diagnostic=resolve_deadline({}, {url:text})
    assert fact['value']=='2026-12-21T00:00:00+08:00'
    assert fact['quote'] in text and 'conflict' not in diagnostic


def test_ordinal_dates_and_chinese_date_before_closing_do_not_take_later_awards():
    from app.competition_decisions import resolve_deadline
    for text in ['Submissions close December 20th, 2026. Winners announced January 15th, 2027.',
                 '2026年12月20日截止，頒獎日期2027年1月15日。']:
        fact,_=resolve_deadline({}, {'https://school.edu.tw/rules':text})
        assert fact['value']=='2026-12-21T00:00:00+08:00'


def test_real_conflicting_deadlines_are_not_hidden_by_timeline_pairing():
    from app.competition_decisions import resolve_deadline
    fact,diagnostic=resolve_deadline({}, {'https://school.edu.tw/rules':'Deadline December 20, 2026. Deadline January 15, 2027.'})
    assert fact['value']=='unknown' and diagnostic=='conflicting_deadline_dates'


def test_actual_ntua_range_opening_is_not_a_conflicting_deadline_and_chinese_minutes_are_kept():
    from app.competition_decisions import resolve_deadline
    text = '二、徵件期間 2026年10月10日至2027年2月1日 報名截止時間為2027年2月1日23時59分，以臺灣時間為準。'
    fact, diagnostic = resolve_deadline({}, {NYCU: text})
    assert fact['value'] == '2027-02-01T23:59:00+08:00'
    assert fact['quote'] in text and diagnostic == 'sourced_deadline'


def test_actual_distinct_closing_dates_remain_unknown_after_range_fix():
    from app.competition_decisions import resolve_deadline
    sources = {NYCU: '徵件期間2026年10月10日至2027年2月1日，報名截止時間為2027年2月1日23時59分。',
               'https://school.edu.tw/other': '報名截止2027年2月2日23時59分。'}
    fact, diagnostic = resolve_deadline({}, sources)
    assert fact['value'] == 'unknown' and diagnostic == 'conflicting_deadline_dates'


def test_actual_itch_date_before_label_uses_explicit_platform_end_year_and_bare_pm():
    from app.competition_decisions import resolve_deadline
    text = ('Submissions open from 2026-10-23 17:00:00 to 2026-10-26 17:00:00 '
            'Schedule Fri Oct 23, 6PM BST · Submissions open and theme reveal '
            'Mon Oct 26, 5PM GMT · Submissions close, voting begins '
            'Oct 26 to Nov 2, 5PM GMT · Community and judge rating Copyright 2003')
    fact, diagnostic = resolve_deadline({}, {'https://itch.io/jam/example': text})
    assert fact['value'] == '2026-10-26T17:00:00+00:00'
    assert fact['quote'] in text and diagnostic == 'sourced_deadline'


def test_shorthand_closing_year_is_not_guessed_with_ambiguous_source_years():
    from app.competition_decisions import resolve_deadline
    fact, _ = resolve_deadline({}, {NYCU: 'Mon Oct 26, 5PM GMT · Submissions close. Events 2026 and 2027.'})
    assert fact['value'] == 'unknown'


def test_platform_shorthand_does_not_hide_a_real_competing_deadline():
    from app.competition_decisions import resolve_deadline
    text = ('Submissions open from 2026-10-23 17:00:00 to 2026-10-26 17:00:00 '
            'Mon Oct 26, 5PM GMT · Submissions close. Deadline October 27, 2026 17:00 UTC.')
    fact, diagnostic = resolve_deadline({}, {NYCU: text})
    assert fact['value'] == 'unknown' and diagnostic == 'conflicting_deadline_dates'
