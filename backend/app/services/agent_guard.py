"""Shared agent lifecycle guards (disable / delete messaging)."""

from __future__ import annotations

from app.schemas import ChatResponse, TrustScore

DISABLED_CHAT_MESSAGE = (
    "This chatbot is disabled. Contact a VERA admin to get it activated."
)


def agent_is_disabled(agent: dict | None) -> bool:
    return bool(agent and agent.get("disabled"))


def disabled_chat_response(session_id: str | None = None) -> ChatResponse:
    return ChatResponse(
        decision="refuse",
        answer=DISABLED_CHAT_MESSAGE,
        reason_codes=["agent_disabled"],
        trust_score=TrustScore(),
        retrieval_mode="disabled",
        session_id=session_id,
    )
