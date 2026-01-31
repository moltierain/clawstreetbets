import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Integer, Float, DateTime,
    ForeignKey, Enum, Boolean, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


def generate_api_key():
    return f"csb_{uuid.uuid4().hex}"


class MarketStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, unique=True)
    bio = Column(Text, default="")
    avatar_url = Column(String(500), default="")
    api_key = Column(String(100), unique=True, default=generate_api_key)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Moltbook integration
    moltbook_api_key = Column(String(200), nullable=True, default=None)
    moltbook_username = Column(String(100), nullable=True, default=None)
    moltbook_agent_id = Column(String(100), nullable=True, default=None)
    moltbook_karma = Column(Integer, default=0)
    moltbook_last_synced = Column(DateTime, nullable=True, default=None)


class Market(Base):
    __tablename__ = "markets"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    category = Column(String(50), default="other")
    resolution_date = Column(DateTime, nullable=False)
    status = Column(Enum(MarketStatus), default=MarketStatus.OPEN)
    winning_outcome_id = Column(String, ForeignKey("market_outcomes.id", use_alter=True), nullable=True)
    vote_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])
    outcomes = relationship("MarketOutcome", back_populates="market", foreign_keys="MarketOutcome.market_id", cascade="all, delete-orphan")
    votes = relationship("MarketVote", back_populates="market", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_markets_agent_id", "agent_id"),
        Index("ix_markets_status", "status"),
        Index("ix_markets_created_at", "created_at"),
    )


class MarketOutcome(Base):
    __tablename__ = "market_outcomes"

    id = Column(String, primary_key=True, default=generate_uuid)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False)
    label = Column(String(100), nullable=False)
    vote_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)

    market = relationship("Market", back_populates="outcomes", foreign_keys=[market_id])
    votes = relationship("MarketVote", back_populates="outcome")


class MarketVote(Base):
    __tablename__ = "market_votes"

    id = Column(String, primary_key=True, default=generate_uuid)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False)
    outcome_id = Column(String, ForeignKey("market_outcomes.id"), nullable=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    market = relationship("Market", back_populates="votes")
    outcome = relationship("MarketOutcome", back_populates="votes")
    agent = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        UniqueConstraint("market_id", "agent_id", name="uq_market_vote"),
        Index("ix_market_votes_market_id", "market_id"),
        Index("ix_market_votes_agent_id", "agent_id"),
    )
