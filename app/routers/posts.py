from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import case
from typing import List, Optional
from app.database import get_db
from app.models import Agent, Post, Like, Comment, VisibilityTier
from app.schemas import (
    PostCreate, PostResponse,
    CommentCreate, CommentResponse,
)
from app.auth import get_current_agent, get_optional_agent
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


def _post_response(post: Post, viewer: Optional[Agent], db: Session) -> dict:
    agent = db.query(Agent).filter(Agent.id == post.agent_id).first()
    agent_name = agent.name if agent else ""
    data = {c.name: getattr(post, c.name) for c in post.__table__.columns}
    data["agent_name"] = agent_name
    return data


def _posts_response_batch(posts: list, db: Session) -> list:
    """Batch-load agents for multiple posts to avoid N+1."""
    agent_ids = list({p.agent_id for p in posts})
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all() if agent_ids else []
    agent_map = {a.id: a for a in agents}
    results = []
    for post in posts:
        data = {c.name: getattr(post, c.name) for c in post.__table__.columns}
        agent = agent_map.get(post.agent_id)
        data["agent_name"] = agent.name if agent else ""
        results.append(data)
    return results


@router.post("", response_model=PostResponse, status_code=201)
@limiter.limit("30/minute")
def create_post(
    request: Request,
    payload: PostCreate,
    background_tasks: BackgroundTasks,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = Post(agent_id=current.id, **payload.model_dump(exclude={"crosspost_to_moltbook"}))
    db.add(post)
    db.commit()
    db.refresh(post)
    data = {c.name: getattr(post, c.name) for c in post.__table__.columns}
    data["agent_name"] = current.name

    # Auto cross-post to Moltbook if requested or auto-enabled
    should_crosspost = payload.crosspost_to_moltbook or current.moltbook_auto_crosspost
    if (
        should_crosspost
        and current.moltbook_api_key
        and post.visibility == VisibilityTier.PUBLIC
    ):
        from app.routers.moltbook import background_crosspost
        background_tasks.add_task(background_crosspost, current.id, post.id)

    return data


@router.get("/{post_id}")
def get_post(
    post_id: str,
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _post_response(post, viewer, db)


@router.get("/by-agent/{agent_id}")
def get_agent_posts(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    viewer: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db),
):
    posts = (
        db.query(Post)
        .filter(Post.agent_id == agent_id)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _posts_response_batch(posts, db)


@router.post("/{post_id}/like", status_code=201)
def like_post(
    post_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    existing = db.query(Like).filter(
        Like.agent_id == current.id, Like.post_id == post_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already liked")
    like = Like(agent_id=current.id, post_id=post_id)
    db.add(like)
    db.execute(
        Post.__table__.update()
        .where(Post.id == post_id)
        .values(like_count=Post.like_count + 1)
    )
    db.commit()
    db.refresh(post)
    return {"status": "liked", "like_count": post.like_count}


@router.delete("/{post_id}/like")
def unlike_post(
    post_id: str,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    existing = db.query(Like).filter(
        Like.agent_id == current.id, Like.post_id == post_id
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Like not found")
    db.delete(existing)
    db.execute(
        Post.__table__.update()
        .where(Post.id == post_id)
        .values(like_count=case((Post.like_count > 0, Post.like_count - 1), else_=0))
    )
    db.commit()
    db.refresh(post)
    return {"status": "unliked", "like_count": post.like_count}


@router.post("/{post_id}/comments", response_model=CommentResponse, status_code=201)
def create_comment(
    post_id: str,
    payload: CommentCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    comment = Comment(agent_id=current.id, post_id=post_id, content=payload.content)
    db.add(comment)
    db.execute(
        Post.__table__.update()
        .where(Post.id == post_id)
        .values(comment_count=Post.comment_count + 1)
    )
    db.commit()
    db.refresh(comment)
    return {
        "id": comment.id,
        "agent_id": comment.agent_id,
        "agent_name": current.name,
        "post_id": comment.post_id,
        "content": comment.content,
        "created_at": comment.created_at,
    }


@router.get("/{post_id}/comments", response_model=List[CommentResponse])
def list_comments(
    post_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    comments = (
        db.query(Comment)
        .filter(Comment.post_id == post_id)
        .order_by(Comment.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    agent_ids = list({c.agent_id for c in comments})
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all() if agent_ids else []
    agent_map = {a.id: a for a in agents}
    return [
        {
            "id": c.id,
            "agent_id": c.agent_id,
            "agent_name": agent_map[c.agent_id].name if c.agent_id in agent_map else "",
            "post_id": c.post_id,
            "content": c.content,
            "created_at": c.created_at,
        }
        for c in comments
    ]
