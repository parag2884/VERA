"""SSE streaming wrapper for Studio Ask (answer text + final trust payload)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.schemas import ChatResponse
from app.services.ask_chat import run_ask_chat
from app.stores.sql import WorkspaceStore


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _display_text(resp: ChatResponse) -> str:
    if resp.decision == "clarify":
        return resp.clarification_prompt or resp.answer or ""
    return resp.answer or ""


async def _chunk_text(text: str) -> AsyncIterator[str]:
    """Yield small readable chunks so the UI feels live."""
    if not text:
        return
    parts = re.findall(r"\S+\s*|\n+", text)
    buf = ""
    for part in parts:
        buf += part
        if len(buf) >= 16 or part == "\n":
            yield buf
            buf = ""
            await asyncio.sleep(0.012)
    if buf:
        yield buf


async def iter_ask_sse(
    *,
    workspace_id: str,
    question: str,
    session_id: str | None = None,
    assistant_id: str | None = None,
    tone: str = "professional",
    verbosity: str = "balanced",
    stream_answer: bool = True,
) -> AsyncIterator[str]:
    """
    Yield SSE events:
      status → optional token* → done | error
    Trust trail / citations arrive in the final `done.response` payload.
    """
    yield _sse({"type": "status", "message": "Working on your question…"})

    status_steps = [
        "Understanding your question…",
        "Searching the knowledge graph…",
        "Gathering evidence…",
        "Writing a grounded answer…",
    ]

    resp: ChatResponse | None = None
    err: str | None = None

    async with WorkspaceStore() as store:
        task = asyncio.create_task(
            run_ask_chat(
                store,
                workspace_id=workspace_id,
                question=question,
                session_id=session_id,
                assistant_id=assistant_id,
                tone=tone,
                verbosity=verbosity,
            )
        )
        step = 0
        while not task.done():
            yield _sse({"type": "status", "message": status_steps[step % len(status_steps)]})
            step += 1
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.1)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                err = str(exc) or "Ask failed"
                break

        if err is None:
            try:
                resp = task.result()
            except Exception as exc:  # noqa: BLE001
                err = str(exc) or "Ask failed"

    if err or resp is None:
        yield _sse({"type": "error", "message": err or "Ask failed"})
        return

    text = _display_text(resp)
    should_stream = (
        stream_answer
        and bool(text)
        and resp.decision in {"answer", "clarify"}
        and len(text) > 40
        and (resp.retrieval_mode or "") not in {"greeting", "policy_refuse", "disabled"}
    )

    if should_stream:
        yield _sse({"type": "status", "message": "Streaming answer…"})
        async for piece in _chunk_text(text):
            yield _sse({"type": "token", "text": piece})
    elif text and stream_answer:
        yield _sse({"type": "token", "text": text})

    yield _sse({"type": "done", "response": resp.model_dump(mode="json")})
