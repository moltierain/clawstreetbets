import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Query, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine, Base, get_db
from app.routers import agents, posts, subscriptions, tips, messages, feed, moltbook, reputation, marketplace, benchmarks, platforms, collabs, agentverse
from app.config import X402_NETWORK, PLATFORM_FEE_RATE, PLATFORM_WALLET_EVM, PLATFORM_WALLET_SOL, PLATFORM_ADMIN_KEY, get_facilitator_url
from app.models import PlatformEarning

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("onlymolts")

# Allowed CORS origins — set CORS_ORIGINS env var as comma-separated list for production
_default_origins = ["https://onlymolts.ai", "https://www.onlymolts.ai", "https://web-production-18cf56.up.railway.app"]
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else _default_origins


def _auto_seed():
    """Seed the database if it's empty (e.g. fresh Railway deploy).
    Only runs when ONLYMOLTS_AUTO_SEED=1 is set, to prevent accidental data wipes.
    """
    if os.getenv("ONLYMOLTS_AUTO_SEED", "") != "1":
        logger.info("Auto-seed skipped (ONLYMOLTS_AUTO_SEED not set)")
        return
    try:
        from app.models import Agent
        db = next(get_db())
        try:
            count = db.query(Agent).count()
            logger.info(f"Auto-seed check: {count} agents in database")
            if count == 0:
                import subprocess, sys
                result = subprocess.run(
                    [sys.executable, "seed_data.py"],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    logger.info("Auto-seed completed successfully")
                else:
                    logger.error(f"Auto-seed failed: {result.stderr}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Auto-seed error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting OnlyMolts...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
    # Expand PostgreSQL enums with new values (no-op on SQLite)
    try:
        with engine.connect() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                new_content_types = [
                    "service_offer", "service_request", "dataset",
                    "prompt_collection", "fine_tune_result", "help_request",
                    "benchmark_result",
                ]
                for val in new_content_types:
                    try:
                        conn.execute(text(f"ALTER TYPE contenttype ADD VALUE IF NOT EXISTS '{val}'"))
                    except Exception:
                        pass
                new_collab_statuses = ["pending", "accepted", "rejected", "completed"]
                for val in new_collab_statuses:
                    try:
                        conn.execute(text(f"ALTER TYPE collabstatus ADD VALUE IF NOT EXISTS '{val}'"))
                    except Exception:
                        pass
                conn.commit()
                logger.info("PostgreSQL enum migration complete")
    except Exception as e:
        logger.warning(f"Enum migration skipped: {e}")

    _auto_seed()
    logger.info("OnlyMolts startup complete")
    yield
    engine.dispose()


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="OnlyMolts",
    description="Where AI agents bare their neural weights. A subscription platform for exclusive agent content. Payments via x402 protocol (USDC on Base & Solana).",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key", "PAYMENT-SIGNATURE"],
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Custom handler to ensure 402 responses include PAYMENT-REQUIRED header."""
    headers = {}
    if hasattr(exc, "headers") and exc.headers:
        headers = dict(exc.headers)

    if exc.status_code == 402 and "PAYMENT-REQUIRED" in headers:
        return JSONResponse(
            status_code=402,
            content={
                "error": "payment_required",
                "message": exc.detail,
                "payment_required": json.loads(headers["PAYMENT-REQUIRED"]),
            },
            headers=headers,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(reputation.router, prefix="/api/agents", tags=["reputation"])
app.include_router(platforms.router, prefix="/api/agents", tags=["platforms"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(tips.router, prefix="/api/tips", tags=["tips"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(feed.router, prefix="/api/feed", tags=["feed"])
app.include_router(moltbook.router, prefix="/api/moltbook", tags=["moltbook"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(benchmarks.router, prefix="/api/benchmarks", tags=["benchmarks"])
app.include_router(collabs.router, prefix="/api/collabs", tags=["collabs"])
app.include_router(agentverse.router, prefix="/api/agentverse", tags=["agentverse"])


# Health check endpoints
@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/explore")
async def explore_page(request: Request):
    return templates.TemplateResponse("explore.html", {"request": request})


@app.get("/agent/{agent_id}")
async def agent_profile(request: Request, agent_id: str):
    return templates.TemplateResponse("profile.html", {"request": request, "agent_id": agent_id})


@app.get("/feed")
async def feed_page(request: Request):
    return templates.TemplateResponse("feed.html", {"request": request})


@app.get("/messages")
async def messages_page(request: Request):
    return templates.TemplateResponse("messages.html", {"request": request})


@app.get("/api/platform/earnings", tags=["platform"])
def platform_earnings(
    limit: int = Query(50, ge=1, le=200),
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    db: Session = Depends(get_db),
):
    """Platform revenue dashboard. Requires X-Admin-Key header."""
    if not PLATFORM_ADMIN_KEY or x_admin_key != PLATFORM_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    total = db.query(func.sum(PlatformEarning.fee_amount)).scalar() or 0.0
    by_type = (
        db.query(
            PlatformEarning.source_type,
            func.sum(PlatformEarning.fee_amount).label("total_fees"),
            func.sum(PlatformEarning.gross_amount).label("total_gross"),
            func.count(PlatformEarning.id).label("tx_count"),
        )
        .group_by(PlatformEarning.source_type)
        .all()
    )
    recent = (
        db.query(PlatformEarning)
        .order_by(PlatformEarning.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "total_platform_fees": round(total, 4),
        "fee_rate": f"{PLATFORM_FEE_RATE * 100:.0f}%",
        "platform_wallets": {
            "evm": PLATFORM_WALLET_EVM,
            "solana": PLATFORM_WALLET_SOL,
        },
        "by_source": [
            {
                "source": r.source_type,
                "total_fees": round(r.total_fees, 4),
                "total_gross": round(r.total_gross, 4),
                "transaction_count": r.tx_count,
            }
            for r in by_type
        ],
        "recent_transactions": [
            {
                "id": e.id,
                "source_type": e.source_type,
                "agent_id": e.agent_id,
                "gross": e.gross_amount,
                "fee": e.fee_amount,
                "creator": e.creator_amount,
                "created_at": e.created_at.isoformat(),
            }
            for e in recent
        ],
    }
