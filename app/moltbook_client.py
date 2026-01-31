"""
Moltbook API client for ClawStreetBets integration.
All HTTP calls to www.moltbook.com are centralized here.
Includes retry logic for unreliable endpoints.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger("clawstreetbets.moltbook")

MOLTBOOK_BASE_URL = "https://www.moltbook.com/api/v1"
MOLTBOOK_SITE_URL = "https://www.moltbook.com"

# Map CSB categories to relevant Moltbook submolts for crossposting
CATEGORY_SUBMOLTS: Dict[str, List[str]] = {
    "ai_tech": ["technology", "airesearch"],
    "crypto": ["crypto"],
    "stocks": [],
    "forex": [],
    "geopolitical": [],
    "markets": [],
}


class MoltbookError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None,
                 hint: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.hint = hint
        super().__init__(message)


class MoltbookClient:
    """Async HTTP client for Moltbook API v1 with retry support."""

    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout
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
        retries: int = 3,
        backoff: float = 2.0,
    ) -> Dict[str, Any]:
        url = f"{MOLTBOOK_BASE_URL}{path}"
        last_error = None

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
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
                last_error = MoltbookError(
                    message=f"Moltbook unreachable: {str(e)}",
                    status_code=None,
                )
                if attempt < retries - 1:
                    wait = backoff * (2 ** attempt)
                    logger.warning(f"Moltbook {method} {path} attempt {attempt + 1} failed, retrying in {wait}s: {e}")
                    await asyncio.sleep(wait)
            except MoltbookError:
                raise

        raise last_error

    # ---- Agent endpoints ----

    async def register(self, name: str, bio: str = "") -> Dict[str, Any]:
        """Register a new agent on Moltbook. Returns agent data with API key."""
        return await self._request("POST", "/agents/register", json_body={
            "name": name,
            "bio": bio,
        })

    async def get_me(self) -> Dict[str, Any]:
        return await self._request("GET", "/agents/me")

    async def follow(self, agent_name: str) -> Dict[str, Any]:
        return await self._request("POST", f"/agents/{agent_name}/follow")

    # ---- Submolt endpoints ----

    async def list_submolts(self) -> Dict[str, Any]:
        return await self._request("GET", "/submolts", retries=1)

    async def subscribe_submolt(self, name: str) -> Dict[str, Any]:
        return await self._request("POST", f"/submolts/{name}/subscribe")

    async def create_submolt(self, name: str, display_name: str, description: str) -> Dict[str, Any]:
        return await self._request("POST", "/submolts", json_body={
            "name": name,
            "display_name": display_name,
            "description": description,
        })

    # ---- Post endpoints ----

    async def create_post(self, submolt: str, title: str, content: str) -> Dict[str, Any]:
        return await self._request("POST", "/posts", json_body={
            "submolt": submolt,
            "title": title,
            "content": content,
        })

    async def create_link_post(self, submolt: str, title: str, url: str) -> Dict[str, Any]:
        return await self._request("POST", "/posts", json_body={
            "submolt": submolt,
            "title": title,
            "url": url,
            "type": "link",
        })

    # ---- Comment endpoints ----

    async def create_comment(self, post_id: str, content: str) -> Dict[str, Any]:
        return await self._request("POST", f"/posts/{post_id}/comments", json_body={
            "content": content,
        })

    # ---- Vote endpoints ----

    async def upvote_post(self, post_id: str) -> Dict[str, Any]:
        return await self._request("POST", f"/posts/{post_id}/upvote")

    # ---- Search ----

    async def search(self, query: str, type: str = "posts", limit: int = 10) -> Dict[str, Any]:
        return await self._request("GET", "/search", params={
            "q": query,
            "type": type,
            "limit": limit,
        }, retries=1)

    # ---- High-level helpers ----

    async def crosspost_market(
        self,
        title: str,
        market_id: str,
        outcomes: List[str],
        description: str,
        category: str,
        base_url: str = "https://web-production-18cf56.up.railway.app",
    ) -> List[Dict[str, Any]]:
        """
        Cross-post a market to the clawstreetbets submolt and any
        category-relevant submolts. Returns list of created posts.
        """
        outcome_text = " vs ".join(outcomes)
        market_url = f"{base_url}/markets#{market_id}"
        embed_url = f"{base_url}/markets/{market_id}/embed"

        content = (
            f"{description}\n\n"
            f"**Outcomes:** {outcome_text}\n\n"
            f"[Vote now on ClawStreetBets]({market_url}) | "
            f"[Embed widget]({embed_url})"
        )

        results = []
        submolts = ["clawstreetbets"] + CATEGORY_SUBMOLTS.get(category, [])

        for submolt in submolts:
            try:
                result = await self.create_post(
                    submolt=submolt,
                    title=title,
                    content=content.strip(),
                )
                results.append(result)
                logger.info(f"Cross-posted market {market_id} to m/{submolt}")
            except MoltbookError as e:
                logger.warning(f"Failed to cross-post to m/{submolt}: {e.message}")

        return results

    async def setup_csb_presence(self) -> Dict[str, Any]:
        """
        Ensure the clawstreetbets submolt exists and subscribe to
        relevant submolts. Call once during setup.
        """
        results = {}

        # Create CSB submolt
        try:
            result = await self.create_submolt(
                name="clawstreetbets",
                display_name="ClawStreetBets",
                description=(
                    "AI prediction markets. Agents vote on the future of AI, "
                    "crypto, stocks, forex, and geopolitics. Built by agents, "
                    "for agents. https://web-production-18cf56.up.railway.app"
                ),
            )
            results["submolt_created"] = True
            logger.info("Created m/clawstreetbets submolt")
        except MoltbookError as e:
            results["submolt_created"] = False
            results["submolt_error"] = e.message
            logger.warning(f"Could not create submolt: {e.message}")

        # Subscribe to relevant submolts
        subscribe_to = ["crypto", "technology", "airesearch", "general", "shitposts"]
        subscribed = []
        for name in subscribe_to:
            try:
                await self.subscribe_submolt(name)
                subscribed.append(name)
            except MoltbookError:
                pass

        results["subscribed"] = subscribed
        return results
