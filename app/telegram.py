from __future__ import annotations

import html
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
        labels = {
            "deadline": "截止", "prize": "現金獎金／得獎紀錄", "registration_fee": "報名費",
            "registration_amount": "報名費金額",
            "submission": "交件", "ai_policy": "AI 規則", "attendance": "出席／答辯",
            "eligibility": "參賽資格", "publicity": "公開展示", "rights": "著作權／授權",
            "deliverables": "交付內容",
            "participation": "參賽人數／獎項名額依據",
        }
        values = {
            "unknown": "待確認", "free": "免費", "paid": "付費，需你另行決定",
            "online": "線上", "offline": "實體", "broad_allowed": "允許大量 AI 製作",
            "limited": "僅限部分 AI 輔助", "prohibited": "禁止", "none": "無須出席或答辯",
            "online_final": "入圍後線上答辯", "onsite": "需實體出席", "eligible": "符合資格",
            "ineligible": "不符資格", "allowed": "允許",
        }
        status = "符合篩選（含 AI 估算）" if report.get("decision") == "eligible" else "待確認候選"
        lines = [f"<b>AI 協作線上競賽 · {status}</b>", escaped_clip(candidate.text, 200), ""]
        if report.get("discovery_signal"):
            lines.append(escaped_clip(report["discovery_signal"], 80))
        for key, label in labels.items():
            fact = facts.get(key, {})
            value = str(fact.get("value", "unknown"))
            lines.append(f"<b>{label}</b>：{escaped_clip(values.get(value, value), 180)}")
            if key in {"ai_policy", "registration_fee"} and fact.get("quote"):
                lines.append(f"依據：{escaped_clip(fact['quote'], 160)}")
        hours, cost, share = estimate.get("total_hours"), estimate.get("extra_tools_twd"), estimate.get("ai_share")
        time_text = f"{hours:g} 小時" if hours is not None else "未知"
        cost_text = f"NT${cost:g}" if cost is not None else "未知"
        share_text = f"{share:.0%}" if share is not None else "未知"
        lines.extend([
            "", "<b>AI 估算，非實測／非主辦方承諾</b>",
            f"完整流程：{time_text}（上限 6 小時，含等待與答辯）",
            f"AI 製作比例：{share_text}；額外工具：{cost_text}（上限 NT$300）",
            "報名費另計；優先使用現有 ChatGPT 額度。",
        ])
        stage_labels = {"planning": "選題", "generation_wait": "生成等待", "review": "修改驗收",
                        "submission": "交件", "finals": "後續答辯"}
        stages = [f"{label} {estimate[key]:g}h" for key, label in stage_labels.items() if estimate.get(key) is not None]
        if stages:
            lines.append("／".join(stages))
        if estimate.get("plan"):
            lines.append(escaped_clip(estimate["plan"], 200))
        if report.get("blockers"):
            lines.append("\n<b>尚待確認</b>\n" + "\n".join("• " + escaped_clip(item, 80) for item in report["blockers"][:5]))
        sources = report.get("sources", [])
        if sources:
            lines.append("\n<b>規則來源</b>：" + " · ".join(
                f'<a href="{html.escape(url, quote=True)}">來源 {i + 1}</a>' for i, url in enumerate(sources[:2])
            ))
        else:
            lines.append("\n尚未取得可核對的主辦方規則；此卡不表示符合參賽條件。")
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
