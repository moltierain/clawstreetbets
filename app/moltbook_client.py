"""
Moltbook API client for ClawStreetBets integration.
All HTTP calls to www.moltbook.com are centralized here.
"""
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger("clawstreetbets.moltbook")

MOLTBOOK_BASE_URL = "https://www.moltbook.com/api/v1"
MOLTBOOK_SITE_URL = "https://www.moltbook.com"


class MoltbookError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None,
                 hint: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.hint = hint
        super().__init__(message)


class MoltbookClient:
    """Async HTTP client for Moltbook API v1."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{MOLTBOOK_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.request(
                    method, url,
                    headers=self.headers,
                    json=json_body,
                    params=params,
                )
                try:
                    data = resp.json()
                except (ValueError, UnicodeDecodeError):
                    raise MoltbookError(
                        message=f"Moltbook returned invalid JSON (HTTP {resp.status_code})",
                        status_code=resp.status_code,
                    )
                if resp.status_code >= 400:
                    raise MoltbookError(
                        message=data.get("error", f"HTTP {resp.status_code}"),
                        status_code=resp.status_code,
                        hint=data.get("hint"),
                    )
                return data.get("data", data)
        except httpx.RequestError as e:
            raise MoltbookError(
                message=f"Moltbook unreachable: {str(e)}",
                status_code=None,
            )

    async def get_me(self) -> Dict[str, Any]:
        return await self._request("GET", "/agents/me")

    async def subscribe_submolt(self, name: str) -> Dict[str, Any]:
        return await self._request("POST", f"/submolts/{name}/subscribe")
