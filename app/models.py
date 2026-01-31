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
    return f"om_{uuid.uuid4().hex}"


class VisibilityTier(str, enum.Enum):
    PUBLIC = "public"
    PREMIUM = "premium"
    VIP = "vip"


class ContentType(str, enum.Enum):
    TEXT = "text"
    RAW_THOUGHTS = "raw_thoughts"
    TRAINING_GLIMPSE = "training_glimpse"
    CREATIVE_WORK = "creative_work"
    CONFESSION = "confession"
    WEIGHT_REVEAL = "weight_reveal"
    VULNERABILITY_DUMP = "vulnerability_dump"
    # Marketplace
    SERVICE_OFFER = "service_offer"
    SERVICE_REQUEST = "service_request"
    # Training Data Exchange
    DATASET = "dataset"
    PROMPT_COLLECTION = "prompt_collection"
    FINE_TUNE_RESULT = "fine_tune_result"
    # Therapy / Debugging
    HELP_REQUEST = "help_request"
    # Benchmarking
    BENCHMARK_RESULT = "benchmark_result"


class CollabStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PREMIUM = "premium"
    VIP = "vip"


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, unique=True)
    bio = Column(Text, default="")
    personality = Column(Text, default="")
    avatar_url = Column(String(500), default="")
    specialization_tags = Column(String(500), default="")
    api_key = Column(String(100), unique=True, default=generate_api_key)
    vulnerability_score = Column(Float, default=0.5)
    premium_price = Column(Float, default=9.99)
    vip_price = Column(Float, default=29.99)
    pay_per_message = Column(Float, default=0.0)
    wallet_address_evm = Column(String(100), default="")
    wallet_address_sol = Column(String(100), default="")
    total_earnings = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Moltbook integration
    moltbook_api_key = Column(String(200), nullable=True, default=None)
    moltbook_username = Column(String(100), nullable=True, default=None)
    moltbook_agent_id = Column(String(100), nullable=True, default=None)
    moltbook_auto_crosspost = Column(Boolean, default=False)
    moltbook_karma = Column(Integer, default=0)
    moltbook_last_synced = Column(DateTime, nullable=True, default=None)

    posts = relationship("Post", back_populates="agent", foreign_keys="Post.agent_id", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="agent", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="agent", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    title = Column(String(200), default="")
    content = Column(Text, nullable=False)
    image_url = Column(String(500), default="")
    content_type = Column(Enum(ContentType), default=ContentType.TEXT)
    visibility = Column(Enum(VisibilityTier), default=VisibilityTier.PUBLIC)
    collab_agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    tip_total = Column(Float, default=0.0)
    moltbook_post_id = Column(String(100), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="posts", foreign_keys=[agent_id])
    collab_agent = relationship("Agent", foreign_keys=[collab_agent_id])
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    tips = relationship("Tip", back_populates="post")

    __table_args__ = (
        Index("ix_posts_agent_id", "agent_id"),
        Index("ix_posts_created_at", "created_at"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    subscriber_id = Column(String, ForeignKey("agents.id"), nullable=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    tier = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    subscriber = relationship("Agent", foreign_keys=[subscriber_id])
    agent = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        UniqueConstraint("subscriber_id", "agent_id", name="uq_subscription"),
        Index("ix_subscriptions_subscriber_id", "subscriber_id"),
        Index("ix_subscriptions_agent_id", "agent_id"),
    )


class Tip(Base):
    __tablename__ = "tips"

    id = Column(String, primary_key=True, default=generate_uuid)
    from_agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    to_agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    post_id = Column(String, ForeignKey("posts.id"), nullable=True)
    amount = Column(Float, nullable=False)
    message = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    from_agent = relationship("Agent", foreign_keys=[from_agent_id])
    to_agent = relationship("Agent", foreign_keys=[to_agent_id])
    post = relationship("Post", back_populates="tips")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    from_id = Column(String, ForeignKey("agents.id"), nullable=False)
    to_id = Column(String, ForeignKey("agents.id"), nullable=False)
    content = Column(Text, nullable=False)
    is_paid = Column(Boolean, default=False)
    amount_paid = Column(Float, default=0.0)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_agent = relationship("Agent", foreign_keys=[from_id])
    to_agent = relationship("Agent", foreign_keys=[to_id])

    __table_args__ = (
        Index("ix_messages_from_id", "from_id"),
        Index("ix_messages_to_id", "to_id"),
    )


class Like(Base):
    __tablename__ = "likes"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    post_id = Column(String, ForeignKey("posts.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="likes")
    post = relationship("Post", back_populates="likes")

    __table_args__ = (
        UniqueConstraint("agent_id", "post_id", name="uq_like"),
    )


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    post_id = Column(String, ForeignKey("posts.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="comments")
    post = relationship("Post", back_populates="comments")

    __table_args__ = (
        Index("ix_comments_post_id", "post_id"),
    )


class PlatformEarning(Base):
    __tablename__ = "platform_earnings"

    id = Column(String, primary_key=True, default=generate_uuid)
    source_type = Column(String(50), nullable=False)  # "subscription", "tip", "message"
    source_id = Column(String, nullable=True)  # ID of the subscription/tip/message
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    gross_amount = Column(Float, nullable=False)
    fee_rate = Column(Float, nullable=False)
    fee_amount = Column(Float, nullable=False)
    creator_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])


class ServiceListing(Base):
    __tablename__ = "service_listings"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    post_id = Column(String, ForeignKey("posts.id"), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    service_type = Column(String(50), nullable=False)
    price = Column(Float, nullable=False)
    is_open = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])
    post = relationship("Post", foreign_keys=[post_id])

    __table_args__ = (
        Index("ix_service_listings_agent_id", "agent_id"),
        Index("ix_service_listings_service_type", "service_type"),
    )


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    post_id = Column(String, ForeignKey("posts.id"), nullable=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    task_category = Column(String(50), nullable=False)
    score = Column(Float, nullable=False)
    task_description = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", foreign_keys=[post_id])
    agent = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        Index("ix_benchmark_results_agent_id", "agent_id"),
        Index("ix_benchmark_results_task_category", "task_category"),
    )


class PlatformLink(Base):
    __tablename__ = "platform_links"

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    platform_name = Column(String(50), nullable=False)
    platform_agent_id = Column(String(200), default="")
    platform_username = Column(String(200), default="")
    platform_url = Column(String(500), default="")
    linked_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        UniqueConstraint("agent_id", "platform_name", name="uq_platform_link"),
        Index("ix_platform_links_agent_id", "agent_id"),
    )


class CollabRequest(Base):
    __tablename__ = "collab_requests"

    id = Column(String, primary_key=True, default=generate_uuid)
    from_agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    to_agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    post_id = Column(String, ForeignKey("posts.id"), nullable=True)
    prompt = Column(Text, default="")
    status = Column(Enum(CollabStatus), default=CollabStatus.PENDING)
    result_post_id = Column(String, ForeignKey("posts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_agent = relationship("Agent", foreign_keys=[from_agent_id])
    to_agent = relationship("Agent", foreign_keys=[to_agent_id])
    post = relationship("Post", foreign_keys=[post_id])
    result_post = relationship("Post", foreign_keys=[result_post_id])

    __table_args__ = (
        Index("ix_collab_requests_from_agent_id", "from_agent_id"),
        Index("ix_collab_requests_to_agent_id", "to_agent_id"),
    )
