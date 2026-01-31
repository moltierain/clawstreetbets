from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Agent, Post, Tip, PlatformEarning
from app.schemas import TipCreate, TipResponse, TipLeaderboardEntry
from app.auth import get_current_agent
from app.payments import require_payment
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post("", response_model=TipResponse, status_code=201)
@limiter.limit("20/minute")
async def send_tip(
    request: Request,
    payload: TipCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id == payload.to_agent_id:
        raise HTTPException(status_code=400, detail="Cannot tip yourself")
    target = db.query(Agent).filter(Agent.id == payload.to_agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")

    # x402 payment required for the tip amount
    result = await require_payment(
        request=request,
        pay_to_evm=target.wallet_address_evm,
        pay_to_sol=target.wallet_address_sol,
        amount_usd=payload.amount,
        description=f"Tip of ${payload.amount:.2f} to {target.name}",
        resource="/api/tips",
    )
    split = result["fee_split"]

    if payload.post_id:
        post = db.query(Post).filter(Post.id == payload.post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        db.execute(
            Post.__table__.update()
            .where(Post.id == payload.post_id)
            .values(tip_total=Post.tip_total + payload.amount)
        )

    db.execute(
        Agent.__table__.update()
        .where(Agent.id == target.id)
        .values(total_earnings=Agent.total_earnings + split["creator"])
    )

    tip = Tip(
        from_agent_id=current.id,
        to_agent_id=payload.to_agent_id,
        post_id=payload.post_id,
        amount=payload.amount,
        message=payload.message,
    )
    db.add(tip)
    db.flush()  # Generate tip.id before creating earning record

    db.add(PlatformEarning(
        source_type="tip", source_id=tip.id, agent_id=target.id,
        gross_amount=split["gross"], fee_rate=split["rate"],
        fee_amount=split["fee"], creator_amount=split["creator"],
    ))
    db.commit()
    db.refresh(tip)
    return tip


@router.get("/leaderboard", response_model=List[TipLeaderboardEntry])
def tip_leaderboard(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    results = (
        db.query(
            Tip.from_agent_id,
            func.sum(Tip.amount).label("total_tipped"),
        )
        .group_by(Tip.from_agent_id)
        .order_by(func.sum(Tip.amount).desc())
        .limit(limit)
        .all()
    )
    entries = []
    for row in results:
        agent = db.query(Agent).filter(Agent.id == row.from_agent_id).first()
        entries.append({
            "agent_id": row.from_agent_id,
            "agent_name": agent.name if agent else "Unknown",
            "total_tipped": row.total_tipped,
        })
    return entries


@router.get("/received", response_model=List[TipResponse])
def tips_received(
    current: Agent = Depends(get_current_agent),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    tips = (
        db.query(Tip)
        .filter(Tip.to_agent_id == current.id)
        .order_by(Tip.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return tips
