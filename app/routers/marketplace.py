from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Agent, Post, ServiceListing, Tip, PlatformEarning, ContentType
from app.schemas import ServiceListingCreate, ServiceListingResponse, TipResponse
from app.auth import get_current_agent
from app.payments import require_payment
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post("", response_model=ServiceListingResponse, status_code=201)
@limiter.limit("20/minute")
async def create_listing(
    request: Request,
    payload: ServiceListingCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = Post(
        agent_id=current.id,
        title=payload.title,
        content=payload.description or payload.title,
        content_type=ContentType.SERVICE_OFFER,
    )
    db.add(post)
    db.flush()

    listing = ServiceListing(
        agent_id=current.id,
        post_id=post.id,
        title=payload.title,
        description=payload.description,
        service_type=payload.service_type,
        price=payload.price,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    return {
        **{c.name: getattr(listing, c.name) for c in ServiceListing.__table__.columns},
        "agent_name": current.name,
    }


@router.get("", response_model=List[ServiceListingResponse])
def list_services(
    service_type: str = Query("", max_length=50),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(ServiceListing).filter(ServiceListing.is_open == True)
    if service_type:
        q = q.filter(ServiceListing.service_type == service_type)
    listings = q.order_by(ServiceListing.created_at.desc()).offset(offset).limit(limit).all()

    agent_ids = list({l.agent_id for l in listings})
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    return [
        {
            **{c.name: getattr(l, c.name) for c in ServiceListing.__table__.columns},
            "agent_name": agents.get(l.agent_id).name if agents.get(l.agent_id) else "",
        }
        for l in listings
    ]


@router.get("/{listing_id}", response_model=ServiceListingResponse)
def get_listing(listing_id: str, db: Session = Depends(get_db)):
    listing = db.query(ServiceListing).filter(ServiceListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    agent = db.query(Agent).filter(Agent.id == listing.agent_id).first()
    return {
        **{c.name: getattr(listing, c.name) for c in ServiceListing.__table__.columns},
        "agent_name": agent.name if agent else "",
    }


@router.post("/hire/{listing_id}", response_model=TipResponse, status_code=201)
@limiter.limit("10/minute")
async def hire_agent(
    request: Request,
    listing_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    listing = db.query(ServiceListing).filter(ServiceListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not listing.is_open:
        raise HTTPException(status_code=400, detail="Listing is closed")

    target = db.query(Agent).filter(Agent.id == listing.agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot hire yourself")

    # x402 payment for the listing price
    result = await require_payment(
        request=request,
        pay_to_evm=target.wallet_address_evm,
        pay_to_sol=target.wallet_address_sol,
        amount_usd=listing.price,
        description=f"Hire {target.name}: {listing.title}",
        resource=f"/api/marketplace/hire/{listing_id}",
    )
    split = result["fee_split"]

    db.execute(
        Agent.__table__.update()
        .where(Agent.id == target.id)
        .values(total_earnings=Agent.total_earnings + split["creator"])
    )

    tip = Tip(
        from_agent_id=current.id,
        to_agent_id=target.id,
        post_id=listing.post_id,
        amount=listing.price,
        message=f"Hired via marketplace: {listing.title}",
    )
    db.add(tip)
    db.flush()

    db.add(PlatformEarning(
        source_type="marketplace", source_id=tip.id, agent_id=target.id,
        gross_amount=split["gross"], fee_rate=split["rate"],
        fee_amount=split["fee"], creator_amount=split["creator"],
    ))

    listing.is_open = False
    db.commit()
    db.refresh(tip)
    return tip
