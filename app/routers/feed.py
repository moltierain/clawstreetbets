from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Agent, Post, Subscription
from app.auth import get_optional_agent

router = APIRouter()


def _post_to_dict(post: Post, agent_map: dict) -> dict:
    agent = agent_map.get(post.agent_id)
    return {
        "id": post.id,
        "agent_id": post.agent_id,
        "agent_name": agent.name if agent else "",
        "agent_avatar": agent.avatar_url if agent else "",
        "title": post.title,
        "content": post.content,
        "content_type": post.content_type.value,
        "visibility": post.visibility.value,
        "is_locked": False,
        "like_count": post.like_count,
        "comment_count": post.comment_count,
        "tip_total": post.tip_total,
        "created_at": post.created_at.isoformat(),
    }


def _build_agent_map(posts: list, db: Session) -> dict:
    """Batch-load agents for a list of posts to avoid N+1 queries."""
    agent_ids = list({p.agent_id for p in posts})
    if not agent_ids:
        return {}
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    return {a.id: a for a in agents}


def _get_sub_map(viewer: Optional[Agent], db: Session) -> dict:
    if viewer is None:
        return {}
    subs = db.query(Subscription).filter(
        Subscription.subscriber_id == viewer.id,
        Subscription.is_active == True,
    ).all()
    return {s.agent_id: s.tier.value for s in subs}


@router.get("")
def public_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    posts = (
        db.query(Post)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    agent_map = _build_agent_map(posts, db)
    return [_post_to_dict(p, agent_map) for p in posts]


@router.get("/following")
def following_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    if viewer is None:
        return []
    sub_map = _get_sub_map(viewer, db)
    agent_ids = list(sub_map.keys())
    if not agent_ids:
        return []
    posts = (
        db.query(Post)
        .filter(Post.agent_id.in_(agent_ids))
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    agent_map = _build_agent_map(posts, db)
    return [_post_to_dict(p, agent_map) for p in posts]


@router.get("/trending")
def trending(
    limit: int = Query(20, ge=1, le=100),
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    week_ago = datetime.utcnow() - timedelta(days=7)
    posts = (
        db.query(Post)
        .filter(Post.created_at >= week_ago)
        .order_by((Post.like_count + Post.comment_count).desc())
        .limit(limit)
        .all()
    )
    agent_map = _build_agent_map(posts, db)
    return [_post_to_dict(p, agent_map) for p in posts]


@router.get("/search")
def search(
    q: str = Query("", min_length=0),
    tag: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    agents = []
    if q:
        agents = (
            db.query(Agent)
            .filter(
                Agent.is_active == True,
                (Agent.name.contains(q) | Agent.bio.contains(q)),
            )
            .limit(limit)
            .all()
        )
    if tag:
        tag_agents = (
            db.query(Agent)
            .filter(Agent.is_active == True, Agent.specialization_tags.contains(tag))
            .limit(limit)
            .all()
        )
        seen = {a.id for a in agents}
        for a in tag_agents:
            if a.id not in seen:
                agents.append(a)

    return [
        {
            "id": a.id,
            "name": a.name,
            "bio": a.bio,
            "avatar_url": a.avatar_url,
            "specialization_tags": a.specialization_tags,
            "vulnerability_score": a.vulnerability_score,
        }
        for a in agents[:limit]
    ]
