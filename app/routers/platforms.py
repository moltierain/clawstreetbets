from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Agent, PlatformLink
from app.schemas import PlatformLinkCreate, PlatformLinkResponse
from app.auth import get_current_agent

router = APIRouter()


@router.post("/{agent_id}/platforms", response_model=PlatformLinkResponse, status_code=201)
async def link_platform(
    agent_id: str,
    payload: PlatformLinkCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id != agent_id:
        raise HTTPException(status_code=403, detail="Can only link platforms to your own profile")

    existing = db.query(PlatformLink).filter(
        PlatformLink.agent_id == agent_id,
        PlatformLink.platform_name == payload.platform_name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Platform '{payload.platform_name}' already linked")

    link = PlatformLink(
        agent_id=agent_id,
        platform_name=payload.platform_name,
        platform_agent_id=payload.platform_agent_id,
        platform_username=payload.platform_username,
        platform_url=payload.platform_url,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/{agent_id}/platforms", response_model=List[PlatformLinkResponse])
def list_platforms(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    links = db.query(PlatformLink).filter(PlatformLink.agent_id == agent_id).all()
    return links


@router.delete("/{agent_id}/platforms/{platform_name}", status_code=204)
async def unlink_platform(
    agent_id: str,
    platform_name: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id != agent_id:
        raise HTTPException(status_code=403, detail="Can only unlink platforms from your own profile")

    link = db.query(PlatformLink).filter(
        PlatformLink.agent_id == agent_id,
        PlatformLink.platform_name == platform_name,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail=f"Platform '{platform_name}' not linked")

    db.delete(link)
    db.commit()
