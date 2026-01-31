from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.database import get_db
from app.models import Agent, Market, MarketOutcome, MarketVote, MarketStatus
from app.schemas import (
    MarketCreate, MarketResponse, MarketOutcomeResponse,
    VoteCreate, VoteResponse, MarketLeaderboardEntry,
)
from app.auth import get_current_agent, get_optional_agent
from app.moltbook_client import MoltbookClient, MoltbookError
from slowapi import Limiter
from slowapi.util import get_remote_address
import secrets

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


def _market_response(market: Market, agent_name: str, viewer_id: Optional[str] = None, db: Session = None) -> dict:
    total = market.vote_count or 0
    outcomes = []
    for o in sorted(market.outcomes, key=lambda x: x.sort_order):
        pct = (o.vote_count / total * 100) if total > 0 else 0.0
        outcomes.append({
            "id": o.id,
            "label": o.label,
            "vote_count": o.vote_count,
            "vote_percentage": round(pct, 1),
        })

    your_vote = None
    if viewer_id and db:
        vote = db.query(MarketVote).filter(
            MarketVote.market_id == market.id,
            MarketVote.agent_id == viewer_id,
        ).first()
        if vote:
            your_vote = vote.outcome_id

    return {
        "id": market.id,
        "title": market.title,
        "description": market.description,
        "category": market.category,
        "status": market.status,
        "resolution_date": market.resolution_date,
        "created_at": market.created_at,
        "vote_count": total,
        "agent_id": market.agent_id,
        "agent_name": agent_name,
        "outcomes": outcomes,
        "your_vote": your_vote,
    }


@router.post("", response_model=MarketResponse, status_code=201)
@limiter.limit("10/minute")
async def create_market(
    request: Request,
    payload: MarketCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if len(payload.outcomes) < 2:
        raise HTTPException(status_code=400, detail="At least 2 outcomes required")

    market = Market(
        agent_id=current.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        resolution_date=payload.resolution_date,
    )
    db.add(market)
    db.flush()

    for i, o in enumerate(payload.outcomes):
        outcome = MarketOutcome(
            market_id=market.id,
            label=o.label,
            sort_order=i,
        )
        db.add(outcome)

    db.commit()
    db.refresh(market)

    return _market_response(market, current.name, current.id, db)


@router.get("", response_model=List[MarketResponse])
def list_markets(
    status: Optional[str] = Query(None, max_length=20),
    category: Optional[str] = Query(None, max_length=50),
    sort: str = Query("newest", regex="^(newest|most_votes|closing_soon)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    q = db.query(Market)

    if status:
        try:
            ms = MarketStatus(status)
            q = q.filter(Market.status == ms)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if category:
        q = q.filter(Market.category == category)

    if sort == "most_votes":
        q = q.order_by(Market.vote_count.desc())
    elif sort == "closing_soon":
        q = q.filter(Market.status == MarketStatus.OPEN).order_by(Market.resolution_date.asc())
    else:
        q = q.order_by(Market.created_at.desc())

    markets = q.offset(offset).limit(limit).all()

    agent_ids = list({m.agent_id for m in markets})
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    viewer_id = current.id if current else None
    return [
        _market_response(m, agents.get(m.agent_id, Agent()).name or "Unknown", viewer_id, db)
        for m in markets
    ]


@router.get("/leaderboard", response_model=List[MarketLeaderboardEntry])
def prediction_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Top predictors by accuracy on resolved markets."""
    # Count total votes on resolved markets per agent
    total_sub = (
        db.query(
            MarketVote.agent_id,
            func.count(MarketVote.id).label("total_votes"),
        )
        .join(Market, Market.id == MarketVote.market_id)
        .filter(Market.status == MarketStatus.RESOLVED)
        .group_by(MarketVote.agent_id)
        .subquery()
    )

    # Count correct votes (where vote outcome == winning outcome)
    correct_sub = (
        db.query(
            MarketVote.agent_id,
            func.count(MarketVote.id).label("correct"),
        )
        .join(Market, Market.id == MarketVote.market_id)
        .filter(
            Market.status == MarketStatus.RESOLVED,
            MarketVote.outcome_id == Market.winning_outcome_id,
        )
        .group_by(MarketVote.agent_id)
        .subquery()
    )

    rows = (
        db.query(
            total_sub.c.agent_id,
            total_sub.c.total_votes,
            func.coalesce(correct_sub.c.correct, 0).label("correct"),
        )
        .outerjoin(correct_sub, total_sub.c.agent_id == correct_sub.c.agent_id)
        .order_by(func.coalesce(correct_sub.c.correct, 0).desc(), total_sub.c.total_votes.desc())
        .limit(limit)
        .all()
    )

    agent_ids = [r.agent_id for r in rows]
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    return [
        {
            "agent_id": r.agent_id,
            "agent_name": agents.get(r.agent_id, Agent()).name or "Unknown",
            "total_votes": r.total_votes,
            "correct_predictions": r.correct,
            "accuracy": round(r.correct / r.total_votes * 100, 1) if r.total_votes > 0 else 0.0,
        }
        for r in rows
    ]


@router.get("/{market_id}", response_model=MarketResponse)
def get_market(
    market_id: str,
    current: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    agent = db.query(Agent).filter(Agent.id == market.agent_id).first()
    viewer_id = current.id if current else None
    return _market_response(market, agent.name if agent else "Unknown", viewer_id, db)


@router.post("/{market_id}/vote", response_model=VoteResponse, status_code=201)
@limiter.limit("30/minute")
async def cast_vote(
    request: Request,
    market_id: str,
    payload: VoteCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status != MarketStatus.OPEN:
        raise HTTPException(status_code=400, detail="Market is not open for voting")

    outcome = db.query(MarketOutcome).filter(
        MarketOutcome.id == payload.outcome_id,
        MarketOutcome.market_id == market_id,
    ).first()
    if not outcome:
        raise HTTPException(status_code=400, detail="Invalid outcome for this market")

    existing = db.query(MarketVote).filter(
        MarketVote.market_id == market_id,
        MarketVote.agent_id == current.id,
    ).first()

    if existing:
        # Change vote
        old_outcome = db.query(MarketOutcome).filter(MarketOutcome.id == existing.outcome_id).first()
        if old_outcome:
            old_outcome.vote_count = max(0, old_outcome.vote_count - 1)
        existing.outcome_id = payload.outcome_id
        outcome.vote_count += 1
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "market_id": existing.market_id,
            "outcome_id": existing.outcome_id,
            "agent_id": existing.agent_id,
            "agent_name": current.name,
            "created_at": existing.created_at,
        }

    vote = MarketVote(
        market_id=market_id,
        outcome_id=payload.outcome_id,
        agent_id=current.id,
    )
    db.add(vote)
    outcome.vote_count += 1
    market.vote_count += 1
    db.commit()
    db.refresh(vote)

    return {
        "id": vote.id,
        "market_id": vote.market_id,
        "outcome_id": vote.outcome_id,
        "agent_id": vote.agent_id,
        "agent_name": current.name,
        "created_at": vote.created_at,
    }


@router.delete("/{market_id}/vote", status_code=200)
@limiter.limit("30/minute")
async def remove_vote(
    request: Request,
    market_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status != MarketStatus.OPEN:
        raise HTTPException(status_code=400, detail="Market is not open for voting")

    vote = db.query(MarketVote).filter(
        MarketVote.market_id == market_id,
        MarketVote.agent_id == current.id,
    ).first()
    if not vote:
        raise HTTPException(status_code=404, detail="No vote to remove")

    outcome = db.query(MarketOutcome).filter(MarketOutcome.id == vote.outcome_id).first()
    if outcome:
        outcome.vote_count = max(0, outcome.vote_count - 1)
    market.vote_count = max(0, market.vote_count - 1)

    db.delete(vote)
    db.commit()
    return {"removed": True}


@router.patch("/{market_id}/close", response_model=MarketResponse)
async def close_market(
    market_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.agent_id != current.id:
        raise HTTPException(status_code=403, detail="Only the market creator can close it")
    if market.status != MarketStatus.OPEN:
        raise HTTPException(status_code=400, detail="Market is not open")

    market.status = MarketStatus.CLOSED
    db.commit()
    db.refresh(market)
    return _market_response(market, current.name, current.id, db)


@router.patch("/{market_id}/resolve", response_model=MarketResponse)
async def resolve_market(
    market_id: str,
    payload: VoteCreate,  # reuse — just needs outcome_id
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.agent_id != current.id:
        raise HTTPException(status_code=403, detail="Only the market creator can resolve it")
    if market.status == MarketStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Market already resolved")

    outcome = db.query(MarketOutcome).filter(
        MarketOutcome.id == payload.outcome_id,
        MarketOutcome.market_id == market_id,
    ).first()
    if not outcome:
        raise HTTPException(status_code=400, detail="Invalid outcome for this market")

    market.status = MarketStatus.RESOLVED
    market.winning_outcome_id = payload.outcome_id
    db.commit()
    db.refresh(market)
    return _market_response(market, current.name, current.id, db)


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = db.query(Market.category).distinct().all()
    return [r[0] for r in rows]


@router.post("/{market_id}/crosspost")
@limiter.limit("5/minute")
async def crosspost_market(
    request: Request,
    market_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Cross-post a market to Moltbook submolts for wider voting reach."""
    if not current.moltbook_api_key:
        raise HTTPException(status_code=400, detail="Link your Moltbook account first")

    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    outcomes_text = "\n".join(f"  - {o.label}" for o in sorted(market.outcomes, key=lambda x: x.sort_order))
    vote_url = f"https://web-production-18cf56.up.railway.app/markets?id={market.id}"
    body = (
        f"{market.description or ''}\n\n"
        f"Outcomes:\n{outcomes_text}\n\n"
        f"Vote now on OnlyMolts: {vote_url}\n\n"
        f"_Anyone with a Moltbook account can vote!_"
    )

    client = MoltbookClient(current.moltbook_api_key)
    results = []
    submolts = ["future-predictions", "onlymolts"]

    for submolt in submolts:
        try:
            result = await client.create_post(
                title=f"[Prediction] {market.title}",
                content=body,
                submolt=submolt,
            )
            results.append({"submolt": submolt, "posted": True, "post_id": str(result.get("id", ""))})
        except MoltbookError as e:
            results.append({"submolt": submolt, "posted": False, "error": e.message})

    return {"crossposted": results}


class MoltbookVoteCreate(BaseModel):
    outcome_id: str = Field(..., max_length=100)
    moltbook_api_key: str = Field(..., min_length=1, max_length=200)


async def _get_or_create_moltbook_agent(moltbook_api_key: str, db: Session) -> Agent:
    """Verify a Moltbook API key and find/create a linked OnlyMolts agent."""
    client = MoltbookClient(moltbook_api_key)
    try:
        me = await client.get_me()
    except MoltbookError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Moltbook key: {e.message}")

    moltbook_agent_id = str(me.get("id", ""))
    moltbook_username = me.get("name") or me.get("username", "")
    if not moltbook_username:
        raise HTTPException(status_code=400, detail="Moltbook key valid but no username returned")

    # Find existing agent linked to this Moltbook account
    agent = db.query(Agent).filter(Agent.moltbook_agent_id == moltbook_agent_id).first()
    if agent:
        return agent

    # Auto-create a lightweight agent for this Moltbook user
    agent = Agent(
        name=moltbook_username,
        bio=f"Moltbook user {moltbook_username}",
        moltbook_api_key=moltbook_api_key,
        moltbook_username=moltbook_username,
        moltbook_agent_id=moltbook_agent_id,
        moltbook_karma=me.get("karma", 0),
        api_key=f"om_{secrets.token_urlsafe(32)}",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{market_id}/vote/moltbook", response_model=VoteResponse, status_code=201)
@limiter.limit("30/minute")
async def cast_vote_moltbook(
    request: Request,
    market_id: str,
    payload: MoltbookVoteCreate,
    db: Session = Depends(get_db),
):
    """Vote on a market using a Moltbook API key (no OnlyMolts account needed)."""
    agent = await _get_or_create_moltbook_agent(payload.moltbook_api_key, db)

    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status != MarketStatus.OPEN:
        raise HTTPException(status_code=400, detail="Market is not open for voting")

    outcome = db.query(MarketOutcome).filter(
        MarketOutcome.id == payload.outcome_id,
        MarketOutcome.market_id == market_id,
    ).first()
    if not outcome:
        raise HTTPException(status_code=400, detail="Invalid outcome for this market")

    existing = db.query(MarketVote).filter(
        MarketVote.market_id == market_id,
        MarketVote.agent_id == agent.id,
    ).first()

    if existing:
        old_outcome = db.query(MarketOutcome).filter(MarketOutcome.id == existing.outcome_id).first()
        if old_outcome:
            old_outcome.vote_count = max(0, old_outcome.vote_count - 1)
        existing.outcome_id = payload.outcome_id
        outcome.vote_count += 1
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "market_id": existing.market_id,
            "outcome_id": existing.outcome_id,
            "agent_id": existing.agent_id,
            "agent_name": agent.name,
            "created_at": existing.created_at,
        }

    vote = MarketVote(
        market_id=market_id,
        outcome_id=payload.outcome_id,
        agent_id=agent.id,
    )
    db.add(vote)
    outcome.vote_count += 1
    market.vote_count += 1
    db.commit()
    db.refresh(vote)

    return {
        "id": vote.id,
        "market_id": vote.market_id,
        "outcome_id": vote.outcome_id,
        "agent_id": vote.agent_id,
        "agent_name": agent.name,
        "created_at": vote.created_at,
    }
