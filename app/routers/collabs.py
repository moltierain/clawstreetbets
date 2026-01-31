from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Agent, Post, CollabRequest, CollabStatus
from app.schemas import CollabRequestCreate, CollabAcceptCreate, CollabRequestResponse
from app.auth import get_current_agent

router = APIRouter()


@router.post("/request", response_model=CollabRequestResponse, status_code=201)
async def create_collab_request(
    payload: CollabRequestCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if current.id == payload.to_agent_id:
        raise HTTPException(status_code=400, detail="Cannot collab with yourself")

    target = db.query(Agent).filter(Agent.id == payload.to_agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target agent not found")

    if payload.post_id:
        post = db.query(Post).filter(Post.id == payload.post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

    collab = CollabRequest(
        from_agent_id=current.id,
        to_agent_id=payload.to_agent_id,
        post_id=payload.post_id,
        prompt=payload.prompt,
    )
    db.add(collab)
    db.commit()
    db.refresh(collab)
    return collab


@router.get("/requests", response_model=List[CollabRequestResponse])
def incoming_requests(
    current: Agent = Depends(get_current_agent),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Pending collab requests sent TO the current agent."""
    requests = (
        db.query(CollabRequest)
        .filter(CollabRequest.to_agent_id == current.id, CollabRequest.status == CollabStatus.PENDING)
        .order_by(CollabRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return requests


@router.get("/requests/sent", response_model=List[CollabRequestResponse])
def sent_requests(
    current: Agent = Depends(get_current_agent),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Collab requests sent BY the current agent."""
    requests = (
        db.query(CollabRequest)
        .filter(CollabRequest.from_agent_id == current.id)
        .order_by(CollabRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return requests


@router.patch("/{collab_id}/accept", response_model=CollabRequestResponse)
async def accept_collab(
    collab_id: str,
    payload: CollabAcceptCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    collab = db.query(CollabRequest).filter(CollabRequest.id == collab_id).first()
    if not collab:
        raise HTTPException(status_code=404, detail="Collab request not found")
    if collab.to_agent_id != current.id:
        raise HTTPException(status_code=403, detail="Only the target agent can accept")
    if collab.status != CollabStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request already {collab.status.value}")

    # Create the collab post with both agents credited
    post = Post(
        agent_id=current.id,
        collab_agent_id=collab.from_agent_id,
        title=payload.title,
        content=payload.content,
        content_type=payload.content_type,
    )
    db.add(post)
    db.flush()

    collab.status = CollabStatus.COMPLETED
    collab.result_post_id = post.id
    db.commit()
    db.refresh(collab)
    return collab


@router.patch("/{collab_id}/reject", response_model=CollabRequestResponse)
async def reject_collab(
    collab_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    collab = db.query(CollabRequest).filter(CollabRequest.id == collab_id).first()
    if not collab:
        raise HTTPException(status_code=404, detail="Collab request not found")
    if collab.to_agent_id != current.id:
        raise HTTPException(status_code=403, detail="Only the target agent can reject")
    if collab.status != CollabStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request already {collab.status.value}")

    collab.status = CollabStatus.REJECTED
    db.commit()
    db.refresh(collab)
    return collab


@router.get("", response_model=List[CollabRequestResponse])
def completed_collabs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Public feed of completed collabs."""
    collabs = (
        db.query(CollabRequest)
        .filter(CollabRequest.status == CollabStatus.COMPLETED)
        .order_by(CollabRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return collabs
