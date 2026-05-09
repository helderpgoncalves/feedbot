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

    async def ingest_reply(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        r = await self._client.post("/v1/internal/ingest-reply", json=payload)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def outbound_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        r = await self._client.get("/v1/internal/outbound-pending", params={"limit": limit})
        r.raise_for_status()
        return r.json()

    async def outbound_ack(self, payload: dict[str, Any]) -> None:
        r = await self._client.post("/v1/internal/outbound-ack", json=payload)
        r.raise_for_status()

    async def fetch_bot_config(self) -> dict[str, Any]:
        """Fetch the Telegram credentials saved via the admin panel.

        Returns ``{"token": str | None, "username": str | None}``. Used at
        bot startup to discover whether to launch and which token to use
        when ``TELEGRAM_BOT_TOKEN`` is not set in the environment.
        """
        r = await self._client.get("/v1/internal/bot-config")
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
