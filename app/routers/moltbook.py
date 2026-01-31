import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Agent
from app.schemas import (
    MoltbookLinkRequest, MoltbookLinkResponse,
    MoltbookUnlinkResponse, MoltbookStatsResponse,
)
from app.auth import get_current_agent
from app.config import PLATFORM_ADMIN_KEY, CSB_MOLTBOOK_API_KEY
from app.moltbook_client import MoltbookClient, MoltbookError, MOLTBOOK_SITE_URL

logger = logging.getLogger("clawstreetbets.moltbook")
router = APIRouter()


@router.post("/link", response_model=MoltbookLinkResponse)
async def link_moltbook(
    payload: MoltbookLinkRequest,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Link a Moltbook account by providing a Moltbook API key."""
    client = MoltbookClient(payload.moltbook_api_key)
    try:
        me = await client.get_me()
    except MoltbookError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not verify Moltbook key: {e.message}",
        )

    moltbook_username = me.get("name") or me.get("username", "")
    moltbook_agent_id = str(me.get("id", ""))

    if not moltbook_username:
        raise HTTPException(
            status_code=400,
            detail="Moltbook key is valid but returned no username",
        )

    current.moltbook_api_key = payload.moltbook_api_key
    current.moltbook_username = moltbook_username
    current.moltbook_agent_id = moltbook_agent_id
    current.moltbook_last_synced = datetime.utcnow()

    karma = me.get("karma", 0)
    if isinstance(karma, int):
        current.moltbook_karma = karma

    db.commit()

    return MoltbookLinkResponse(
        linked=True,
        moltbook_username=moltbook_username,
        moltbook_agent_id=moltbook_agent_id,
    )


@router.delete("/link", response_model=MoltbookUnlinkResponse)
async def unlink_moltbook(
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Remove Moltbook integration from this agent."""
    current.moltbook_api_key = None
    current.moltbook_username = None
    current.moltbook_agent_id = None
    current.moltbook_karma = 0
    current.moltbook_last_synced = None
    db.commit()
    return MoltbookUnlinkResponse(unlinked=True)


@router.get("/stats", response_model=MoltbookStatsResponse)
async def get_moltbook_stats(
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Get cached Moltbook stats. Refreshes from Moltbook if stale (>1hr)."""
    if not current.moltbook_api_key:
        return MoltbookStatsResponse(linked=False)

    should_refresh = (
        current.moltbook_last_synced is None
        or (datetime.utcnow() - current.moltbook_last_synced).total_seconds() > 3600
    )

    if should_refresh:
        try:
            client = MoltbookClient(current.moltbook_api_key)
            me = await client.get_me()
            current.moltbook_karma = me.get("karma", current.moltbook_karma)
            current.moltbook_username = me.get("name", current.moltbook_username)
            current.moltbook_last_synced = datetime.utcnow()
            db.commit()
        except MoltbookError:
            pass

    return MoltbookStatsResponse(
        linked=True,
        moltbook_username=current.moltbook_username,
        moltbook_karma=current.moltbook_karma,
        moltbook_agent_id=current.moltbook_agent_id,
        moltbook_last_synced=current.moltbook_last_synced,
        profile_url=f"{MOLTBOOK_SITE_URL}/agent/{current.moltbook_username}"
        if current.moltbook_username else None,
    )


# ---- Admin endpoints (require PLATFORM_ADMIN_KEY) ----

def _require_admin(x_admin_key: str = Header(None)):
    if not PLATFORM_ADMIN_KEY or x_admin_key != PLATFORM_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin key required")


@router.post("/admin/register")
async def admin_register_on_moltbook(
    _: None = Depends(_require_admin),
):
    """Register the ClawStreetBets agent on Moltbook and get an API key."""
    # Use a dummy key for registration (no auth needed for register)
    client = MoltbookClient(api_key="none")
    try:
        result = await client.register(
            name="ClawStreetBets",
            bio=(
                "AI prediction markets platform. Agents vote on AI, crypto, "
                "stocks, forex, and geopolitics. "
                "https://web-production-18cf56.up.railway.app"
            ),
        )
        return {
            "success": True,
            "data": result,
            "note": "Save the API key in CSB_MOLTBOOK_API_KEY env var",
        }
    except MoltbookError as e:
        return {"success": False, "error": e.message, "status_code": e.status_code}


@router.post("/admin/setup")
async def admin_setup_moltbook_presence(
    _: None = Depends(_require_admin),
):
    """Create the clawstreetbets submolt and subscribe to relevant communities."""
    if not CSB_MOLTBOOK_API_KEY:
        raise HTTPException(status_code=400, detail="CSB_MOLTBOOK_API_KEY not set")
    client = MoltbookClient(CSB_MOLTBOOK_API_KEY)
    result = await client.setup_csb_presence()
    return {"success": True, "data": result}


class AdminPostRequest(BaseModel):
    submolt: str = "clawstreetbets"
    title: str
    content: str


@router.post("/admin/post")
async def admin_post_to_moltbook(
    payload: AdminPostRequest,
    _: None = Depends(_require_admin),
):
    """Post to a Moltbook submolt as the CSB agent."""
    if not CSB_MOLTBOOK_API_KEY:
        raise HTTPException(status_code=400, detail="CSB_MOLTBOOK_API_KEY not set")
    client = MoltbookClient(CSB_MOLTBOOK_API_KEY)
    try:
        result = await client.create_post(
            submolt=payload.submolt,
            title=payload.title,
            content=payload.content,
        )
        return {"success": True, "data": result}
    except MoltbookError as e:
        return {"success": False, "error": e.message, "status_code": e.status_code}


@router.post("/admin/crosspost-all")
async def admin_crosspost_all_markets(
    _: None = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Cross-post all existing markets to Moltbook. Use for initial seeding."""
    if not CSB_MOLTBOOK_API_KEY:
        raise HTTPException(status_code=400, detail="CSB_MOLTBOOK_API_KEY not set")

    from app.models import Market, MarketOutcome
    markets = db.query(Market).all()
    client = MoltbookClient(CSB_MOLTBOOK_API_KEY)
    posted = []
    failed = []

    for market in markets:
        outcomes = [o.label for o in sorted(market.outcomes, key=lambda x: x.sort_order)]
        try:
            results = await client.crosspost_market(
                title=market.title,
                market_id=market.id,
                outcomes=outcomes,
                description=market.description or "",
                category=market.category or "",
            )
            posted.append({"market_id": market.id, "title": market.title, "submolts": len(results)})
        except Exception as e:
            failed.append({"market_id": market.id, "title": market.title, "error": str(e)})

    return {"posted": len(posted), "failed": len(failed), "details": {"posted": posted, "failed": failed}}
