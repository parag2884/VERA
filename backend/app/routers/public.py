from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import ChatResponse, PublicAgentConfig, PublicChatRequest
from app.services.agent_guard import (
    DISABLED_CHAT_MESSAGE,
    agent_is_disabled,
    disabled_chat_response,
)
from app.services.ask_chat import run_ask_chat, settings_from_agent
from app.services.ask_stream import iter_ask_sse
from app.services.public_guard import origin_ok, rate_limit_ok
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/public", tags=["public"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _embed_streaming_enabled(settings: dict) -> bool:
    if "embedStreaming" in settings:
        return bool(settings.get("embedStreaming"))
    # Back-compat aliases
    if "streaming" in settings:
        return bool(settings.get("streaming"))
    return True


async def _load_published_agent(store: WorkspaceStore, embed_key: str, request: Request):
    agent = await store.get_agent_by_embed_key(embed_key)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if not agent.get("published"):
        raise HTTPException(403, "Agent is not published")
    origin = request.headers.get("origin")
    if not origin_ok(agent.get("allowed_origins") or "*", origin):
        raise HTTPException(403, "Origin not allowed for this agent")
    return agent


@router.get("/agents/{embed_key}", response_model=PublicAgentConfig)
async def public_agent_config(embed_key: str, request: Request) -> PublicAgentConfig:
    async with WorkspaceStore() as store:
        agent = await _load_published_agent(store, embed_key, request)
        s = settings_from_agent(agent)
        disabled = agent_is_disabled(agent)
        return PublicAgentConfig(
            name=s.get("agentName") or agent["name"],
            greeting=DISABLED_CHAT_MESSAGE if disabled else (s.get("greeting") or ""),
            placeholder="Chatbot disabled" if disabled else (s.get("placeholder") or "Ask a question…"),
            accent=s.get("accent") or "coral",
            show_trust_trail=bool(s.get("showTrustTrail", True)) and not disabled,
            show_citations=bool(s.get("showCitations", True)) and not disabled,
            streaming=_embed_streaming_enabled(s) and not disabled,
            published=True,
            disabled=disabled,
            disabled_message=DISABLED_CHAT_MESSAGE if disabled else None,
        )


@router.post("/chat", response_model=ChatResponse)
async def public_chat(body: PublicChatRequest, request: Request) -> ChatResponse:
    async with WorkspaceStore() as store:
        agent = await _load_published_agent(store, body.embed_key, request)
        if agent_is_disabled(agent):
            return disabled_chat_response(session_id=body.session_id)
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


@router.post("/chat/stream")
async def public_chat_stream(body: PublicChatRequest, request: Request) -> StreamingResponse:
    """SSE stream for published embeds (same event shape as Studio /api/chat/stream)."""
    async with WorkspaceStore() as store:
        agent = await _load_published_agent(store, body.embed_key, request)
        if agent_is_disabled(agent):
            refuse = disabled_chat_response(session_id=body.session_id)

            async def disabled_gen():
                yield f"data: {json.dumps({'type': 'token', 'text': refuse.answer})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': refuse.model_dump(mode='json')})}\n\n"

            return StreamingResponse(
                disabled_gen(),
                media_type="text/event-stream",
                headers=_SSE_HEADERS,
            )

        client = request.client.host if request.client else "unknown"
        if not rate_limit_ok(f"{body.embed_key}:{client}"):
            raise HTTPException(429, "Rate limit exceeded for this embed key")

        s = settings_from_agent(agent)
        if not _embed_streaming_enabled(s):
            raise HTTPException(
                409,
                "Streaming is disabled for this agent. Use POST /api/public/chat instead.",
            )

        workspace_id = agent["workspace_id"]
        assistant_id = agent["id"]
        tone = str(s.get("tone") or "professional")
        verbosity = str(s.get("verbosity") or "balanced")

    return StreamingResponse(
        iter_ask_sse(
            workspace_id=workspace_id,
            question=body.question,
            session_id=body.session_id,
            assistant_id=assistant_id,
            tone=tone,
            verbosity=verbosity,
            stream_answer=True,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
