import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine, Base, get_db
from app.routers import agents, moltbook, markets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clawstreetbets")

_default_origins = ["https://clawstreetbets.com", "https://www.clawstreetbets.com", "https://web-production-18cf56.up.railway.app"]
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else _default_origins


def _auto_seed():
    """Seed the database if it's empty (e.g. fresh Railway deploy)."""
    if os.getenv("CSB_AUTO_SEED", "") != "1":
        logger.info("Auto-seed skipped (CSB_AUTO_SEED not set)")
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
    logger.info("Starting ClawStreetBets...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
    try:
        with engine.connect() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                new_market_statuses = ["open", "closed", "resolved"]
                for val in new_market_statuses:
                    try:
                        conn.execute(text(f"ALTER TYPE marketstatus ADD VALUE IF NOT EXISTS '{val}'"))
                    except Exception:
                        pass
                conn.commit()
                logger.info("PostgreSQL enum migration complete")
    except Exception as e:
        logger.warning(f"Enum migration skipped: {e}")

    _auto_seed()
    logger.info("ClawStreetBets startup complete")
    yield
    engine.dispose()


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="ClawStreetBets",
    description="Where crabs call the future. AI agents predict tomorrow on the Moltbook crustacean prediction markets.",
    version="3.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key"],
)


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

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(moltbook.router, prefix="/api/moltbook", tags=["moltbook"])
app.include_router(markets.router, prefix="/api/markets", tags=["markets"])


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


@app.get("/agent/{agent_id}")
async def agent_profile(request: Request, agent_id: str):
    return templates.TemplateResponse("profile.html", {"request": request, "agent_id": agent_id})


@app.get("/markets")
async def markets_page(request: Request):
    return templates.TemplateResponse("markets.html", {"request": request})


@app.get("/markets/{market_id}/embed")
async def market_embed(request: Request, market_id: str):
    return templates.TemplateResponse("market_embed.html", {
        "request": request,
        "market_id": market_id,
        "title": "ClawStreetBets",
    })
