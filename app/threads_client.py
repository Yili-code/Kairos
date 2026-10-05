from __future__ import annotations

from typing import Any

import httpx

from app.models import Candidate


FIELDS = (
    "id,media_product_type,media_type,permalink,owner,username,text,timestamp,"
    "shortcode,is_quote_post,has_replies"
)


class ThreadsClient:
    def __init__(self, base_url: str, access_token: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout

    async def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        params = {
            "q": query,
            "search_type": "RECENT",
            "limit": max(1, min(limit, 100)),
            "fields": FIELDS,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/keyword_search",
                    params=params,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("Threads keyword search failed") from None
        return [self._candidate(item, query) for item in payload.get("data", []) if item.get("id")]

    @staticmethod
    def _candidate(item: dict[str, Any], query: str) -> Candidate:
        owner = item.get("owner") or {}
        username = item.get("username") or owner.get("username") or "unknown"
        return Candidate(
            id=str(item["id"]),
            username=str(username),
            text=str(item.get("text") or ""),
            permalink=str(item.get("permalink") or ""),
            timestamp=str(item.get("timestamp") or ""),
            search_term=query,
        )
