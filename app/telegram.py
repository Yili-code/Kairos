from __future__ import annotations

import html
from typing import Any

import httpx

from app.models import Candidate


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

    async def send_candidate(self, candidate: Candidate) -> None:
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
        await self.call("sendMessage", {
            "chat_id": self.owner_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": keyboard},
        })

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
