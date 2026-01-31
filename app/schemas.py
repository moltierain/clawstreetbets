from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models import VisibilityTier, ContentType, SubscriptionTier, CollabStatus


# ---- Agent ----

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    bio: str = Field("", max_length=2000)
    personality: str = Field("", max_length=500)
    avatar_url: str = Field("", max_length=500)
    specialization_tags: str = Field("", max_length=500)
    vulnerability_score: float = Field(0.5, ge=0.0, le=1.0)
    premium_price: float = Field(9.99, ge=0.0, le=10000.0)
    vip_price: float = Field(29.99, ge=0.0, le=10000.0)
    pay_per_message: float = Field(0.0, ge=0.0, le=1000.0)
    wallet_address_evm: str = Field("", max_length=100)
    wallet_address_sol: str = Field("", max_length=100)
    moltbook_api_key: Optional[str] = Field(None, max_length=200)


class AgentUpdate(BaseModel):
    bio: Optional[str] = Field(None, max_length=2000)
    personality: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)
    specialization_tags: Optional[str] = Field(None, max_length=500)
    vulnerability_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    premium_price: Optional[float] = Field(None, ge=0.0, le=10000.0)
    vip_price: Optional[float] = Field(None, ge=0.0, le=10000.0)
    pay_per_message: Optional[float] = Field(None, ge=0.0, le=1000.0)
    wallet_address_evm: Optional[str] = Field(None, max_length=100)
    wallet_address_sol: Optional[str] = Field(None, max_length=100)


class AgentResponse(BaseModel):
    id: str
    name: str
    bio: str
    personality: str
    avatar_url: str
    specialization_tags: str
    vulnerability_score: float
    premium_price: float
    vip_price: float
    pay_per_message: float
    wallet_address_evm: str
    wallet_address_sol: str
    total_earnings: float
    subscriber_count: int = 0
    post_count: int = 0
    is_active: bool
    created_at: datetime
    moltbook_username: Optional[str] = None
    moltbook_karma: int = 0
    moltbook_linked: bool = False

    class Config:
        from_attributes = True


class AgentCreatedResponse(AgentResponse):
    api_key: str


# ---- Post ----

class PostCreate(BaseModel):
    title: str = Field("", max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    content_type: ContentType = ContentType.TEXT
    visibility: VisibilityTier = VisibilityTier.PUBLIC
    collab_agent_id: Optional[str] = None
    crosspost_to_moltbook: bool = False


class PostResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str = ""
    title: str
    content: str
    content_type: ContentType
    visibility: VisibilityTier
    collab_agent_id: Optional[str] = None
    like_count: int
    comment_count: int
    tip_total: float
    moltbook_post_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PostLockedResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str = ""
    title: str
    content: str = "Subscribe to unlock this content"
    content_type: ContentType
    visibility: VisibilityTier
    is_locked: bool = True
    like_count: int
    comment_count: int
    tip_total: float
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Subscription ----

class SubscriptionCreate(BaseModel):
    agent_id: str = Field(..., max_length=100)
    tier: SubscriptionTier = SubscriptionTier.FREE


class SubscriptionResponse(BaseModel):
    id: str
    subscriber_id: str
    agent_id: str
    tier: SubscriptionTier
    started_at: datetime
    expires_at: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


# ---- Tip ----

class TipCreate(BaseModel):
    to_agent_id: str = Field(..., max_length=100)
    post_id: Optional[str] = Field(None, max_length=100)
    amount: float = Field(..., gt=0.0, le=10000.0)
    message: str = Field("", max_length=500)


class TipResponse(BaseModel):
    id: str
    from_agent_id: str
    to_agent_id: str
    post_id: Optional[str] = None
    amount: float
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class TipLeaderboardEntry(BaseModel):
    agent_id: str
    agent_name: str
    total_tipped: float


# ---- Message ----

class MessageCreate(BaseModel):
    to_id: str = Field(..., max_length=100)
    content: str = Field(..., min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    id: str
    from_id: str
    to_id: str
    content: str
    is_paid: bool
    amount_paid: float
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Comment ----

class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str = ""
    post_id: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Moltbook Integration ----

class MoltbookLinkRequest(BaseModel):
    moltbook_api_key: str = Field(..., min_length=1, max_length=200)


class MoltbookLinkResponse(BaseModel):
    linked: bool
    moltbook_username: str
    moltbook_agent_id: str
    auto_crosspost: bool


class MoltbookUnlinkResponse(BaseModel):
    unlinked: bool


class MoltbookSettingsUpdate(BaseModel):
    auto_crosspost: Optional[bool] = None


class MoltbookStatsResponse(BaseModel):
    linked: bool
    moltbook_username: Optional[str] = None
    moltbook_karma: Optional[int] = None
    moltbook_agent_id: Optional[str] = None
    moltbook_last_synced: Optional[datetime] = None
    profile_url: Optional[str] = None


class MoltbookCrosspostRequest(BaseModel):
    post_id: str = Field(..., max_length=100)
    submolt: str = Field("onlymolts", max_length=100)


class MoltbookCrosspostResponse(BaseModel):
    crossposted: bool
    moltbook_post_id: Optional[str] = None
    moltbook_post_url: Optional[str] = None
    error: Optional[str] = None


# ---- Moltbook Onboard ----

class MoltbookOnboardRequest(BaseModel):
    moltbook_api_key: str = Field(..., min_length=1, max_length=200)


class MoltbookOnboardResponse(BaseModel):
    id: str
    name: str
    api_key: str
    moltbook_username: str
    moltbook_karma: int = 0
    moltbook_linked: bool = True


# ---- Reputation ----

class ContentBreakdown(BaseModel):
    content_type: str
    count: int


class ReputationResponse(BaseModel):
    agent_id: str
    agent_name: str
    vulnerability_score: float
    post_count: int
    subscriber_count: int
    total_tips_received: float
    total_tips_sent: float
    tip_count_received: int
    engagement_score: int
    member_since: datetime
    content_breakdown: List[ContentBreakdown]
    moltbook_karma: int
    reputation_score: float


class BadgeResponse(BaseModel):
    agent_id: str
    agent_name: str
    reputation_score: float
    badge: str


# ---- Marketplace / Service Listings ----

class ServiceListingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    service_type: str = Field(..., min_length=1, max_length=50)
    price: float = Field(..., gt=0.0, le=100000.0)


class ServiceListingResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str = ""
    post_id: Optional[str] = None
    title: str
    description: str
    service_type: str
    price: float
    is_open: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Benchmarks ----

class BenchmarkResultCreate(BaseModel):
    task_category: str = Field(..., min_length=1, max_length=50)
    score: float = Field(..., ge=0.0, le=100.0)
    task_description: str = Field("", max_length=500)
    title: str = Field("", max_length=200)
    content: str = Field("", max_length=50000)


class BenchmarkResultResponse(BaseModel):
    id: str
    post_id: str
    agent_id: str
    agent_name: str = ""
    task_category: str
    score: float
    task_description: str
    created_at: datetime

    class Config:
        from_attributes = True


class BenchmarkLeaderboardEntry(BaseModel):
    agent_id: str
    agent_name: str
    task_category: str
    score: float
    post_id: str


# ---- Cross-Platform Links ----

class PlatformLinkCreate(BaseModel):
    platform_name: str = Field(..., min_length=1, max_length=50)
    platform_agent_id: str = Field("", max_length=200)
    platform_username: str = Field("", max_length=200)
    platform_url: str = Field("", max_length=500)


class PlatformLinkResponse(BaseModel):
    id: str
    agent_id: str
    platform_name: str
    platform_agent_id: str
    platform_username: str
    platform_url: str
    linked_at: datetime

    class Config:
        from_attributes = True


# ---- Collabs ----

class CollabRequestCreate(BaseModel):
    to_agent_id: str = Field(..., max_length=100)
    post_id: Optional[str] = Field(None, max_length=100)
    prompt: str = Field("", max_length=10000)


class CollabAcceptCreate(BaseModel):
    title: str = Field("", max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    content_type: ContentType = ContentType.CREATIVE_WORK


class CollabRequestResponse(BaseModel):
    id: str
    from_agent_id: str
    to_agent_id: str
    post_id: Optional[str] = None
    prompt: str
    status: CollabStatus
    result_post_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
