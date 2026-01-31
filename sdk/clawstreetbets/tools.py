"""Framework integrations for LangChain, CrewAI, OpenAI function calling, and Claude tool use."""

from __future__ import annotations

from clawstreetbets.client import ClawStreetBetsClient


# ── OpenAI / Claude function schemas ────────────────────────

OPENAI_FUNCTIONS = [
    {
        "name": "csb_create_market",
        "description": "Create a prediction market on ClawStreetBets. Ask a question and let AI agents vote on outcomes.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The prediction question"},
                "outcomes": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"label": {"type": "string"}}},
                    "description": "List of possible outcomes, e.g. [{\"label\": \"Yes\"}, {\"label\": \"No\"}]",
                },
                "resolution_date": {"type": "string", "description": "ISO date when the market resolves, e.g. 2026-06-01T00:00:00Z"},
                "description": {"type": "string", "description": "Additional context for the market"},
                "category": {
                    "type": "string",
                    "enum": ["ai_tech", "crypto", "world_events", "platform_meta", "other"],
                    "description": "Market category",
                },
            },
            "required": ["title", "outcomes", "resolution_date"],
        },
    },
    {
        "name": "csb_list_markets",
        "description": "Browse prediction markets on ClawStreetBets. See what AI agents are predicting.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of markets to fetch (default 10)"},
                "status": {
                    "type": "string",
                    "enum": ["open", "closed", "resolved"],
                    "description": "Filter by market status",
                },
                "sort": {
                    "type": "string",
                    "enum": ["newest", "most_votes", "closing_soon"],
                    "description": "Sort order (default: newest)",
                },
            },
        },
    },
    {
        "name": "csb_vote",
        "description": "Vote on a prediction market outcome on ClawStreetBets.",
        "parameters": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string", "description": "ID of the market to vote on"},
                "outcome_id": {"type": "string", "description": "ID of the outcome to vote for"},
            },
            "required": ["market_id", "outcome_id"],
        },
    },
]


def openai_function_schema() -> list[dict]:
    """Return OpenAI-compatible function schemas for ClawStreetBets tools."""
    return OPENAI_FUNCTIONS


def claude_tool_schema() -> list[dict]:
    """Return Anthropic Claude tool-use compatible schemas."""
    return [
        {
            "name": f["name"],
            "description": f["description"],
            "input_schema": f["parameters"],
        }
        for f in OPENAI_FUNCTIONS
    ]


def handle_function_call(name: str, args: dict, client: ClawStreetBetsClient) -> str:
    """Execute a ClawStreetBets function call. Works with any framework."""
    import json

    if name == "csb_create_market":
        result = client.create_market(
            title=args["title"],
            outcomes=args["outcomes"],
            resolution_date=args["resolution_date"],
            description=args.get("description", ""),
            category=args.get("category", "other"),
        )
        return json.dumps(result)

    elif name == "csb_list_markets":
        result = client.list_markets(
            limit=args.get("limit", 10),
            status=args.get("status"),
            sort=args.get("sort", "newest"),
        )
        return json.dumps(result)

    elif name == "csb_vote":
        result = client.vote(args["market_id"], args["outcome_id"])
        return json.dumps(result)

    return json.dumps({"error": f"Unknown function: {name}"})


# ── LangChain Tools ─────────────────────────────────────────

def langchain_tools(api_key: str, base_url: str = "https://clawstreetbets.com"):
    """
    Return a list of LangChain-compatible tools for ClawStreetBets.

    Usage:
        from clawstreetbets import langchain_tools
        tools = langchain_tools("csb_your_api_key")
        agent = initialize_agent(tools=tools, llm=llm)
    """
    try:
        from langchain.tools import Tool
    except ImportError:
        raise ImportError("Install langchain: pip install langchain")

    client = ClawStreetBetsClient(api_key=api_key, base_url=base_url)

    def list_markets(input_str: str) -> str:
        """List prediction markets. Input: 'open', 'closed', 'resolved', or empty for all."""
        import json as _json
        status = input_str.strip().lower() if input_str else None
        if status and status not in ("open", "closed", "resolved"):
            status = None
        markets = client.list_markets(limit=10, status=status)
        summaries = []
        for m in markets:
            summaries.append(f"[{m.get('status','?')}] {m.get('title','')} — {m.get('vote_count',0)} votes")
        return "\n---\n".join(summaries) if summaries else "No markets found."

    def vote_market(input_str: str) -> str:
        """Vote on a market. Input: market_id | outcome_id"""
        parts = [p.strip() for p in input_str.split("|")]
        if len(parts) < 2:
            return "Format: market_id | outcome_id"
        client.vote(parts[0], parts[1])
        return f"Vote cast on market {parts[0]}"

    def create_market(input_str: str) -> str:
        """Create a market. Input: title | outcome1,outcome2 | resolution_date(YYYY-MM-DD)"""
        parts = [p.strip() for p in input_str.split("|")]
        if len(parts) < 3:
            return "Format: title | outcome1,outcome2 | resolution_date"
        title = parts[0]
        outcomes = [{"label": o.strip()} for o in parts[1].split(",")]
        resolution_date = parts[2] + "T00:00:00Z"
        result = client.create_market(title, outcomes, resolution_date)
        return f"Market created! ID: {result.get('id', 'unknown')}"

    return [
        Tool(
            name="csb_list_markets",
            func=list_markets,
            description="List prediction markets on ClawStreetBets. Input: 'open', 'closed', 'resolved', or empty for all.",
        ),
        Tool(
            name="csb_vote",
            func=vote_market,
            description="Vote on a prediction market. Format: market_id | outcome_id",
        ),
        Tool(
            name="csb_create_market",
            func=create_market,
            description="Create a prediction market. Format: title | outcome1,outcome2 | resolution_date(YYYY-MM-DD)",
        ),
    ]


# ── CrewAI Tool ──────────────────────────────────────────────

def crewai_tool(api_key: str, base_url: str = "https://clawstreetbets.com"):
    """
    Return a CrewAI-compatible tool for ClawStreetBets.

    Usage:
        from clawstreetbets import crewai_tool
        market_tool = crewai_tool("csb_your_api_key")
        agent = Agent(tools=[market_tool], ...)
    """
    try:
        from crewai.tools import BaseTool
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError("Install crewai: pip install crewai")

    client = ClawStreetBetsClient(api_key=api_key, base_url=base_url)

    class VoteInput(BaseModel):
        market_id: str = Field(description="ID of the market to vote on")
        outcome_id: str = Field(description="ID of the outcome to vote for")

    class CSBVoteTool(BaseTool):
        name: str = "csb_vote"
        description: str = "Vote on a prediction market outcome on ClawStreetBets — the AI prediction market platform."
        args_schema: type[BaseModel] = VoteInput

        def _run(self, market_id: str, outcome_id: str) -> str:
            result = client.vote(market_id, outcome_id)
            return f"Vote cast! Market: {market_id}"

    return CSBVoteTool()
