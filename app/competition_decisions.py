"""Conservative interpretation of grounded contest decision evidence."""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx


UNKNOWN = {'value': 'unknown', 'quote': '', 'url': ''}
TAIPEI = timezone(timedelta(hours=8))
MONTHS = {name.lower(): number for number in range(1,13)
          for name in (calendar.month_name[number], calendar.month_abbr[number])}
CLOSING = re.compile(r'截止|期限|(?:自公告日|即日)起至|deadline|entries\s+close|submissions?\s+(?:close|due)', re.I)


def evaluation_context(profile):
    return hashlib.sha256(json.dumps({'profile': profile, 'policy': 'ai50-hours6-tools300-v1'},
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
    match = re.search(rf'\b(\d{{1,2}})\s+({months})\s+(20\d{{2}})\b',text,re.I)
    if match:
        day, month, year = match.groups()
    else:
        match = re.search(rf'\b({months})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b',text,re.I)
        if not match:
            return None
        month, day, year = match.groups()
    try:
        return datetime(int(year),MONTHS[month.lower()],int(day)).date()
    except ValueError:
        return None


def _clock(text):
    text = re.sub(r'\b(?:UTC|GMT)\s*[+-]\d{1,2}(?::?\d{2})?', '', text, flags=re.I)
    match = re.search(r'(\d{1,2})[:：](\d{2})|(\d{1,2})[時點]',text,re.I)
    if not match:
        return None
    hour, minute = (int(match[1]),int(match[2])) if match[1] else (int(match[3]),0)
    local = text[max(0,match.start()-8):match.end()+5]
    if re.search(r'下午|晚上|\bpm\b',local,re.I) and hour<12:
        hour += 12
    elif re.search(r'上午|\bam\b',local,re.I) and hour==12:
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
    for name,hours in {'AEDT':11,'AEST':10,'PDT':-7,'PST':-8,'EDT':-4,'EST':-5}.items():
        if re.search(r'\b'+name+r'\b',text):
            return timezone(timedelta(hours=hours)),False
    if re.search(r'\b(?:UTC|GMT)\b',text):
        return timezone.utc,False
    return TAIPEI, not bool(re.search(r'台灣|臺灣|Taipei',text,re.I))


def resolve_deadline(fact, sources):
    """Merge matching date evidence; explicit precision always outranks defaults."""
    candidates = []
    for url,page in sources.items():
        starts = [m.start() for m in CLOSING.finditer(page)]
        starts += [m.start() for m in re.finditer(r'(?:\d{3,4}[年/.-])?\d{1,2}[月/.-]\d{1,2}日?[^。；\n]{0,16}截止',page)]
        for start in starts:
            span = re.split(r'[。；\n]',page[start:start+180],maxsplit=1)[0]
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


def recommendation_identity(candidate):
    try:
        parsed = urlsplit(str(httpx.URL(candidate.permalink)))
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
