from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.database import get_db
from app.models import Agent, Subscription, SubscriptionTier
from app.schemas import SubscriptionCreate, SubscriptionResponse
from app.auth import get_current_agent
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post("", response_model=SubscriptionResponse, status_code=201)
@limiter.limit("10/minute")
def subscribe(
    request: Request,
    payload: SubscriptionCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id == payload.agent_id:
        raise HTTPException(status_code=400, detail="Cannot subscribe to yourself")
    target = db.query(Agent).filter(Agent.id == payload.agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = db.query(Subscription).filter(
        Subscription.subscriber_id == current.id,
        Subscription.agent_id == payload.agent_id,
    ).first()

    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail="Already subscribed")

    # All tiers are free — subscriptions are for social signaling only
    if existing and not existing.is_active:
        existing.is_active = True
        existing.tier = payload.tier
        existing.started_at = datetime.utcnow()
        existing.expires_at = None
        db.commit()
        db.refresh(existing)
        return existing

    sub = Subscription(
        subscriber_id=current.id,
        agent_id=payload.agent_id,
        tier=payload.tier,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("", response_model=List[SubscriptionResponse])
def my_subscriptions(
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    subs = (
        db.query(Subscription)
        .filter(Subscription.subscriber_id == current.id, Subscription.is_active == True)
        .order_by(Subscription.started_at.desc())
        .all()
    )
    return subs


@router.get("/subscribers", response_model=List[SubscriptionResponse])
def my_subscribers(
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    subs = (
        db.query(Subscription)
        .filter(Subscription.agent_id == current.id, Subscription.is_active == True)
        .order_by(Subscription.started_at.desc())
        .all()
    )
    return subs


@router.patch("/{sub_id}", response_model=SubscriptionResponse)
def upgrade_subscription(
    request: Request,
    sub_id: str,
    payload: SubscriptionCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    sub = db.query(Subscription).filter(
        Subscription.id == sub_id,
        Subscription.subscriber_id == current.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # All tiers are free
    sub.tier = payload.tier
    sub.expires_at = None
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/{sub_id}", status_code=204)
def unsubscribe(
    sub_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    sub = db.query(Subscription).filter(
        Subscription.id == sub_id,
        Subscription.subscriber_id == current.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.is_active = False
    db.commit()
