from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas import (
    AgentCreate,
    AgentEndpoints,
    AgentFleetItem,
    AgentOut,
    AgentPublishOut,
    AgentUpdate,
    PricingTier,
    StudioDashboard,
)
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _widget_origin() -> str:
    return get_settings().vera_widget_public_origin.rstrip("/")


def _api_base() -> str:
    # Public API is served alongside Studio proxy; document host-relative path.
    return "/api"


def _embed_url(embed_key: str) -> str:
    return f"{_widget_origin()}/embed/{embed_key}"


def _embed_snippet(embed_key: str) -> str:
    origin = _widget_origin()
    return (
        f'<script src="{origin}/widget.js" '
        f'data-vera-key="{embed_key}" '
        f'data-vera-origin="{origin}" async></script>'
    )


def _readiness(agent: dict) -> str:
    counts = agent.get("counts") or {}
    docs = int(counts.get("documents") or 0)
    chunks = int(counts.get("chunks") or 0)
    if agent.get("published"):
        return "live"
    if docs > 0 or chunks > 0:
        return "ready"
    return "draft"


def _fleet_item(agent: dict) -> AgentFleetItem:
    key = agent.get("embed_key")
    published = bool(agent.get("published"))
    readiness = _readiness(agent)  # type: ignore[assignment]
    endpoints = AgentEndpoints(
        embed_url=_embed_url(key) if key and published else (_embed_url(key) if key else None),
        widget_snippet=_embed_snippet(key) if key and published else None,
        public_config_url=(
            f"{_api_base()}/public/agents/{key}" if key and published else None
        ),
        public_chat_url=f"{_api_base()}/public/chat",
        studio_ask_hint=f"Studio Ask uses workspace_id={agent['workspace_id']}",
    )
    if readiness == "live":
        hint = "Billable surface: embed + public chat API for this agent’s KB only."
    elif readiness == "ready":
        hint = "Knowledge loaded — publish to unlock embed & paid site hooks."
    else:
        hint = "Connect documents, then publish to sell access on any website."
    return AgentFleetItem(
        id=agent["id"],
        name=agent["name"],
        slug=agent.get("slug") or "",
        description=agent.get("description") or "",
        workspace_id=agent["workspace_id"],
        published=published,
        readiness=readiness,  # type: ignore[arg-type]
        embed_key=key,
        counts=agent.get("counts") or {},
        endpoints=endpoints,
        monetize_hint=hint,
    )


@router.get("/dashboard", response_model=StudioDashboard)
async def studio_dashboard() -> StudioDashboard:
    async with WorkspaceStore() as store:
        agents = await store.list_agents()
        totals = await store.studio_totals()
    pricing = [
        PricingTier(
            id="builder",
            name="Builder",
            price_label="$0",
            blurb="Studio + isolated agents for internal proof.",
            features=[
                "Unlimited draft agents",
                "Graph + CleanStack ingest",
                "Studio Ask with Trust Trail",
            ],
        ),
        PricingTier(
            id="growth",
            name="Growth",
            price_label="$149/mo",
            blurb="Ship branded agents on customer sites.",
            features=[
                "Publish & embed widget",
                "Public chat API per agent",
                "Usage metering (asks)",
                "Origin allowlists",
            ],
            highlighted=True,
        ),
        PricingTier(
            id="scale",
            name="Scale",
            price_label="Custom",
            blurb="White-label trust agents for enterprises.",
            features=[
                "Multi-site deploy keys",
                "SLA + audit exports",
                "Per-agent billing packs",
                "Private VPC / Azure",
            ],
        ),
    ]
    return StudioDashboard(
        plan="builder",
        plan_label="Builder",
        api_base=_api_base(),
        widget_origin=_widget_origin(),
        totals=totals,
        agents=[_fleet_item(a) for a in agents],
        pricing=pricing,
        revenue_model=[
            "Charge per published agent (SaaS seat / agent pack)",
            "Meter public Ask volume on embed + /api/public/chat",
            "Sell domain packs (PlayReady, Legal, HR) as pre-built agents",
            "Upsell Scale for white-label on partner sites (e.g. KFORCE)",
        ],
    )


@router.get("", response_model=list[AgentOut])
async def list_agents() -> list[AgentOut]:
    async with WorkspaceStore() as store:
        rows = await store.list_agents()
        return [AgentOut.model_validate(r) for r in rows]


@router.post("", response_model=AgentOut)
async def create_agent(body: AgentCreate) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.create_agent(name=body.name, description=body.description)
        return AgentOut.model_validate(row)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.get_agent(agent_id)
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentUpdate) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.update_agent(
            agent_id,
            name=body.name,
            description=body.description,
            settings=body.settings,
            allowed_origins=body.allowed_origins,
            published=body.published,
            rotate_embed_key=body.rotate_embed_key,
        )
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)


@router.post("/{agent_id}/publish", response_model=AgentPublishOut)
async def publish_agent(agent_id: str) -> AgentPublishOut:
    async with WorkspaceStore() as store:
        row = await store.update_agent(agent_id, published=True)
        if not row:
            raise HTTPException(404, "Agent not found")
        key = row["embed_key"]
        if not key:
            row = await store.update_agent(agent_id, rotate_embed_key=True, published=True)
            key = row["embed_key"]  # type: ignore[index]
        return AgentPublishOut(
            id=row["id"],
            name=row["name"],
            published=True,
            embed_key=key,
            embed_snippet=_embed_snippet(key),
            embed_url=_embed_url(key),
            allowed_origins=row["allowed_origins"],
        )


@router.post("/{agent_id}/unpublish", response_model=AgentOut)
async def unpublish_agent(agent_id: str) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.update_agent(agent_id, published=False)
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)
