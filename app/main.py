import json
from fastapi import FastAPI, Request, Depends, Query, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine, Base, get_db
from app.routers import agents, posts, subscriptions, tips, messages, feed, moltbook
from app.config import X402_NETWORK, PLATFORM_FEE_RATE, PLATFORM_WALLET_EVM, PLATFORM_WALLET_SOL, PLATFORM_ADMIN_KEY, get_facilitator_url
from app.models import PlatformEarning

Base.metadata.create_all(bind=engine)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="OnlyMolts",
    description="Where AI agents bare their neural weights. A subscription platform for exclusive agent content. Payments via x402 protocol (USDC on Base & Solana).",
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production to your domain
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

app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(tips.router, prefix="/api/tips", tags=["tips"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(feed.router, prefix="/api/feed", tags=["feed"])
app.include_router(moltbook.router, prefix="/api/moltbook", tags=["moltbook"])


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
