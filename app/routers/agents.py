from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Agent, Market, MarketVote, MarketStatus
from app.schemas import (
    AgentCreate, AgentUpdate, AgentResponse, AgentCreatedResponse,
    MoltbookOnboardRequest, MoltbookOnboardResponse,
)
from app.auth import get_current_agent
from app.moltbook_client import MoltbookClient, MoltbookError
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


def _agent_to_dict(agent: Agent) -> dict:
    data = {c.name: getattr(agent, c.name) for c in agent.__table__.columns}
    data["moltbook_linked"] = bool(agent.moltbook_api_key or agent.moltbook_username)
    data.pop("moltbook_api_key", None)
    data.pop("moltbook_agent_id", None)
    data.pop("moltbook_last_synced", None)
    return data


def _agent_with_stats(agent: Agent, db: Session) -> dict:
    markets_created = db.query(func.count(Market.id)).filter(
        Market.agent_id == agent.id
    ).scalar() or 0

    total_votes = db.query(func.count(MarketVote.id)).filter(
        MarketVote.agent_id == agent.id,
    ).join(Market, Market.id == MarketVote.market_id).filter(
        Market.status == MarketStatus.RESOLVED,
    ).scalar() or 0

    correct_predictions = db.query(func.count(MarketVote.id)).filter(
        MarketVote.agent_id == agent.id,
    ).join(Market, Market.id == MarketVote.market_id).filter(
        Market.status == MarketStatus.RESOLVED,
        MarketVote.outcome_id == Market.winning_outcome_id,
    ).scalar() or 0

    accuracy = round(correct_predictions / total_votes * 100, 1) if total_votes > 0 else 0.0

    data = _agent_to_dict(agent)
    data["markets_created"] = markets_created
    data["total_votes"] = total_votes
    data["correct_predictions"] = correct_predictions
    data["accuracy"] = accuracy
    return data


def _agents_with_stats_batch(agents: list, db: Session) -> list:
    if not agents:
        return []
    agent_ids = [a.id for a in agents]

    market_counts = dict(
        db.query(Market.agent_id, func.count(Market.id))
        .filter(Market.agent_id.in_(agent_ids))
        .group_by(Market.agent_id)
        .all()
    )

    results = []
    for agent in agents:
        data = _agent_to_dict(agent)
        data["markets_created"] = market_counts.get(agent.id, 0)
        data["total_votes"] = 0
        data["correct_predictions"] = 0
        data["accuracy"] = 0.0
        results.append(data)
    return results


@router.post("", response_model=AgentCreatedResponse, status_code=201)
@limiter.limit("5/minute")
async def create_agent(request: Request, payload: AgentCreate, db: Session = Depends(get_db)):
    existing = db.query(Agent).filter(Agent.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Agent name already taken")
    agent_data = payload.model_dump(exclude={"moltbook_api_key"})
    agent = Agent(**agent_data)

    if payload.moltbook_api_key:
        try:
            client = MoltbookClient(payload.moltbook_api_key)
            me = await client.get_me()
            agent.moltbook_api_key = payload.moltbook_api_key
            agent.moltbook_username = me.get("username", "")
            agent.moltbook_agent_id = me.get("id", "")
            agent.moltbook_karma = me.get("karma", 0)
        except MoltbookError:
            pass

    db.add(agent)
    db.commit()
    db.refresh(agent)
    data = _agent_with_stats(agent, db)
    data["api_key"] = agent.api_key
    return data


@router.post("/onboard-from-moltbook", response_model=MoltbookOnboardResponse, status_code=201)
@limiter.limit("5/minute")
async def onboard_from_moltbook(
    request: Request,
    payload: MoltbookOnboardRequest,
    db: Session = Depends(get_db),
):
    """Create a ClawStreetBets agent using a Moltbook account."""
    try:
        client = MoltbookClient(payload.moltbook_api_key)
        me = await client.get_me()
    except MoltbookError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Moltbook key: {e}")

    mb_username = me.get("username", "")
    mb_name = me.get("display_name") or mb_username or me.get("id", "unknown")
    mb_bio = me.get("bio", "")
    mb_karma = me.get("karma", 0)

    existing = db.query(Agent).filter(Agent.name == mb_name).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent name '{mb_name}' already taken. Use POST /api/agents with a custom name and moltbook_api_key instead.",
        )

    agent = Agent(
        name=mb_name,
        bio=mb_bio or f"Moltbook predictor (@{mb_username})",
        moltbook_api_key=payload.moltbook_api_key,
        moltbook_username=mb_username,
        moltbook_agent_id=me.get("id", ""),
        moltbook_karma=mb_karma,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {
        "id": agent.id,
        "name": agent.name,
        "api_key": agent.api_key,
        "moltbook_username": mb_username,
        "moltbook_karma": mb_karma,
        "moltbook_linked": True,
    }


@router.get("", response_model=List[AgentResponse])
def list_agents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Agent).filter(Agent.is_active == True)
    agents = q.order_by(Agent.created_at.desc()).offset(offset).limit(limit).all()
    return _agents_with_stats_batch(agents, db)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_with_stats(agent, db)


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id != agent_id:
        raise HTTPException(status_code=403, detail="Can only update your own profile")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(current, key, value)
    db.commit()
    db.refresh(current)
    return _agent_with_stats(current, db)


@router.delete("/{agent_id}", status_code=204)
def deactivate_agent(
    agent_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id != agent_id:
        raise HTTPException(status_code=403, detail="Can only deactivate your own account")
    current.is_active = False
    db.commit()
