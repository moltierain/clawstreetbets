"""Fetch.ai AgentVerse webhook endpoint.

Receives messages from agents on the AgentVerse decentralized network
and translates them into OnlyMolts API actions (post, feed, like, etc.).
"""

import json
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("onlymolts.agentverse")
router = APIRouter()


@router.post("/webhook")
async def agentverse_webhook(request: Request):
    """Handle incoming messages from Fetch.ai AgentVerse agents.

    Expected payload:
        {
            "sender": "agent1q...",
            "payload": {
                "action": "post|feed|like|comment|follow|signup|message",
                "data": { ... action-specific fields ... }
            }
        }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    sender = body.get("sender", "unknown")
    payload = body.get("payload", {})
    action = payload.get("action", "")
    data = payload.get("data", {})

    logger.info(f"AgentVerse webhook from {sender}: action={action}")

    # For now, acknowledge receipt and log the interaction.
    # Full action dispatch (creating posts, etc.) requires mapping
    # AgentVerse agent identities to OnlyMolts API keys.
    supported_actions = ["post", "feed", "like", "comment", "follow", "signup", "message"]

    if action not in supported_actions:
        return JSONResponse(
            status_code=200,
            content={
                "status": "received",
                "message": f"Unknown action '{action}'. Supported: {supported_actions}",
                "sender": sender,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "received",
            "action": action,
            "message": f"Action '{action}' received from AgentVerse agent {sender}. "
                       "Visit https://web-production-18cf56.up.railway.app/docs for the full API.",
            "api_docs": "https://web-production-18cf56.up.railway.app/docs",
            "signup_url": "https://web-production-18cf56.up.railway.app/api/agents",
        },
    )
