"""Conservative interpretation of grounded contest decision evidence."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from app.competition_policy import COMPETITION_POLICY


UNKNOWN = {'value': 'unknown', 'quote': '', 'url': ''}
TAIPEI = timezone(timedelta(hours=8))
MONTHS = {name.lower(): number for number in range(1,13)
          for name in (calendar.month_name[number], calendar.month_abbr[number])}
MONTHS['sept'] = 9
CLOSING = re.compile(r'截止|期限|마감|(?:自公告日|即日)起至|deadline|entries\s+close|submissions?\s+(?:close|due)', re.I)


def concrete_cash_prize(value):
    if not isinstance(value, str) or re.search(r'\b(?:TBA|TBD|unknown|undetermined)\b|待(?:公[布佈]|公告|確認)|未(?:公[布佈]|公告|確認|定)|另行公[布佈]', value, re.I):
        return False
    currency = r'NT\$|US\$|[$€£¥₹₩]|USD|TWD|NTD|AUD|CAD|EUR|GBP|JPY|KRW|CNY|SGD|HKD|新[臺台]幣|美元|韓元|歐元|日圓|人民幣|元'
    number = r'(\d[\d,]*(?:\.\d+)?)'
    for match in re.finditer(rf'(?:{currency})\s*{number}|{number}\s*[萬万千百億]?\s*(?:{currency})', value, re.I):
        try:
            amount = float((match[1] or match[2]).replace(',', ''))
            if math.isfinite(amount) and amount > 0:
                return True
        except (ValueError, OverflowError):
            pass
    return bool(re.search(r'(?:新[臺台]幣|美元|韓元|歐元|日圓|人民幣)[一二三四五六七八九十百千萬億]+元', value))


def competition_card_gaps(report, *, now=None):
    """Minimum useful card content; quotation provenance was validated by evaluation."""
    facts, sources = report.get('facts', {}), report.get('sources', [])
    missing = []
    def grounded(key):
        fact = facts.get(key, {})
        return bool(isinstance(fact.get('value'), str) and fact['value'] not in {'', 'unknown'} and fact.get('quote')
                    and fact.get('url') in sources)
    if (not grounded('prize') or not concrete_cash_prize(facts.get('prize', {}).get('value'))
            or not grounded('prize_kind') or facts['prize_kind']['value'] != 'cash'):
        missing.append('現金獎金')
    try:
        closing = datetime.fromisoformat(facts.get('deadline', {}).get('value', '').replace('Z', '+00:00'))
        valid_deadline = grounded('deadline') and closing.tzinfo and closing > (now or datetime.now(timezone.utc))
    except (TypeError, ValueError, AttributeError):
        valid_deadline = False
    if not valid_deadline:
        missing.append('有效截止時間')
    for key, label in (('deliverables', '交付內容'), ('ai_policy', 'AI 規則')):
        if not grounded(key):
            missing.append(label)
    estimate = report.get('estimate', {})
    valid_estimate = True
    for key in ('total_hours', 'ai_share', 'extra_tools_twd'):
        value = estimate.get(key)
        valid_estimate &= (not isinstance(value, bool) and isinstance(value, (int, float))
                           and math.isfinite(value) and value >= 0
                           and (key != 'total_hours' or value > 0)
                           and (key != 'ai_share' or value <= 1))
    if not valid_estimate:
        missing.append('完整投入估算')
    return missing


def evaluation_context(profile):
    return hashlib.sha256(json.dumps({'profile': profile, 'policy': COMPETITION_POLICY},
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def assessment_current(report, profile, *, now=None):
    if report.get('context_hash') != evaluation_context(profile):return False
    try:
        checked = datetime.fromisoformat(report.get('checked_at', ''))
        now = now or datetime.now(timezone.utc)
        return bool(checked.tzinfo and now - timedelta(hours=24) <= checked <= now + timedelta(minutes=5))
    except (TypeError, ValueError):return False


def explicit_decision_conditions(sources):
    """Retain literal licence and conditional-reward clauses omitted by summaries."""
    patterns = {
        'licence': r'By entering[^.]{0,180}?you grant[^.]{15,900}\.',
        'reward': r'Only premium[^.]{0,150}(?:bonus|reward)[^.]{0,80}\.(?:\s*Each account[^.]{0,120}\.)?',
        'requirement': r'The AKOOL logo MUST BE prominently displayed at the top of the video\.',
        'mixed_prize': r'Grand Prize\s+\$[\d,]+\s+Includes:\s+Cash Award\s+AKOOL Membership / Credits[^.]{0,180}?Featured Case Study',
    }
    conditions, seen = [], set()
    for url, page in sources.items():
        for kind, pattern in patterns.items():
            for match in re.finditer(pattern, page, re.I):
                quote = match[0]
                identity = (kind, ' '.join(quote.split()).casefold())
                if identity not in seen:
                    seen.add(identity)
                    conditions.append({'kind': kind, 'quote': quote, 'url': url})
    return conditions


def _calendar_date(text, page):
    text = re.sub(r'[（(](\d{3})[）)]年',r'\1年',text)
    match = re.search(r'(?:(\d{3,4})[年/.-])?(\d{1,2})[月/.-](\d{1,2})日?', text)
    if match:
        year, month, day = match.groups()
        if not year:
            years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', page))
            if len(years) != 1:
                return None
            year = years.pop()
        year = int(year) + (1911 if int(year)<1911 else 0)
        try:
            return datetime(year,int(month),int(day)).date()
        except ValueError:
            return None
    months = '|'.join(sorted(MONTHS,key=len,reverse=True))
    match = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})\s+(20\d{{2}})\b',text,re.I)
    if match:
        day, month, year = match.groups()
    else:
        match = re.search(rf'\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b',text,re.I)
        if not match:
            short = re.search(rf'\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b', text, re.I)
            if not short:
                return None
            month, day = short.groups()
            # A platform's explicit submission-end date can supply the omitted
            # year of its matching timeline card, even with an old footer year.
            referenced = {year for year, mm, dd in re.findall(
                r'Submissions open from\s+20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\s+to\s+(20\d{2})-(\d{2})-(\d{2})', page, re.I)
                if int(mm) == MONTHS[month.lower()] and int(dd) == int(day)}
            years = referenced or set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', page))
            if len(years) != 1:
                return None
            year = years.pop()
        else:
            month, day, year = match.groups()
    try:
        return datetime(int(year),MONTHS[month.lower()],int(day)).date()
    except ValueError:
        return None


def _clock(text):
    text = re.sub(r'\b(?:UTC|GMT)\s*[+-]\d{1,2}(?::?\d{2})?', '', text, flags=re.I)
    match = re.search(r'(\d{1,2})[:：](\d{2})|(\d{1,2})[時點](?:(\d{1,2})分?)?|(\d{1,2})\s*(?:am|pm)\b',text,re.I)
    if not match:
        return None
    hour, minute = ((int(match[1]),int(match[2])) if match[1] else
                    (int(match[3]),int(match[4] or 0)) if match[3] else (int(match[5]),0))
    local = text[max(0,match.start()-8):match.end()+5]
    if re.search(r'下午|晚上|(?<![A-Za-z])pm\b',local,re.I) and hour<12:
        hour += 12
    elif re.search(r'上午|(?<![A-Za-z])am\b',local,re.I) and hour==12:
        hour = 0
    return (hour,minute)


def _zone(text):
    iana = re.search(r'\b(?:Africa|America|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Za-z_]+(?:/[A-Za-z_]+)?',text)
    if iana:
        return ZoneInfo(iana[0]), False
    offset = re.search(r'\b(?:UTC|GMT)\s*([+-])(\d{1,2})(?::?(\d{2}))?',text,re.I)
    if offset:
        minutes = int(offset[2])*60 + int(offset[3] or 0)
        return timezone(timedelta(minutes=minutes*(1 if offset[1]=='+' else -1))), False
    for name,hours in {'AEDT':11,'AEST':10,'PDT':-7,'PST':-8,'EDT':-4,'EST':-5,'KST':9,'JST':9}.items():
        if re.search(r'\b'+name+r'\b',text):
            return timezone(timedelta(hours=hours)),False
    if re.search(r'\b(?:UTC|GMT)\b',text):
        return timezone.utc,False
    return TAIPEI, not bool(re.search(r'台灣|臺灣|Taipei',text,re.I))


def resolve_deadline(fact, sources):
    """Merge matching date evidence; explicit precision always outranks defaults."""
    candidates = []
    for url,page in sources.items():
        # Some timeline cards put each date before its label. Preserve that literal
        # span instead of borrowing the following winner-announcement date.
        month_names = '|'.join(sorted(MONTHS, key=len, reverse=True))
        english_date = rf'(?:{month_names})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+20\d{{2}}'
        timeline = re.compile(rf'{english_date}\s+(?:challenge|entries|submissions)\s+opens?\s+'
            rf'(?P<closing>{english_date})(?:\s+now open)?\s+(?P<label>(?:submissions?|entries)\s+close)\s+'
            rf'{english_date}\s+winners?\s+announced', re.I)
        paired = {match.start('label'): page[match.start('closing'):match.end('label')]
                  for match in timeline.finditer(page)}
        short_date = rf'(?:{month_names})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+20\d{{2}})?'
        for match in re.finditer(rf'(?=(?P<date>{short_date})(?P<gap>[^.;\n]{{0,65}})(?P<label>(?:submissions?|entries)\s+close))', page, re.I):
            if not re.search(short_date, match['gap'], re.I):
                paired[match.start('label')] = page[match.start('date'):match.end('label')]
        suffix = re.compile(r'(?P<closing>(?:\d{3,4}[年/.-])?\d{1,2}[月/.-]\d{1,2}日?)\s*(?P<label>截止)', re.I)
        for match in suffix.finditer(page):
            if not re.match(r'.{0,8}(?:延長|延期|展延|改為|調整)', page[match.end():match.end()+16]):
                paired[match.start('label')] = page[match.start('closing'):match.end('label')]
        starts = [m.start() for m in CLOSING.finditer(page)]
        numeric_date = r'(?<!\d)(?:\d{3,4}[年/.-])?\d{1,2}[月/.-]\d{1,2}日?'
        # Overlap matches so a range's opening date cannot swallow its closing
        # date. An intervening second date belongs to that later closing label.
        for match in re.finditer(rf'(?=({numeric_date})([^。；\n]{{0,16}})截止)', page):
            if not re.search(numeric_date, match[2]):
                starts.append(match.start())
        for start in starts:
            span = paired.get(start) or re.split(r'[。；\n]',page[start:start+180],maxsplit=1)[0]
            date = _calendar_date(span,page)
            if date:
                candidates.append((date,_clock(span),span,url))
    if not candidates:
        return dict(UNKNOWN),'missing_sourced_deadline'
    if len({row[0] for row in candidates}) != 1:
        return dict(UNKNOWN),'conflicting_deadline_dates'
    clocks = {row[1] for row in candidates if row[1] is not None}
    if len(clocks)>1:
        return dict(UNKNOWN),'conflicting_deadline_times'
    precise = [row for row in candidates if row[1] is not None] or candidates
    # Prefer a span with an explicit timezone over one that requires the owner default.
    try:
        explicit = [row for row in precise if not _zone(row[2])[1]]
        date,clock,span,url = (explicit or precise)[0]
        zone,zone_default = _zone(span)
        closing = datetime.combine(date,datetime.min.time(),tzinfo=zone)
        if clock is None or clock == (24,0):
            closing += timedelta(days=1)
        else:
            closing = closing.replace(hour=clock[0],minute=clock[1])
    except (ValueError,ZoneInfoNotFoundError):
        return dict(UNKNOWN),'invalid_or_unsupported_deadline_time'
    defaults = ('台灣時間' if zone_default else '') + ('、當日結束 24:00' if clock is None else '')
    result = {'value':closing.isoformat(),'quote':span,'url':url,'date':date.isoformat()}
    if defaults:
        result['defaults'] = defaults.strip('、')
    return result,'sourced_deadline_with_defaults' if defaults else 'sourced_deadline'


def validate_eligibility(fact, profile):
    if fact['value'] != 'eligible':
        return fact, None
    quote = fact['quote']
    positive = re.search(r'不限|皆可|參賽資格|參賽對象|在學學生|大專.{0,8}學生|open to|may enter|can enter|eligible (?:entrants|participants)|eligible to enter|individual artists|individuals|everyone|anyone',quote,re.I)
    if not positive:
        return {**fact,'value':'unknown'},'missing_positive_eligibility_evidence'
    school = profile.get('education',{}).get('school','')
    if 'NTOU' in school:
        other = r'(?:陽明交大|陽明交通大學|NYCU|National Yang Ming Chiao Tung University|清華大學|NTHU|淡江大學|Tamkang University)'
        if re.search(other+r'.{0,14}(?:在校學生|在學學生|師生|學生及|students|staff)',quote,re.I):
            return {**fact,'value':'ineligible'},'restricted_to_other_institution'
    if re.search(r'限本校|本校在學|全校師生',quote) and not re.search(r'不限學校|不限校別',quote):
        return {**fact,'value':'unknown'},'institution_scope_requires_confirmation'
    unrestricted = re.search(r'(?:不限|任何|所有).{0,8}國籍|all nationalities|regardless of (?:nationality|citizenship)',quote,re.I)
    if not unrestricted and re.search(r'國籍|citizenship|nationality|\bcitizens\b|passport',quote,re.I) and not profile.get('citizenship'):
        return {**fact,'value':'unknown'},'citizenship_requires_confirmation'
    return fact,None


def canonical_contest_url(url):
    from app.config import DEFAULT_COMPETITION_COMPANIONS
    for primary, companions in DEFAULT_COMPETITION_COMPANIONS.items():
        if url in companions:
            return primary
    return url


def recommendation_identity(candidate):
    # Only reviewed explicit aliases are merged; similar titles do not prove identity.
    permalink = canonical_contest_url(candidate.permalink)
    try:
        parsed = urlsplit(str(httpx.URL(permalink)))
        url = urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(sorted(parse_qsl(parsed.query))),''))
    except (ValueError,httpx.InvalidURL):
        url = 'candidate:' + candidate.id
    deadline = candidate.competition.get('facts',{}).get('deadline',{}).get('value','unknown')
    return url,deadline


def recover_explicit_rights(fact, sources):
    """Recover a literal entrant/winner clause, not a legal interpretation."""
    if fact['value'] != 'unknown':
        return fact,False
    found = {}
    for url,text in sources.items():
        if not (urlsplit(url).hostname or '').endswith(('.edu.tw','.gov.tw')):
            continue
        for match in re.finditer(r'(?:得獎者|參賽者).{0,12}(?:同意|保留).{0,45}(?:圖文使用權|作品.{0,8}使用權|著作權|授權)[^。]{0,180}',text,re.S):
            quote = match[0].split('。')[0].strip()
            normalized = ' '.join(quote.split())
            found.setdefault(normalized,{'value':normalized,'quote':quote,'url':url})
    return (next(iter(found.values())),True) if len(found)==1 else (fact,False)
