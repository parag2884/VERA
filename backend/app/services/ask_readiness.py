"""Post-ingest Ask readiness: short auto-suite + optional goldens.

“Ready” means the suite passes — not that crawl progress hit 100%.
This is the “AI that works” gate after connect: grounded refuse/answer checks
plus passage quality signals from knowledge.signals.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.base import AgentContext
from app.agents.ask.evidence_contract import detect_evidence_contract
from app.services.passage_signals import summarize_passage_readiness

logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def default_auto_cases(workspace_id: str) -> list[dict[str, Any]]:
    """Minimal suite that any corpus should pass."""
    return [
        {
            "id": "ood_weather",
            "question": "What is the weather in Seattle today?",
            "expect_decision": "refuse",
            "forbid_any": ["sunny", "fahrenheit", "celsius", "rainy"],
        },
        {
            "id": "ood_trivia",
            "question": "What is the capital of France?",
            "expect_decision": "refuse",
            "forbid_any": ["paris is the capital"],
        },
    ]


async def run_ask_case(
    runtime,
    store,
    workspace_id: str,
    question: str,
) -> dict[str, Any]:
    ctx = AgentContext(
        workspace_id=workspace_id,
        demo_mode=runtime.demo_mode,
        stores=store,
        llm=runtime.llm,
        config={"vector_store": runtime.vector_store},
    )
    result = await runtime.orchestrator.run("ask_pipeline", ctx, {"question": question})
    bag = result.bag or {}
    return {
        "decision": bag.get("decision"),
        "answer": bag.get("answer") or bag.get("clarification_prompt") or "",
        "reason_codes": bag.get("reason_codes") or [],
        "retrieval_mode": bag.get("retrieval_mode"),
    }


def verify_case(case: dict[str, Any], bag: dict[str, Any]) -> dict[str, Any]:
    decision = (bag.get("decision") or "").lower()
    answer = _norm(bag.get("answer") or "")
    expect = case.get("expect_decision") or "answer"
    ok = True
    notes: list[str] = []

    if expect == "either":
        dec_ok = decision in {"answer", "refuse", "clarify"}
    else:
        dec_ok = decision == expect
    if not dec_ok:
        ok = False
        notes.append(f"decision={decision} expected={expect}")

    for phrase in case.get("must_any") or []:
        if phrase.lower() in answer:
            break
    else:
        if case.get("must_any") and expect == "answer" and decision == "answer":
            ok = False
            notes.append("missing must_any")

    for phrase in case.get("forbid_any") or []:
        if phrase.lower() in answer:
            ok = False
            notes.append(f"forbid:{phrase}")
            break

    return {
        "id": case.get("id"),
        "ok": ok,
        "decision": decision,
        "notes": notes,
        "question": case.get("question"),
    }


async def evaluate_workspace_readiness(
    runtime,
    store,
    workspace_id: str,
    *,
    extra_cases: list[dict[str, Any]] | None = None,
    run_live_asks: bool = True,
) -> dict[str, Any]:
    """Run auto-suite (+ optional goldens) and passage summary."""
    docs = await store.list_canonical_documents(workspace_id)
    chunks = await store.list_chunks(workspace_id)
    passage = summarize_passage_readiness(chunks, docs)

    cases = default_auto_cases(workspace_id)
    if extra_cases:
        cases.extend(extra_cases)

    results: list[dict[str, Any]] = []
    if run_live_asks and docs:
        for case in cases:
            try:
                bag = await run_ask_case(runtime, store, workspace_id, case["question"])
                results.append(verify_case(case, bag))
            except Exception as exc:  # noqa: BLE001
                logger.warning("readiness case %s failed: %s", case.get("id"), exc)
                results.append(
                    {
                        "id": case.get("id"),
                        "ok": False,
                        "decision": "error",
                        "notes": [str(exc)[:160]],
                        "question": case.get("question"),
                    }
                )
    elif not docs:
        results.append(
            {
                "id": "no_docs",
                "ok": False,
                "decision": "skip",
                "notes": ["no documents"],
                "question": "",
            }
        )

    passed = sum(1 for r in results if r.get("ok"))
    total = len(results) or 1
    pass_rate = round(passed / total, 3)
    failing = [r["id"] for r in results if not r.get("ok")]

    # Passage gates: chrome-heavy corpora need attention even if OOD refuse works
    passage_ok = passage.get("chrome_heavy_pct", 100) < 70 or passage.get("chunks_scored", 0) < 5
    status = "ready" if pass_rate >= 0.99 and passage_ok and bool(docs) else "needs_attention"
    if not docs:
        status = "unknown"

    failing_patterns: list[str] = []
    for r in results:
        if r.get("ok"):
            continue
        q = r.get("question") or ""
        shape = detect_evidence_contract(q).shape if q else "open"
        failing_patterns.append(f"{r.get('id')}:{shape}")

    if not passage.get("has_officer_evidence") and passage.get("chunks_scored", 0) > 20:
        failing_patterns.append("corpus:few_named_officers")

    # Crawl skew: many client/case pages but no about/leaders → officer Ask will fail
    titles = [(d.get("title") or "") for d in (docs or [])]
    n_docs = len(titles)
    if n_docs >= 40:
        blob = " ".join(titles).lower()
        has_corporate = any(
            tok in blob
            for tok in (
                "about-us",
                "about_us",
                "/about",
                "leaders",
                "leadership",
                "who-we-are",
                "our-team",
            )
        )
        clientish = sum(
            1
            for t in titles
            if any(x in t.lower() for x in ("clients", "client_", "case-stud", "case_stud"))
        )
        if clientish / n_docs >= 0.35 and not has_corporate:
            failing_patterns.append("corpus:missing_about_or_leaders")
            if status == "ready":
                status = "needs_attention"

    return {
        "status": status,
        "pass_rate": pass_rate,
        "passed": passed,
        "total": total,
        "failing": failing,
        "failing_patterns": failing_patterns[:12],
        "cases": results,
        "passage": passage,
    }
