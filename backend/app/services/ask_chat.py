from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext
from app.runtime import get_runtime
from app.schemas import (
    ChatResponse,
    CitationOut,
    ClaimOut,
    ClarifyOption,
    TrustScore,
    TrustTrailHop,
)
from app.services.voice import apply_agent_voice
from app.stores.sql import WorkspaceStore


async def run_ask_chat(
    store: WorkspaceStore,
    *,
    workspace_id: str,
    question: str,
    session_id: str | None = None,
    assistant_id: str | None = None,
    tone: str = "professional",
    verbosity: str = "balanced",
) -> ChatResponse:
    """Shared Ask pipeline for studio chat and public embed widget."""
    runtime = get_runtime()
    session_id = session_id or await store.create_session(workspace_id, assistant_id)
    await store.insert_message(
        workspace_id,
        session_id=session_id,
        role="user",
        content=question,
    )

    ctx = AgentContext(
        workspace_id=workspace_id,
        assistant_id=assistant_id,
        demo_mode=runtime.demo_mode,
        stores=store,
        llm=runtime.llm,
        config={"vector_store": runtime.vector_store},
    )
    result = await runtime.orchestrator.run(
        "ask_pipeline",
        ctx,
        {"question": question},
    )
    bag = result.bag
    demo_mode = bool(result.demo_mode or ctx.demo_mode or runtime.demo_mode)
    provider_mode = "mock" if demo_mode else runtime.provider_mode  # type: ignore[assignment]

    decision = bag.get("decision") or "refuse"
    trust_raw = bag.get("trust_score") or {}
    if hasattr(trust_raw, "model_dump"):
        trust_raw = trust_raw.model_dump()
    trust = TrustScore.model_validate(trust_raw) if trust_raw else TrustScore()

    trail: list[TrustTrailHop] = []
    for hop in bag.get("trust_trail") or []:
        if hasattr(hop, "model_dump"):
            trail.append(TrustTrailHop.model_validate(hop.model_dump(by_alias=True)))
        else:
            trail.append(TrustTrailHop.model_validate(hop))

    claims: list[ClaimOut] = []
    for c in bag.get("claims") or []:
        claims.append(
            ClaimOut(
                claim_id=c.get("claim_id") or "claim",
                claim_text=c.get("claim_text") or "",
                support_status=c.get("support_status") or "supported",
                trust_score=float(c.get("trust_score") or 0),
            )
        )
    citations: list[CitationOut] = []
    for c in bag.get("citations") or []:
        citations.append(
            CitationOut(
                claim_id=c.get("claim_id"),
                document=c.get("document") or "document",
                locator=c.get("locator"),
                quote=c.get("quote") or "",
                chunk_id=c.get("chunk_id"),
                edge_id=c.get("edge_id"),
            )
        )
    clarify_options: list[ClarifyOption] = []
    for o in bag.get("clarify_options") or []:
        if hasattr(o, "model_dump"):
            clarify_options.append(ClarifyOption.model_validate(o.model_dump()))
        else:
            clarify_options.append(ClarifyOption.model_validate(o))

    answer_text = bag.get("answer")
    if decision == "clarify":
        answer_text = bag.get("clarification_prompt")
    elif decision == "answer" and answer_text:
        answer_text = await apply_agent_voice(
            runtime.llm,
            answer_text,
            tone=tone,  # type: ignore[arg-type]
            verbosity=verbosity,  # type: ignore[arg-type]
        )
        bag["answer"] = answer_text

    mid = await store.insert_message(
        workspace_id,
        session_id=session_id,
        role="assistant",
        content=answer_text or "",
        decision=decision,
        reason_codes=bag.get("reason_codes") or [],
        trust_score=trust.model_dump(),
        trust_trail=[t.model_dump(by_alias=True) for t in trail],
        retrieval_mode=bag.get("retrieval_mode"),
        provider_mode=provider_mode,
    )
    for claim in claims:
        cid = await store.insert_claim(
            workspace_id,
            message_id=mid,
            claim_text=claim.claim_text,
            support_status=claim.support_status,
            trust_score=claim.trust_score,
        )
        for cit in citations:
            if cit.claim_id and claim.claim_id and cit.claim_id != claim.claim_id:
                continue
            await store.insert_citation(
                workspace_id,
                claim_id=cid,
                chunk_id=cit.chunk_id,
                edge_id=cit.edge_id,
                quote=cit.quote,
                locator=cit.locator,
                document_title=cit.document,
            )
    await store.commit()

    return ChatResponse(
        decision=decision,
        answer=bag.get("answer"),
        clarification_prompt=bag.get("clarification_prompt"),
        clarify_options=clarify_options,
        reason_codes=bag.get("reason_codes") or [],
        trust_score=trust,
        trust_trail=trail,
        claims=claims,
        citations=citations,
        retrieval_mode=bag.get("retrieval_mode") or "graph_primary",
        provider_mode=provider_mode,  # type: ignore[arg-type]
        demo_mode=demo_mode,
        session_id=session_id,
        message_id=mid,
        events=[e.model_dump(mode="json") for e in result.events],
    )


def settings_from_agent(agent: dict[str, Any]) -> dict[str, Any]:
    raw = agent.get("settings") or {}
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}
