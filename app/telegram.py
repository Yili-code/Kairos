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
        fee = display("registration_amount") if value("registration_fee") == "paid" and value("registration_amount") != "unknown" else display("registration_fee")
        if value("registration_fee") == "paid":
            fee += "（報名前由你決定）"
        lines = [f"<b>{escaped_clip(title, 180)}</b>", status, "", "<b>回報與投入</b>",
                 f"獎金：{display('prize')}", f"截止：{deadline}", f"報名費：{fee}"]
        hours, cost, share = estimate.get("total_hours"), estimate.get("extra_tools_twd"), estimate.get("ai_share")
        time_text = f"{hours:g} 小時" if hours is not None else "未知"
        cost_text = f"NT${cost:g}" if cost is not None else "未知"
        share_text = f"{share:.0%}" if share is not None else "未知"
        if all(item is None for item in (hours, cost, share)):
            lines.append("AI 估算：尚無可靠的耗時、製作比例與工具費估算")
        else:
            lines.extend([f"AI 估算：{time_text}｜AI 製作 {share_text}｜額外工具 {cost_text}"])
        lines.append("你的上限：6 小時／工具 NT$300；優先使用現有 ChatGPT 額度")
        if estimate.get('component_rule_issues'):
            lines.append('分工含未核實的人工限制，暫不採信這份製作計畫。')
        elif estimate.get("plan"):
            lines.append("估算依據：" + escaped_clip(estimate["plan"], 160))
        components = estimate.get('production_components', [])
        if components:
            lines.append('估算分工：' + '；'.join(
                escaped_clip(part['name'], 25) + f'（AI {part["ai_fraction"]:.0%}）' for part in components[:3]))

        labels = {
            "deliverables": "交付", "submission": "交件方式", "ai_policy": "AI 使用",
            "attendance": "答辯／出席", "eligibility": "參賽資格", "publicity": "公開展示",
            "rights": "作品授權", "participation": "參賽人數／名額",
        }
        known = [key for key in labels if value(key) != "unknown"]
        unknown = [labels[key] for key in labels if value(key) == "unknown"]
        lines.extend(["", "<b>交件與規則</b>"])
        for key in known:
            lines.append(f"{labels[key]}：{display(key)}")
        if unknown:
            lines.append("待補：" + "、".join(unknown))
        ai_quote = facts.get("ai_policy", {}).get("quote")
        if value("ai_policy") != "unknown" and ai_quote:
            lines.append(f"<i>AI 規則摘錄：{escaped_clip(ai_quote, 140)}</i>")
        if report.get("blockers"):
            heading = "不符合的原因" if report.get("decision") == "rejected" else "決策前先確認"
            lines.append(f"\n<b>{heading}</b>\n" + "\n".join("• " + escaped_clip(item, 90) for item in report["blockers"][:4]))
            if len(report["blockers"]) > 4:
                lines.append(f"另有 {len(report['blockers']) - 4} 項限制待核對，請查看來源。")
        questions = report.get('verification_questions', [])
        if questions and report.get('sources'):
            lines.append('\n<b>核對重點</b>\n' + '\n'.join(
                '• ' + escaped_clip(item['question'], 65) for item in questions[:2]))
        sources = sorted(report.get("sources", []), key=lambda url: (
            0 if '.pdf' in url.lower() else 1 if '/terms' in url.lower() else 2))
        if sources:
            lines.append("\n" + " · ".join(
                f'<a href="{html.escape(url, quote=True)}">規則來源 {i + 1}</a>' for i, url in enumerate(sources[:2])
            ))
        else:
            lines.append("\n尚無可核對的規則來源，不能判定符合條件。")
        lines.append("<i>耗時含 AI 等待、修改、交件及答辯；估算非實測，不代表得獎機率。報名費另計。</i>")
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
