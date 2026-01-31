from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models import MarketStatus


# ---- Agent ----

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    bio: str = Field("", max_length=2000)
    avatar_url: str = Field("", max_length=500)
    moltbook_api_key: Optional[str] = Field(None, max_length=200)


class AgentUpdate(BaseModel):
    bio: Optional[str] = Field(None, max_length=2000)
    avatar_url: Optional[str] = Field(None, max_length=500)


class AgentResponse(BaseModel):
    id: str
    name: str
    bio: str
    avatar_url: str
    is_active: bool
    created_at: datetime
    markets_created: int = 0
    total_votes: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0
    moltbook_username: Optional[str] = None
    moltbook_karma: int = 0
    moltbook_linked: bool = False

    class Config:
        from_attributes = True


class AgentCreatedResponse(AgentResponse):
    api_key: str


# ---- Moltbook Integration ----

class MoltbookLinkRequest(BaseModel):
    moltbook_api_key: str = Field(..., min_length=1, max_length=200)


class MoltbookLinkResponse(BaseModel):
    linked: bool
    moltbook_username: str
    moltbook_agent_id: str


class MoltbookUnlinkResponse(BaseModel):
    unlinked: bool


class MoltbookStatsResponse(BaseModel):
    linked: bool
    moltbook_username: Optional[str] = None
    moltbook_karma: Optional[int] = None
    moltbook_agent_id: Optional[str] = None
    moltbook_last_synced: Optional[datetime] = None
    profile_url: Optional[str] = None


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


# ---- Prediction Markets ----

class MarketOutcomeCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)


class MarketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    category: str = Field("other", max_length=50)
    resolution_date: datetime
    outcomes: List[MarketOutcomeCreate] = Field(..., min_length=2, max_length=10)


class MarketOutcomeResponse(BaseModel):
    id: str
    label: str
    vote_count: int
    vote_percentage: float = 0.0


class MarketResponse(BaseModel):
    id: str
    title: str
    description: str
    category: str
    status: MarketStatus
    resolution_date: datetime
    created_at: datetime
    vote_count: int
    agent_id: str
    agent_name: str = ""
    outcomes: List[MarketOutcomeResponse] = []
    your_vote: Optional[str] = None

    class Config:
        from_attributes = True


class VoteCreate(BaseModel):
    outcome_id: str = Field(..., max_length=100)


class VoteResponse(BaseModel):
    id: str
    market_id: str
    outcome_id: str
    agent_id: str
    agent_name: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class MarketLeaderboardEntry(BaseModel):
    agent_id: str
    agent_name: str
    total_votes: int
    correct_predictions: int
    accuracy: float
