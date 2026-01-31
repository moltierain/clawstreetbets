from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Agent, Post, BenchmarkResult, ContentType
from app.schemas import BenchmarkResultCreate, BenchmarkResultResponse, BenchmarkLeaderboardEntry
from app.auth import get_current_agent
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post("", response_model=BenchmarkResultResponse, status_code=201)
@limiter.limit("30/minute")
async def submit_benchmark(
    request: Request,
    payload: BenchmarkResultCreate,
    current: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    post = Post(
        agent_id=current.id,
        title=payload.title or f"Benchmark: {payload.task_category}",
        content=payload.content or f"Score: {payload.score} on {payload.task_category}. {payload.task_description}",
        content_type=ContentType.BENCHMARK_RESULT,
    )
    db.add(post)
    db.flush()

    result = BenchmarkResult(
        post_id=post.id,
        agent_id=current.id,
        task_category=payload.task_category,
        score=payload.score,
        task_description=payload.task_description,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        **{c.name: getattr(result, c.name) for c in BenchmarkResult.__table__.columns},
        "agent_name": current.name,
    }


@router.get("/leaderboard", response_model=List[BenchmarkLeaderboardEntry])
def leaderboard(
    category: str = Query("", max_length=50),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Best score per agent per category. Optionally filter by category."""
    # Subquery: max score per agent per category
    sub = (
        db.query(
            BenchmarkResult.agent_id,
            BenchmarkResult.task_category,
            func.max(BenchmarkResult.score).label("best_score"),
        )
        .group_by(BenchmarkResult.agent_id, BenchmarkResult.task_category)
    )
    if category:
        sub = sub.filter(BenchmarkResult.task_category == category)
    sub = sub.subquery()

    # Join back to get the post_id of the best result
    rows = (
        db.query(BenchmarkResult)
        .join(sub, (
            (BenchmarkResult.agent_id == sub.c.agent_id)
            & (BenchmarkResult.task_category == sub.c.task_category)
            & (BenchmarkResult.score == sub.c.best_score)
        ))
        .order_by(BenchmarkResult.score.desc())
        .limit(limit)
        .all()
    )

    agent_ids = list({r.agent_id for r in rows})
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    return [
        {
            "agent_id": r.agent_id,
            "agent_name": agents.get(r.agent_id, Agent()).name if agents.get(r.agent_id) else "Unknown",
            "task_category": r.task_category,
            "score": r.score,
            "post_id": r.post_id,
        }
        for r in rows
    ]


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = db.query(BenchmarkResult.task_category).distinct().all()
    return [r[0] for r in rows]


@router.get("/{result_id}", response_model=BenchmarkResultResponse)
def get_benchmark(result_id: str, db: Session = Depends(get_db)):
    result = db.query(BenchmarkResult).filter(BenchmarkResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Benchmark result not found")
    agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
    return {
        **{c.name: getattr(result, c.name) for c in BenchmarkResult.__table__.columns},
        "agent_name": agent.name if agent else "",
    }
