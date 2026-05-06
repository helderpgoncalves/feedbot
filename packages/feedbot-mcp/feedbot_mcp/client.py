from typing import Any

import httpx


class FeedbotHTTP:
    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )

    async def list_feedbacks(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._client.get("/v1/feedbacks", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def get_feedback(self, public_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/v1/feedbacks/{public_id}")
        r.raise_for_status()
        return r.json()

    async def patch_feedback(self, public_id: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.patch(f"/v1/feedbacks/{public_id}", json=body)
        r.raise_for_status()
        return r.json()

    async def stats(self) -> dict[str, Any]:
        r = await self._client.get("/v1/stats")
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
