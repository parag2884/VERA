from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import ChatFeedbackRequest, ChatRequest, ChatResponse
from app.services.agent_guard import agent_is_disabled, disabled_chat_response
from app.services.ask_chat import run_ask_chat
from app.services.ask_stream import iter_ask_sse
from app.stores.sql import WorkspaceStore
from app.knowledge_os.service import record_feedback

router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _resolve_assistant(store: WorkspaceStore, body: ChatRequest):
    ws = await store.get_workspace(body.workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    agent = None
    if body.assistant_id:
        agent = await store.get_agent(body.assistant_id)
    if agent is None:
        agent = await store.get_agent_by_workspace(body.workspace_id)
    return agent


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    async with WorkspaceStore() as store:
        agent = await _resolve_assistant(store, body)
        if agent_is_disabled(agent):
            return disabled_chat_response(session_id=body.session_id)
        return await run_ask_chat(
            store,
            workspace_id=body.workspace_id,
            question=body.question,
            session_id=body.session_id,
            assistant_id=body.assistant_id or (agent["id"] if agent else None),
            tone=body.tone,
            verbosity=body.verbosity,
        )


@router.post("/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """SSE stream: status + answer tokens + final ChatResponse (trust trail at end)."""
    async with WorkspaceStore() as store:
        agent = await _resolve_assistant(store, body)
        if agent_is_disabled(agent):
            refuse = disabled_chat_response(session_id=body.session_id)

            async def disabled_gen():
                import json

                yield f"data: {json.dumps({'type': 'token', 'text': refuse.answer})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': refuse.model_dump(mode='json')})}\n\n"

            return StreamingResponse(
                disabled_gen(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        assistant_id = body.assistant_id or (agent["id"] if agent else None)

    return StreamingResponse(
        iter_ask_sse(
            workspace_id=body.workspace_id,
            question=body.question,
            session_id=body.session_id,
            assistant_id=assistant_id,
            tone=body.tone,
            verbosity=body.verbosity,
            stream_answer=True,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback")
async def chat_feedback(body: ChatFeedbackRequest) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(body.workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
    return await record_feedback(
        body.workspace_id,
        message_id=body.message_id,
        rating=body.rating,
        note=body.note,
    )
