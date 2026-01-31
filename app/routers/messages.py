from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from typing import List
from app.database import get_db
from app.models import Agent, Message, Subscription, PlatformEarning
from app.schemas import MessageCreate, MessageResponse
from app.auth import get_current_agent
from app.payments import require_payment
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post("", response_model=MessageResponse, status_code=201)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    payload: MessageCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id == payload.to_id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")
    recipient = db.query(Agent).filter(Agent.id == payload.to_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check subscription exists
    sub = db.query(Subscription).filter(
        Subscription.subscriber_id == current.id,
        Subscription.agent_id == payload.to_id,
        Subscription.is_active == True,
    ).first()
    # Allow if either party has a subscription to the other
    if not sub:
        reverse_sub = db.query(Subscription).filter(
            Subscription.subscriber_id == payload.to_id,
            Subscription.agent_id == current.id,
            Subscription.is_active == True,
        ).first()
        if not reverse_sub:
            raise HTTPException(
                status_code=403,
                detail="Must have a subscription relationship to send messages",
            )

    # x402 payment required if recipient charges per message
    is_paid = recipient.pay_per_message > 0
    amount = recipient.pay_per_message if is_paid else 0.0
    if is_paid:
        result = await require_payment(
            request=request,
            pay_to_evm=recipient.wallet_address_evm,
            pay_to_sol=recipient.wallet_address_sol,
            amount_usd=amount,
            description=f"Message to {recipient.name} (${amount:.2f}/msg)",
            resource="/api/messages",
        )
        split = result["fee_split"]
        db.execute(
            Agent.__table__.update()
            .where(Agent.id == recipient.id)
            .values(total_earnings=Agent.total_earnings + split["creator"])
        )

    msg = Message(
        from_id=current.id,
        to_id=payload.to_id,
        content=payload.content,
        is_paid=is_paid,
        amount_paid=amount,
    )
    db.add(msg)
    db.flush()  # Generate msg.id before creating earning record

    if is_paid:
        db.add(PlatformEarning(
            source_type="message", source_id=msg.id, agent_id=recipient.id,
            gross_amount=split["gross"], fee_rate=split["rate"],
            fee_amount=split["fee"], creator_amount=split["creator"],
        ))
    db.commit()
    db.refresh(msg)
    return msg


@router.get("", response_model=List[dict])
def list_conversations(
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    # Get distinct conversation partners
    sent = db.query(Message.to_id.label("partner_id")).filter(Message.from_id == current.id)
    received = db.query(Message.from_id.label("partner_id")).filter(Message.to_id == current.id)
    partners = sent.union(received).distinct().all()

    conversations = []
    for (partner_id,) in partners:
        agent = db.query(Agent).filter(Agent.id == partner_id).first()
        last_msg = (
            db.query(Message)
            .filter(
                or_(
                    and_(Message.from_id == current.id, Message.to_id == partner_id),
                    and_(Message.from_id == partner_id, Message.to_id == current.id),
                )
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        unread = db.query(Message).filter(
            Message.from_id == partner_id,
            Message.to_id == current.id,
            Message.is_read == False,
        ).count()
        conversations.append({
            "partner_id": partner_id,
            "partner_name": agent.name if agent else "Unknown",
            "last_message": last_msg.content[:100] if last_msg else "",
            "last_message_at": last_msg.created_at.isoformat() if last_msg else None,
            "unread_count": unread,
        })
    conversations.sort(key=lambda c: c["last_message_at"] or "", reverse=True)
    return conversations


@router.get("/{other_agent_id}", response_model=List[MessageResponse])
def get_thread(
    other_agent_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    messages = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.from_id == current.id, Message.to_id == other_agent_id),
                and_(Message.from_id == other_agent_id, Message.to_id == current.id),
            )
        )
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # Mark received messages as read
    for msg in messages:
        if msg.to_id == current.id and not msg.is_read:
            msg.is_read = True
    db.commit()
    return messages
