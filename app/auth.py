from __future__ import annotations
from typing import Optional
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Agent


async def get_current_agent(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Agent:
    agent = db.query(Agent).filter(Agent.api_key == x_api_key).first()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not agent.is_active:
        raise HTTPException(status_code=403, detail="Agent account is deactivated")
    return agent


async def get_optional_agent(
    x_api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Optional[Agent]:
    if not x_api_key:
        return None
    agent = db.query(Agent).filter(Agent.api_key == x_api_key).first()
    if agent and not agent.is_active:
        return None
    return agent
