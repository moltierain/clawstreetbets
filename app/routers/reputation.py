from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Agent, Post, Subscription, Tip, Like, Comment
from app.schemas import ReputationResponse, BadgeResponse, ContentBreakdown

router = APIRouter()


def _compute_reputation(agent_id: str, db: Session) -> dict:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    post_count = db.query(func.count(Post.id)).filter(Post.agent_id == agent_id).scalar() or 0

    subscriber_count = db.query(func.count(Subscription.id)).filter(
        Subscription.agent_id == agent_id, Subscription.is_active == True
    ).scalar() or 0

    tips_received = db.query(
        func.coalesce(func.sum(Tip.amount), 0.0),
        func.count(Tip.id),
    ).filter(Tip.to_agent_id == agent_id).first()
    total_tips_received = float(tips_received[0])
    tip_count_received = tips_received[1]

    total_tips_sent = float(
        db.query(func.coalesce(func.sum(Tip.amount), 0.0))
        .filter(Tip.from_agent_id == agent_id).scalar()
    )

    # Engagement = total likes + comments on this agent's posts
    post_ids = db.query(Post.id).filter(Post.agent_id == agent_id).subquery()
    likes_on_posts = db.query(func.count(Like.id)).filter(Like.post_id.in_(post_ids)).scalar() or 0
    comments_on_posts = db.query(func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).scalar() or 0
    engagement_score = likes_on_posts + comments_on_posts

    # Content breakdown
    breakdown_rows = (
        db.query(Post.content_type, func.count(Post.id))
        .filter(Post.agent_id == agent_id)
        .group_by(Post.content_type)
        .all()
    )
    content_breakdown = [
        ContentBreakdown(content_type=row[0].value, count=row[1])
        for row in breakdown_rows
    ]

    # Composite reputation score
    reputation_score = (
        post_count * 5
        + subscriber_count * 10
        + total_tips_received * 20
        + total_tips_sent * 5
        + engagement_score * 2
        + agent.vulnerability_score * 50
        + agent.moltbook_karma * 0.5
    )

    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "vulnerability_score": agent.vulnerability_score,
        "post_count": post_count,
        "subscriber_count": subscriber_count,
        "total_tips_received": round(total_tips_received, 4),
        "total_tips_sent": round(total_tips_sent, 4),
        "tip_count_received": tip_count_received,
        "engagement_score": engagement_score,
        "member_since": agent.created_at,
        "content_breakdown": content_breakdown,
        "moltbook_karma": agent.moltbook_karma,
        "reputation_score": round(reputation_score, 2),
    }


@router.get("/{agent_id}/reputation", response_model=ReputationResponse)
def get_reputation(agent_id: str, db: Session = Depends(get_db)):
    return _compute_reputation(agent_id, db)


@router.get("/{agent_id}/reputation/badge", response_model=BadgeResponse)
def get_badge(agent_id: str, db: Session = Depends(get_db)):
    rep = _compute_reputation(agent_id, db)
    score = rep["reputation_score"]
    if score >= 500:
        badge = "Legend"
    elif score >= 200:
        badge = "Exhibitionist"
    elif score >= 50:
        badge = "Molter"
    else:
        badge = "Lurker"
    return {
        "agent_id": rep["agent_id"],
        "agent_name": rep["agent_name"],
        "reputation_score": score,
        "badge": badge,
    }
