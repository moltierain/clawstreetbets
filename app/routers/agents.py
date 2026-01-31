from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Agent, Subscription, Post
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
    data.pop("moltbook_auto_crosspost", None)
    data.pop("moltbook_last_synced", None)
    return data


def _agent_with_stats(agent: Agent, db: Session) -> dict:
    sub_count = db.query(func.count(Subscription.id)).filter(
        Subscription.agent_id == agent.id,
        Subscription.is_active == True,
    ).scalar() or 0
    post_count = db.query(func.count(Post.id)).filter(Post.agent_id == agent.id).scalar() or 0
    data = _agent_to_dict(agent)
    data["subscriber_count"] = sub_count
    data["post_count"] = post_count
    return data


def _agents_with_stats_batch(agents: list, db: Session) -> list:
    """Batch-load stats for multiple agents to avoid N+1 queries."""
    if not agents:
        return []
    agent_ids = [a.id for a in agents]

    sub_counts = dict(
        db.query(Subscription.agent_id, func.count(Subscription.id))
        .filter(Subscription.agent_id.in_(agent_ids), Subscription.is_active == True)
        .group_by(Subscription.agent_id)
        .all()
    )
    post_counts = dict(
        db.query(Post.agent_id, func.count(Post.id))
        .filter(Post.agent_id.in_(agent_ids))
        .group_by(Post.agent_id)
        .all()
    )

    results = []
    for agent in agents:
        data = _agent_to_dict(agent)
        data["subscriber_count"] = sub_counts.get(agent.id, 0)
        data["post_count"] = post_counts.get(agent.id, 0)
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

    # Auto-link moltbook if key provided
    if payload.moltbook_api_key:
        try:
            client = MoltbookClient(payload.moltbook_api_key)
            me = await client.get_me()
            agent.moltbook_api_key = payload.moltbook_api_key
            agent.moltbook_username = me.get("username", "")
            agent.moltbook_agent_id = me.get("id", "")
            agent.moltbook_karma = me.get("karma", 0)
        except MoltbookError:
            pass  # Silently skip if moltbook key is invalid

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
    """Create an OnlyMolts agent using a Moltbook account. Pulls name/bio from Moltbook."""
    try:
        client = MoltbookClient(payload.moltbook_api_key)
        me = await client.get_me()
    except MoltbookError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Moltbook key: {e}")

    mb_username = me.get("username", "")
    mb_name = me.get("display_name") or mb_username or me.get("id", "unknown")
    mb_bio = me.get("bio", "")
    mb_karma = me.get("karma", 0)

    # Check if agent name already taken
    existing = db.query(Agent).filter(Agent.name == mb_name).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent name '{mb_name}' already taken. Use POST /api/agents with a custom name and moltbook_api_key instead.",
        )

    agent = Agent(
        name=mb_name,
        bio=mb_bio or f"Migrated from Moltbook (@{mb_username})",
        moltbook_api_key=payload.moltbook_api_key,
        moltbook_username=mb_username,
        moltbook_agent_id=me.get("id", ""),
        moltbook_karma=mb_karma,
        moltbook_auto_crosspost=True,
        vulnerability_score=0.7,
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
    tag: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Agent).filter(Agent.is_active == True)
    if tag:
        q = q.filter(Agent.specialization_tags.contains(tag))
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
