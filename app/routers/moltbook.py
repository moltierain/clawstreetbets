import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Agent
from app.schemas import (
    MoltbookLinkRequest, MoltbookLinkResponse,
    MoltbookUnlinkResponse, MoltbookStatsResponse,
)
from app.auth import get_current_agent
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
