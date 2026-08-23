from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.runtime import get_runtime
from app.schemas import (
    AgentCreate,
    AgentEndpoints,
    AgentFleetItem,
    AgentOut,
    AgentPublishOut,
    AgentUpdate,
    AiFinding,
    AskReadinessOut,
    GraphInsights,
    PlatformIntelligence,
    PricingTier,
    StudioDashboard,
    TrustCenter,
)
from app.services.ask_readiness import evaluate_workspace_readiness
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _ask_readiness_for(store: WorkspaceStore, workspace_id: str) -> AskReadinessOut:
    health = await store.get_health(workspace_id)
    raw = ((health or {}).get("components") or {}).get("ask_readiness") or {}
    status = raw.get("status") or "unknown"
    if status not in {"unknown", "ready", "needs_attention"}:
        status = "unknown"
    return AskReadinessOut(
        status=status,  # type: ignore[arg-type]
        pass_rate=raw.get("pass_rate"),
        failing_patterns=list(raw.get("failing_patterns") or []),
        passage=dict(raw.get("passage") or {}),
    )


async def _enrich_agent(store: WorkspaceStore, row: dict) -> dict:
    ask = await _ask_readiness_for(store, row["workspace_id"])
    return {**row, "ask_readiness": ask.model_dump()}


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
    if agent.get("disabled"):
        return "disabled"
    counts = agent.get("counts") or {}
    docs = int(counts.get("documents") or 0)
    chunks = int(counts.get("chunks") or 0)
    if agent.get("published"):
        return "live"
    if docs > 0 or chunks > 0 or int(counts.get("nodes") or 0) > 0:
        return "ready"
    return "draft"


def _fleet_item(agent: dict) -> AgentFleetItem:
    key = agent.get("embed_key")
    published = bool(agent.get("published"))
    disabled = bool(agent.get("disabled"))
    readiness = _readiness(agent)  # type: ignore[assignment]
    ask_raw = agent.get("ask_readiness") or {}
    if hasattr(ask_raw, "model_dump"):
        ask_raw = ask_raw.model_dump()
    ask_status = ask_raw.get("status") or "unknown"
    if ask_status not in {"unknown", "ready", "needs_attention"}:
        ask_status = "unknown"
    endpoints = AgentEndpoints(
        embed_url=_embed_url(key) if key and published and not disabled else (
            _embed_url(key) if key else None
        ),
        widget_snippet=_embed_snippet(key) if key and published and not disabled else None,
        public_config_url=(
            f"{_api_base()}/public/agents/{key}" if key and published and not disabled else None
        ),
        public_chat_url=f"{_api_base()}/public/chat",
        studio_ask_hint=f"Studio Ask uses workspace_id={agent['workspace_id']}",
    )
    if readiness == "disabled":
        hint = "Disabled — chatbots refuse until a VERA admin reactivates."
    elif readiness == "live":
        hint = "Billable surface: embed + public chat API for this agent’s KB only."
    elif ask_status == "needs_attention":
        hint = "Knowledge loaded but Ask readiness needs attention — check failing patterns."
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
        disabled=disabled,
        readiness=readiness,  # type: ignore[arg-type]
        ask_status=ask_status,  # type: ignore[arg-type]
        ask_pass_rate=ask_raw.get("pass_rate"),
        ask_failing_patterns=list(ask_raw.get("failing_patterns") or []),
        embed_key=key,
        counts=agent.get("counts") or {},
        endpoints=endpoints,
        monetize_hint=hint,
    )


@router.get("/dashboard", response_model=StudioDashboard)
async def studio_dashboard() -> StudioDashboard:
    async with WorkspaceStore() as store:
        agents = [await _enrich_agent(store, a) for a in await store.list_agents()]
        totals = await store.studio_totals()
        intel_raw = await store.studio_intelligence()
    intelligence = PlatformIntelligence(
        trust=TrustCenter(**(intel_raw.get("trust") or {})),
        findings=[AiFinding(**f) for f in (intel_raw.get("findings") or [])],
        graph=GraphInsights(**(intel_raw.get("graph") or {})),
    )
    pricing = [
        PricingTier(
            id="builder",
            name="Builder",
            price_label="Custom",
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
            price_label="Custom",
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
        intelligence=intelligence,
    )


@router.get("", response_model=list[AgentOut])
async def list_agents() -> list[AgentOut]:
    async with WorkspaceStore() as store:
        rows = [await _enrich_agent(store, a) for a in await store.list_agents()]
        return [AgentOut.model_validate(r) for r in rows]


@router.post("", response_model=AgentOut)
async def create_agent(body: AgentCreate) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.create_agent(name=body.name, description=body.description)
        row = await _enrich_agent(store, row)
        return AgentOut.model_validate(row)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.get_agent(agent_id)
        if not row:
            raise HTTPException(404, "Agent not found")
        row = await _enrich_agent(store, row)
        return AgentOut.model_validate(row)


@router.post("/{agent_id}/ask-readiness", response_model=AskReadinessOut)
async def run_ask_readiness(agent_id: str) -> AskReadinessOut:
    """Re-run the Ask readiness suite and persist on knowledge health."""
    runtime = get_runtime()
    async with WorkspaceStore() as store:
        row = await store.get_agent(agent_id)
        if not row:
            raise HTTPException(404, "Agent not found")
        ws = row["workspace_id"]
        report = await evaluate_workspace_readiness(runtime, store, ws, run_live_asks=True)
        health = await store.get_health(ws) or {}
        components = dict(health.get("components") or {})
        components["ask_readiness"] = report
        await store.save_health(ws, float(health.get("score") or 0), components)
        return AskReadinessOut(
            status=report.get("status") or "unknown",  # type: ignore[arg-type]
            pass_rate=report.get("pass_rate"),
            failing_patterns=list(report.get("failing_patterns") or []),
            passage=dict(report.get("passage") or {}),
        )


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
            disabled=body.disabled,
            rotate_embed_key=body.rotate_embed_key,
        )
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)


@router.post("/{agent_id}/disable", response_model=AgentOut)
async def disable_agent(agent_id: str) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.update_agent(agent_id, disabled=True)
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)


@router.post("/{agent_id}/enable", response_model=AgentOut)
async def enable_agent(agent_id: str) -> AgentOut:
    async with WorkspaceStore() as store:
        row = await store.update_agent(agent_id, disabled=False)
        if not row:
            raise HTTPException(404, "Agent not found")
        return AgentOut.model_validate(row)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    """Delete agent + entire knowledge graph, chats, vectors, and uploads."""
    runtime = get_runtime()
    settings = get_settings()
    async with WorkspaceStore() as store:
        agent = await store.get_agent(agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        workspace_id = agent["workspace_id"]
        deleted = await store.delete_agent(agent_id)
    vectors_removed = await runtime.vector_store.delete_workspace(workspace_id)
    upload_dir = settings.data_dir / "uploads" / workspace_id
    uploads_removed = False
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
        uploads_removed = True
    return {
        "ok": True,
        "deleted": deleted,
        "vectors_removed": vectors_removed,
        "uploads_removed": uploads_removed,
    }


@router.post("/{agent_id}/publish", response_model=AgentPublishOut)
async def publish_agent(agent_id: str) -> AgentPublishOut:
    async with WorkspaceStore() as store:
        existing = await store.get_agent(agent_id)
        if not existing:
            raise HTTPException(404, "Agent not found")
        if existing.get("disabled"):
            raise HTTPException(400, "Enable the agent before publishing")
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
