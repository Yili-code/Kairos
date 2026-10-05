from __future__ import annotations

import asyncio

import httpx
import pytest

from app.threads_client import ThreadsClient


def test_keyword_search_sends_the_explicit_meta_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/keyword_search"
        assert request.url.params["q"] == "hackathon"
        assert request.url.params["search_type"] == "RECENT"
        assert request.url.params["search_mode"] == "KEYWORD"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"data": [{
            "id": "post-1",
            "username": "builder",
            "text": "Looking for a teammate",
            "permalink": "https://example.test/post-1",
            "timestamp": "2026-10-05T00:00:00Z",
        }]})

    client = ThreadsClient(
        "https://graph.threads.net/v1.0",
        "test-token",
        transport=httpx.MockTransport(handler),
    )

    candidates = asyncio.run(client.search("hackathon", limit=20))

    assert [candidate.id for candidate in candidates] == ["post-1"]


def test_keyword_search_reports_http_status_without_exposing_token() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "permission denied"}})

    client = ThreadsClient(
        "https://graph.threads.net/v1.0",
        "secret-token-value",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError) as error:
        asyncio.run(client.search("internship"))

    assert "HTTP 403" in str(error.value)
    assert "secret-token-value" not in str(error.value)


def test_keyword_search_rejects_an_invalid_data_shape() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None})

    client = ThreadsClient(
        "https://graph.threads.net/v1.0",
        "test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="invalid data shape"):
        asyncio.run(client.search("paid project"))
