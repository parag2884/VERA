from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas import ChatResponse, PublicAgentConfig, PublicChatRequest
from app.services.ask_chat import run_ask_chat, settings_from_agent
from app.services.public_guard import origin_ok, rate_limit_ok
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/agents/{embed_key}", response_model=PublicAgentConfig)
async def public_agent_config(embed_key: str, request: Request) -> PublicAgentConfig:
    async with WorkspaceStore() as store:
        agent = await store.get_agent_by_embed_key(embed_key)
        if not agent:
            raise HTTPException(404, "Agent not found")
        if not agent.get("published"):
            raise HTTPException(403, "Agent is not published")
        origin = request.headers.get("origin")
        if not origin_ok(agent.get("allowed_origins") or "*", origin):
            raise HTTPException(403, "Origin not allowed for this agent")
        s = settings_from_agent(agent)
        return PublicAgentConfig(
            name=s.get("agentName") or agent["name"],
            greeting=s.get("greeting") or "",
            placeholder=s.get("placeholder") or "Ask a question…",
            accent=s.get("accent") or "coral",
            show_trust_trail=bool(s.get("showTrustTrail", True)),
            show_citations=bool(s.get("showCitations", True)),
            published=True,
        )


@router.post("/chat", response_model=ChatResponse)
async def public_chat(body: PublicChatRequest, request: Request) -> ChatResponse:
    async with WorkspaceStore() as store:
        agent = await store.get_agent_by_embed_key(body.embed_key)
        if not agent:
            raise HTTPException(404, "Agent not found")
        if not agent.get("published"):
            raise HTTPException(403, "Agent is not published")
        origin = request.headers.get("origin")
        if not origin_ok(agent.get("allowed_origins") or "*", origin):
            raise HTTPException(403, "Origin not allowed for this agent")
        client = request.client.host if request.client else "unknown"
        if not rate_limit_ok(f"{body.embed_key}:{client}"):
            raise HTTPException(429, "Rate limit exceeded for this embed key")

        s = settings_from_agent(agent)
        return await run_ask_chat(
            store,
            workspace_id=agent["workspace_id"],
            question=body.question,
            session_id=body.session_id,
            assistant_id=agent["id"],
            tone=str(s.get("tone") or "professional"),
            verbosity=str(s.get("verbosity") or "balanced"),
        )
