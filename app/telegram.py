from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.models import Candidate


def escaped_clip(text: str, units: int) -> str:
    """Telegram counts UTF-16 units; escaping must happen after clipping."""
    clipped = text.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")
    return html.escape(clipped)


class TelegramClient:
    def __init__(self, token: str, owner_chat_id: int, timeout: float = 15.0) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.owner_chat_id = owner_chat_id
        self.timeout = timeout

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/{method}", json=payload)
                response.raise_for_status()
                result = response.json()
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

    async def send_competition(self, candidate: Candidate) -> int:
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
        }.get(report.get("decision"), "待確認｜尚未確認適合投入")
        deadline = display("deadline")
        try:
            closing = datetime.fromisoformat(value("deadline").replace("Z", "+00:00"))
            if closing.tzinfo:
                deadline = closing.astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d %H:%M") + "（台灣）"
        except ValueError:
            pass
        if facts.get('deadline', {}).get('defaults'):
            deadline = facts['deadline']['date'].replace('-', '/') + ' 24:00（預設台灣時間、當日結束）' if '24:00' in facts['deadline']['defaults'] and '台灣時間' in facts['deadline']['defaults'] else deadline + '（預設：' + html.escape(facts['deadline']['defaults']) + '）'
        fee = display("registration_amount") if value("registration_fee") == "paid" and value("registration_amount") != "unknown" else display("registration_fee")
        if value("registration_fee") == "paid":
            fee += "（報名前由你決定）"
        if value("registration_fee") == "unknown":
            fee += "（實際費用未確認）"
        lines = [f"<b>{escaped_clip(title, 180)}</b>", status, "", "<b>獎勵與期限</b>",
                 f"獎金：{display('prize')}{evidence_link('prize')}", f"截止：{deadline}{evidence_link('deadline')}", f"報名費：{fee}"]
        fit = {'eligible': '目前通過條件初篩；獎金與公開得獎紀錄符合目標，投入仍為估算。',
               'rejected': '有明確條件衝突，建議略過。'}.get(report.get('decision'), '目前只適合查證；關鍵條件尚缺，未確認值得開始製作。')
        lines.extend(['', '<b>是否值得投入</b>', fit])
        hours, cost, share = estimate.get("total_hours"), estimate.get("extra_tools_twd"), estimate.get("ai_share")
        time_text = f"{hours:g} 小時" if hours is not None else "未知"
        cost_text = f"NT${cost:g}" if cost is not None else "未知"
        share_text = f"{share:.0%}" if share is not None else "未知"
        lines.extend(["", "<b>投入預估</b>"])
        if all(item is None for item in (hours, cost, share)):
            lines.append("AI 估算：尚無可靠的耗時、製作比例與工具費估算")
        else:
            lines.extend([f"AI 估算：{time_text}（非實測）", f"AI 製作 {share_text}｜額外工具 {cost_text}"])
        lines.append("目標：≤6 小時 · AI ≥50% · 工具 ≤NT$300")
        if estimate.get('component_rule_issues'):
            lines.append('分工含未核實的人工限制，暫不採信這份製作計畫。')
        elif estimate.get('plan'):
            stages = (('planning', '規劃'), ('generation_wait', '生成等待'), ('review', '審查'),
                      ('submission', '交件'), ('finals', '後續'))
            lines.append('流程估算：\n' + ' · '.join(
                label + (f'{estimate[key]:g}h' if isinstance(estimate.get(key), (int, float)) else '未知')
                for key, label in stages))
            if value('attendance') == 'unknown':
                lines.append('後續出席義務尚未確認，流程估算仍不完整。')
        # Detailed component weights stay in the assessment; keep mobile cards scannable.

        labels = {
            "deliverables": "交付", "submission": "交件方式", "ai_policy": "AI 使用",
            "attendance": "答辯／出席", "eligibility": "參賽資格", "publicity": "公開展示",
            "rights": "作品授權", "participation": "參賽人數／名額",
        }
        known = [key for key in labels if value(key) != "unknown"]
        unknown = [labels[key] for key in labels if value(key) == "unknown"]
        lines.extend(["", "<b>交件與規則</b>"])
        for key in known:
            detail = display(key)
            if key == 'eligibility' and value(key) in {'eligible', 'ineligible'}:
                rule = facts.get(key, {}).get('quote')
                if rule:
                    sentences = re.split(r'(?<=[。；.!?])\s*', rule)
                    matching = [sentence for sentence in sentences if re.search(r'資格|不限年齡|國籍|居住地|eligible|eligibility|open to', sentence, re.I)]
                    rule = ' '.join(matching) if matching else rule
                    start = re.search(r'參賽資格[：:\s]*|不限年齡|(?:eligibility|eligible entrants|open to)\b', rule, re.I)
                    if start:
                        rule = rule[start.start():]
                detail += '｜' + escaped_clip(rule, 240) if rule else '｜資格規則原文待補'
            lines.append(f"{labels[key]}：{detail}" + (evidence_link(key) if key == "eligibility" else ""))
        if unknown:
            lines.append("待補：" + "、".join(unknown))
        ai_quote = facts.get("ai_policy", {}).get("quote")
        if value("ai_policy") != "unknown" and ai_quote:
            lines.append(f"<i>AI 規則摘錄：{escaped_clip(ai_quote, 140)}</i>")
        conditions = []
        for part in estimate.get('production_components', []):
            if part.get('human_only') and part.get('rule_quote') and part.get('rule_url') in report.get('sources', []):
                conditions.append(('須本人完成', part['rule_quote'], part['rule_url']))
        for condition in report.get('decision_conditions', []):
            if condition.get('url') in report.get('sources', []) and condition.get('kind') in {'licence', 'reward'}:
                conditions.append(('授權原文' if condition['kind'] == 'licence' else '獎勵限制',
                                   condition.get('quote', ''), condition['url']))
        if conditions:
            lines.extend(['', '<b>不可漏掉的條件</b>'])
            for label, quote, url in conditions[:3]:
                lines.append(f'{label}：{escaped_clip(quote, 440)} <a href="{html.escape(url, quote=True)}">依據</a>')
            if len(conditions) > 3:
                lines.append(f'另有 {len(conditions) - 3} 項原文限制，請核對完整來源。')
        if report.get("blockers"):
            heading = "不符合的原因" if report.get("decision") == "rejected" else "決策前先確認"
            lines.append(f"\n<b>{heading}</b>\n" + "\n".join("• " + escaped_clip(item, 90) for item in report["blockers"][:4]))
            if len(report["blockers"]) > 4:
                lines.append(f"另有 {len(report['blockers']) - 4} 項限制待核對，請查看來源。")
        sources = sorted(report.get("sources", []), key=lambda url: (
            0 if '.pdf' in url.lower() else 1 if '/terms' in url.lower() else 2))
        if sources:
            lines.append("\n" + " · ".join(
                f'<a href="{html.escape(url, quote=True)}">規則來源 {i + 1}</a>' for i, url in enumerate(sources[:2])
            ))
        else:
            lines.append("\n尚無可核對的規則來源，不能判定符合條件。")
        lines.append("\n<i>耗時含等待、修改、交件與答辯。工具優先使用現有 ChatGPT 額度；報名費另計。估算不代表得獎機率。</i>")
        result = await self.call("sendMessage", {
            "chat_id": self.owner_chat_id, "text": "\n".join(lines), "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[
                {"text": "查看原始來源", "url": candidate.permalink},
                {"text": "略過", "callback_data": f"q:{candidate.id}:skip"},
            ]]},
        })
        return int(result["message_id"])

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
