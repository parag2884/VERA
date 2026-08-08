from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ChatRequest, ChatResponse
from app.services.ask_chat import run_ask_chat
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(body.workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        return await run_ask_chat(
            store,
            workspace_id=body.workspace_id,
            question=body.question,
            session_id=body.session_id,
            assistant_id=body.assistant_id,
            tone=body.tone,
            verbosity=body.verbosity,
        )
