from typing import Any

import httpx


class FeedbotClient:
    """Thin async client for the Feedbot internal endpoints (server-side bot token).

    All ingestion goes through `/v1/internal/ingest` which resolves project from
    chat_id, so the bot itself doesn't know (or need) a project slug.
    """

    def __init__(self, base_url: str, bot_token: str, timeout: float = 10.0):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=timeout,
        )

    async def ingest(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        r = await self._client.post("/v1/internal/ingest", json=payload)
        if r.status_code == 404:
            return None  # chat not linked to any project — caller decides what to do
        r.raise_for_status()
        return r.json()

    async def redeem_link(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        r = await self._client.post("/v1/internal/redeem-link", json=payload)
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
