from __future__ import annotations

import json
from dataclasses import dataclass


class DMSenderError(RuntimeError):
    pass


class DMUnavailable(DMSenderError):
    pass


@dataclass(frozen=True)
class SendReceipt:
    status: str
    detail: str


class DisabledDMSender:
    async def send(self, username: str, message: str) -> SendReceipt:
        raise DMSenderError("Threads DM automation is disabled")


class ThreadsBrowserSender:
    """Brittle UI adapter. Enable only after a controlled live selector check."""

    def __init__(self, storage_state_json: str) -> None:
        if not storage_state_json:
            raise DMSenderError("Missing Threads browser storage state")
        self.storage_state = json.loads(storage_state_json)

    async def send(self, username: str, message: str) -> SendReceipt:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=self.storage_state)
            page = await context.new_page()
            try:
                await page.goto(f"https://www.threads.com/@{username}", wait_until="domcontentloaded")
                message_button = page.get_by_role("button", name="Message", exact=True)
                if await message_button.count() == 0:
                    raise DMUnavailable("The profile has no available DM action")
                await message_button.click()
                composer = page.get_by_role("textbox")
                await composer.wait_for(state="visible", timeout=10_000)
                await composer.fill(message)
                send_button = page.get_by_role("button", name="Send", exact=True)
                await send_button.click()
                return SendReceipt("sent", "Threads UI accepted the send action")
            finally:
                await context.close()
                await browser.close()
