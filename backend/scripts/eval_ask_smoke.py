"""Ask-quality smoke eval — golden questions against a workspace.

Usage (inside API container or with PYTHONPATH=/app):
  python scripts/eval_ask_smoke.py [workspace_id]

Exits non-zero if any case fails hard (refuse on must-answer, or clarify on compare).
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from app.services.ask_chat import run_ask_chat
from app.stores.sql import WorkspaceStore

DEFAULT_WS = "31509630-c427-40c4-b182-e1f63fe8c91b"


@dataclass
class Case:
    question: str
    must_decision: set[str]
    forbid_modes: set[str] | None = None
    must_contain: list[str] | None = None


CASES = [
    Case(
        "Compare SL3000 and SL2000",
        must_decision={"answer"},
        forbid_modes={"clarify"},
        must_contain=["SL2000", "SL3000"],
    ),
    Case(
        "What is PlayReady?",
        must_decision={"answer"},
        must_contain=["PlayReady"],
    ),
    Case(
        "What is an OPL in PlayReady?",
        must_decision={"answer", "clarify"},
    ),
    Case(
        "How does license acquisition work?",
        must_decision={"answer", "clarify"},
    ),
]


async def main() -> int:
    ws = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WS
    passed = 0
    failed = 0
    async with WorkspaceStore() as store:
        for case in CASES:
            res = await run_ask_chat(store, workspace_id=ws, question=case.question)
            decision = (res.decision or "").lower()
            mode = (res.retrieval_mode or "").lower()
            answer = res.answer or res.clarification_prompt or ""
            ok = decision in case.must_decision
            if case.forbid_modes and mode in case.forbid_modes:
                ok = False
            if case.must_contain:
                blob = answer.lower()
                if not all(t.lower() in blob for t in case.must_contain):
                    ok = False
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
            print(
                f"[{status}] {case.question!r} → decision={decision} mode={mode} "
                f"trust={getattr(res.trust_score, 'overall', None)}"
            )
            if not ok:
                print(f"       preview={answer[:180]!r}")
    print(f"\nSummary: {passed} passed, {failed} failed / {len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
