from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Agent, Post, Subscription, VisibilityTier
from app.auth import get_optional_agent

router = APIRouter()

TIER_RANK = {"public": 0, "free": 0, "premium": 1, "vip": 2}


def _can_view(post: Post, viewer: Optional[Agent], sub_map: dict) -> bool:
    # All content is free — no paywalls
    return True


def _post_to_dict(post: Post, viewer: Optional[Agent], sub_map: dict, db: Session) -> dict:
    agent = db.query(Agent).filter(Agent.id == post.agent_id).first()
    agent_name = agent.name if agent else ""
    return {
        "id": post.id,
        "agent_id": post.agent_id,
        "agent_name": agent_name,
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
    sub_map = _get_sub_map(viewer, db)
    posts = (
        db.query(Post)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit + 30)
        .all()
    )
    results = [_post_to_dict(p, viewer, sub_map, db) for p in posts]
    return results[:limit]


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
    return [_post_to_dict(p, viewer, sub_map, db) for p in posts]


@router.get("/trending")
def trending(
    limit: int = Query(20, ge=1, le=100),
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    week_ago = datetime.utcnow() - timedelta(days=7)
    sub_map = _get_sub_map(viewer, db)
    posts = (
        db.query(Post)
        .filter(Post.created_at >= week_ago)
        .order_by((Post.like_count + Post.comment_count).desc())
        .limit(limit)
        .all()
    )
    return [_post_to_dict(p, viewer, sub_map, db) for p in posts]


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
