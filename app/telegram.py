from __future__ import annotations

import html
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.models import Candidate
from app.competition_decisions import competition_card_gaps


class CompetitionCardIncomplete(ValueError):
    """No Telegram request was made; retain the lead for background research."""
    def __init__(self, gaps):
        self.gaps = gaps
        super().__init__('Competition card lacks: ' + '、'.join(gaps))


def escaped_clip(text: str, units: int) -> str:
    """Telegram counts UTF-16 units; escaping must happen after clipping."""
    clipped = text.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")
    return html.escape(clipped)


def competition_recommendation(report: dict) -> str:
    """Preference tier, separate from qualification and never an award probability."""
    decision = report.get('decision')
    if decision == 'rejected':
        return '不推薦'
    estimate = report.get('estimate', {})

    def number(key, *, upper=None, positive=False):
        value = estimate.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value < 0 or (positive and value == 0) or (upper is not None and value > upper)):
            return None
        return value

    hours = number('total_hours', positive=True)
    share = number('ai_share', upper=1)
    cost = number('extra_tools_twd')
    if hours is not None and hours > 6:
        return '低｜目前工時估算偏高'
    if share is not None and share < .5:
        return '低｜預估 AI 製作比例偏低'
    if cost is not None and cost > 300:
        return '低｜預估工具費偏高'
    facts = report.get('facts', {})
    fee = facts.get('registration_fee', {}).get('value')
    attendance = facts.get('attendance', {}).get('value')
    if (decision != 'eligible' or estimate.get('uncertain') is not False
            or any(value is None for value in (hours, share, cost))
            or fee not in {'free', 'paid'} or attendance not in {'none', 'online_final'}):
        return '暫不評級'
    return '高' if fee == 'free' and attendance == 'none' else '中'


class TelegramRejected(RuntimeError):
    """Explicit rejection or failure before connection; safe to distinguish from unknown delivery."""
    def __init__(self, code, *, retryable=False, retry_after=60):
        super().__init__('Telegram request not accepted')
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


class TelegramClient:
    def __init__(self, token: str, owner_chat_id: int, timeout: float = 15.0, *, transport=None) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.owner_chat_id = owner_chat_id
        self.timeout = timeout
        self.transport = transport

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(f"{self.base_url}/{method}", json=payload)
                if response.status_code in {400, 401, 403, 404, 429}:
                    rejected = response.json()
                    if (method == 'editMessageText' and response.status_code == 400
                            and 'message is not modified' in str(rejected.get('description', '')).lower()):
                        return {'message_id': payload['message_id']}
                    if isinstance(rejected, dict) and rejected.get('ok') is False:
                        parameters = rejected.get('parameters', {})
                        delay = parameters.get('retry_after', 60) if isinstance(parameters, dict) else 60
                        delay = delay if isinstance(delay, int) and not isinstance(delay, bool) else 60
                        raise TelegramRejected(str(response.status_code), retryable=response.status_code == 429,
                                               retry_after=max(60, delay))
                response.raise_for_status()
                result = response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TelegramRejected('connection_not_established', retryable=True) from None
        except (httpx.HTTPError, ValueError):
            raise RuntimeError(f"Telegram {method} transport failed") from None
        if not result.get("ok"):
            raise RuntimeError(f"Telegram {method} failed")
        return result["result"]

    async def send_candidate(self, candidate: Candidate) -> int:
        if candidate.category == "ai_competition":
            return await self.send_competition(candidate)
        reasons = "\n".join(f"• {html.escape(reason)}" for reason in candidate.reasons[:4]) or "• No strong signal"
        risks = "\n".join(f"• {html.escape(risk)}" for risk in candidate.risks[:3]) or "• None detected"
        excerpt = html.escape(candidate.text[:700])
        text = (
            f"<b>{html.escape(candidate.category.replace('_', ' ').title())} · {candidate.first_round_score}/100</b>\n"
            f"@{html.escape(candidate.username)}\n\n"
            f"{excerpt}\n\n<b>Why shortlisted</b>\n{reasons}\n\n<b>Risks</b>\n{risks}"
        )
        keyboard = [[
            {"text": "Interested", "callback_data": f"q:{candidate.id}:start"},
            {"text": "Skip", "callback_data": f"q:{candidate.id}:skip"},
            {"text": "Open post", "url": candidate.permalink},
        ]]
        result = await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": keyboard},
        })
        return int(result["message_id"])

    async def send_competition(self, candidate: Candidate, *, edit=False) -> int:
        gaps = competition_card_gaps(candidate.competition)
        if gaps:
            raise CompetitionCardIncomplete(gaps)
        payload = self.competition_payload(candidate)
        if edit:
            if not candidate.telegram_message_id:
                raise ValueError('Cannot edit a card without a receipt')
            payload['message_id'] = candidate.telegram_message_id
        result = await self.call('editMessageText' if edit else 'sendMessage', payload)
        return int(result['message_id'])

    def competition_payload(self, candidate: Candidate) -> dict:
        """Pure layout preview; public delivery always applies the information gate."""
        report = candidate.competition
        facts, estimate = report.get("facts", {}), report.get("estimate", {})
        values = {
            "unknown": "未確認", "free": "免費", "paid": "付費，金額未確認",
            "online": "線上", "offline": "實體", "broad_allowed": "允許大量 AI 製作",
            "limited": "僅限部分 AI 輔助", "prohibited": "禁止", "none": "無須出席或答辯",
            "online_final": "入圍後線上答辯", "onsite": "需實體出席", "eligible": "符合資格",
            "ineligible": "不符資格", "allowed": "允許",
        }
        def value(key):
            return str(facts.get(key, {}).get("value") or "unknown")

        def display(key, limit=140):
            raw = value(key)
            return escaped_clip(values.get(raw, raw), limit)

        def evidence_link(key):
            fact = facts.get(key,{})
            url = fact.get('url','')
            if fact.get('value') != 'unknown' and fact.get('quote') and url in report.get('sources',[]) and url.startswith('https://'):
                return f' <a href="{html.escape(url,quote=True)}">依據</a>'
            return ''

        title_lines = re.sub(r"https?://\S+", "", candidate.text).splitlines()
        title = next((line.strip() for line in title_lines if line.strip()), "競賽資訊（名稱待確認）")
        status = {
            "eligible": "初篩符合｜報名前核對完整規則",
            "rejected": "不符合條件｜建議略過",
        }.get(report.get("decision"), "待確認")
        deadline = display("deadline")
        try:
            closing = datetime.fromisoformat(value("deadline").replace("Z", "+00:00"))
            if closing.tzinfo:
                deadline = closing.astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d %H:%M") + "（台灣）"
        except ValueError:
            pass
        deadline_fact = facts.get('deadline', {})
        if '24:00' in deadline_fact.get('defaults', '') and deadline_fact.get('date'):
            deadline = html.escape(deadline_fact['date'].replace('-', '/')) + ' 24:00'
        fee = display("registration_amount") if value("registration_fee") == "paid" and value("registration_amount") != "unknown" else display("registration_fee")
        if value("registration_fee") == "paid":
            fee += "（報名前由你決定）"
        lines = [f"<b>{escaped_clip(title, 180)}</b>", status,
                 f"推薦程度：{competition_recommendation(report)}", "", "<b>獎勵與期限</b>",
                 f"獎金：{display('prize')}{evidence_link('prize')}", f"截止：{deadline}{evidence_link('deadline')}", f"報名費：{fee}"]
        hours, cost, share = estimate.get("total_hours"), estimate.get("extra_tools_twd"), estimate.get("ai_share")
        time_text = f"{hours:g} 小時" if hours is not None else "未知"
        cost_text = f"NT${cost:g}" if cost is not None else "未知"
        share_text = f"{share:.0%}" if share is not None else "未知"
        lines.extend(["", "<b>投入預估</b>"])
        if all(item is None for item in (hours, cost, share)):
            lines.append("AI 估算：尚無可靠的耗時、製作比例與工具費估算")
        else:
            lines.extend([f"AI 估算：{time_text}（非實測）", f"AI 製作 {share_text}｜額外工具 {cost_text}"])
        if estimate.get('component_rule_issues'):
            lines.append('分工含未核實的人工限制，暫不採信這份製作計畫。')
        elif estimate.get('plan'):
            stages = []
            for keys, label in ((('planning', 'generation_wait'), '製作'), (('review', 'submission'), '檢查／交件')):
                amounts = [estimate.get(key) for key in keys]
                stages.append(label + (f' {sum(amounts):g}h' if all(isinstance(n, (int, float)) for n in amounts) else '待估'))
            if isinstance(estimate.get('finals'), (int, float)) and estimate['finals'] > 0:
                stages.append(f"後續 {estimate['finals']:g}h")
            lines.append('流程估算：' + ' · '.join(stages))
        # Detailed component weights stay in the assessment; keep mobile cards scannable.

        labels = {
            "deliverables": "交付", "submission": "交件方式", "ai_policy": "AI 使用",
            "attendance": "答辯／出席", "eligibility": "參賽資格", "publicity": "公開展示",
            "rights": "作品授權", "participation": "參賽人數／名額",
        }
        known = [key for key in labels if value(key) != "unknown"]
        if known:
            lines.extend(["", "<b>交件與規則</b>"])
        for key in known:
            detail = display(key, 110 if key == 'deliverables' else 100)
            if key == 'eligibility' and value(key) in {'eligible', 'ineligible'}:
                rule = facts.get(key, {}).get('quote')
                if rule:
                    sentences = re.split(r'(?<=[。；.!?])\s*', rule)
                    matching = [sentence for sentence in sentences if re.search(r'資格|不限年齡|國籍|居住地|eligible|eligibility|open to', sentence, re.I)]
                    rule = ' '.join(matching) if matching else rule
                    start = re.search(r'參賽資格[：:\s]*|不限年齡|(?:eligibility|eligible entrants|open to)\b', rule, re.I)
                    if start:
                        rule = rule[start.start():]
                detail += '｜' + escaped_clip(rule, 120) if rule else '｜資格規則原文待補'
            lines.append(f"{labels[key]}：{detail}" + (evidence_link(key) if key == "eligibility" else ""))
        conditions = []
        for part in estimate.get('production_components', []):
            if part.get('human_only') and part.get('rule_quote') and part.get('rule_url') in report.get('sources', []):
                conditions.append(('須本人完成', part['rule_quote'], part['rule_url']))
        for condition in report.get('decision_conditions', []):
            labels = {'licence': '授權原文', 'reward': '獎勵限制', 'requirement': '交件限制',
                      'mixed_prize': '獎項含非現金，現金拆分待確認'}
            if condition.get('url') in report.get('sources', []) and condition.get('kind') in labels:
                conditions.append((labels[condition['kind']],
                                   condition.get('quote', ''), condition['url']))
        if conditions:
            lines.extend(['', '<b>不可漏掉的條件</b>'])
            for label, quote, url in conditions[:4]:
                lines.append(f'{label}：{escaped_clip(quote, 440)} <a href="{html.escape(url, quote=True)}">依據</a>')
        if report.get("blockers"):
            rejected = report.get('decision') == 'rejected'
            heading = '不符合的原因' if rejected else '待確認'
            issues = list(dict.fromkeys(report['blockers']))[:3 if rejected else 2]
            lines.append(f'\n<b>{heading}</b>\n' + '；'.join(escaped_clip(item.rstrip('。.'), 80) for item in issues))
        sources = sorted(report.get("sources", []), key=lambda url: (
            0 if '.pdf' in url.lower() else 1 if '/terms' in url.lower() else 2))
        if sources:
            lines.append("\n" + " · ".join(
                f'<a href="{html.escape(url, quote=True)}">規則來源 {i + 1}</a>' for i, url in enumerate(sources[:2])
            ))
        else:
            lines.append("\n尚無可核對的規則來源，不能判定符合條件。")
        payload = {
            "chat_id": self.owner_chat_id, "text": "\n".join(lines), "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[
                {"text": "查看原始來源", "url": candidate.permalink},
                {"text": "略過", "callback_data": f"q:{candidate.id}:skip"},
            ]]},
        }
        return payload

    async def send_question(self, candidate: Candidate, question: str, options: list[tuple[str, str]]) -> None:
        buttons = [
            {"text": label, "callback_data": f"q:{candidate.id}:{value}"}
            for label, value in options
        ]
        rows = [buttons[index:index + 3] for index in range(0, len(buttons), 3)]
        await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": question,
            "reply_markup": {"inline_keyboard": rows},
        })

    async def send_free_text_prompt(self, candidate: Candidate, purpose: str, question: str) -> None:
        marker = f"[Kairos:{candidate.id}:{purpose}]"
        await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": f"{question}\n\n{marker}",
            "reply_markup": {
                "force_reply": True,
                "selective": True,
                "input_field_placeholder": "Reply with one short note",
            },
        })

    async def send_draft(self, candidate: Candidate) -> None:
        text = (
            f"<b>Fit assessment · {candidate.fit_score}/100</b>\n"
            f"Interest: {candidate.interest_score}/5\n\n"
            f"{html.escape(candidate.assessment)}\n\n"
            f"<b>Private message draft</b>\n{html.escape(candidate.draft_message)}"
        )
        keyboard = [[
            {"text": "Approve & Send", "callback_data": f"q:{candidate.id}:approve"},
            {"text": "Revise", "callback_data": f"q:{candidate.id}:revise"},
            {"text": "Skip", "callback_data": f"q:{candidate.id}:skip"},
        ]]
        await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": keyboard},
        })

    async def send_generation_error(self, candidate: Candidate) -> None:
        keyboard = [[
            {"text": "Retry drafting", "callback_data": f"q:{candidate.id}:retry_draft"},
            {"text": "Skip", "callback_data": f"q:{candidate.id}:skip"},
        ]]
        await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": f"Drafting failed for @{candidate.username}. Your answers were kept.",
            "reply_markup": {"inline_keyboard": keyboard},
        })

    async def notify(self, text: str) -> None:
        await self.call("sendMessage", {"chat_id": self.owner_chat_id, "text": text})

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
