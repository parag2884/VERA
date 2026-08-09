"""Run Ask golden suites from tests/golden/ (web + documents + refuse).

Usage (inside vera-api):
  python /app/scripts/ask_eval_golden.py --suite /app/tests/golden/web/thoughtworks_v2.json
  python /app/scripts/ask_eval_golden.py --agent "Thoughtworks Assistant"
  python /app/scripts/ask_eval_golden.py --agent "PlayReady" --suite /app/tests/golden/documents/playready_v1.json
  python /app/scripts/ask_eval_golden.py --agent "Thoughtworks Assistant" --suite /app/tests/golden/refuse/ood_common.json

Suites live under tests/golden/{web,documents,refuse}/ — draft Q&A from the KB sources
(website pages or uploaded PDFs/txt), then cross-verify bot answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path

from app.agents.base import AgentContext
from app.runtime import get_runtime
from app.stores.sql import WorkspaceStore

REPO_GOLDEN_ROOTS = [
    Path("/app/tests/golden"),
    # /app/scripts → /app/tests/golden; backend/scripts → backend/tests/golden
    Path(__file__).resolve().parents[1] / "tests" / "golden",
    # backend/scripts → repo tests/golden
    Path(__file__).resolve().parents[2] / "tests" / "golden",
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _golden_roots() -> list[Path]:
    return [p for p in REPO_GOLDEN_ROOTS if p.is_dir()]


def _load_suite(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_suite_path"] = str(path)
    return data


def _find_suite_for_agent(agent_name: str) -> Path | None:
    key = agent_name.strip().lower()
    for root in _golden_roots():
        for path in sorted(root.rglob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            name = (data.get("agent_name") or "").strip().lower()
            if name and name == key:
                return path
    return None


async def _resolve_workspace(agent_name: str) -> tuple[str, str]:
    async with WorkspaceStore() as store:
        agents = await store.list_agents()
        for a in agents:
            if (a.get("name") or "").strip().lower() == agent_name.strip().lower():
                return a["id"], a["workspace_id"]
        names = [a.get("name") for a in agents]
        raise RuntimeError(f"Agent {agent_name!r} not found. Present: {names}")


async def run_case(workspace_id: str, case: dict) -> dict:
    runtime = get_runtime()
    t0 = time.perf_counter()
    async with WorkspaceStore() as store:
        ctx = AgentContext(
            workspace_id=workspace_id,
            demo_mode=runtime.demo_mode,
            stores=store,
            llm=runtime.llm,
            config={"vector_store": runtime.vector_store},
        )
        result = await runtime.orchestrator.run(
            "ask_pipeline", ctx, {"question": case["question"]}
        )
    bag = result.bag or {}
    elapsed = round(time.perf_counter() - t0, 2)
    decision = (bag.get("decision") or "").lower()
    answer = bag.get("answer") or bag.get("clarification_prompt") or ""
    ans_n = _norm(answer)
    expect = (case.get("expect_decision") or "answer").lower()

    ok = True
    notes: list[str] = []
    if expect == "either":
        if decision not in {"answer", "refuse", "clarify"}:
            ok = False
            notes.append(f"decision={decision}")
    elif decision != expect:
        ok = False
        notes.append(f"decision={decision} expected={expect}")

    must_any = case.get("must_any") or []
    if must_any and expect == "answer" and decision == "answer":
        if not any(_norm(p) in ans_n for p in must_any):
            ok = False
            notes.append("missing must_any")

    for phrase in case.get("forbid_any") or []:
        if _norm(phrase) and _norm(phrase) in ans_n:
            ok = False
            notes.append(f"forbid:{phrase}")
            break

    cites = bag.get("citations") or bag.get("quote_citations") or []
    cite_blob = _norm(
        " ".join(
            str(c.get("document_title") or c.get("title") or c.get("doc_id") or "")
            for c in cites
            if isinstance(c, dict)
        )
    )
    citation_any = case.get("citation_any") or []
    if citation_any and decision == "answer" and cites:
        if not any(_norm(p) in cite_blob for p in citation_any):
            notes.append("citation_soft_miss")

    return {
        "id": case["id"],
        "pass": ok,
        "decision": decision,
        "elapsed_s": elapsed,
        "question": case["question"],
        "expected_answer": case.get("expected_answer"),
        "source_url": case.get("source_url"),
        "source_document": case.get("source_document"),
        "kb_quote_hint": case.get("kb_quote_hint"),
        "answer_preview": answer[:280],
        "notes": notes,
        "must_any": must_any,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run KB-grounded Ask golden suites")
    parser.add_argument("--suite", default="", help="Path to suite JSON")
    parser.add_argument("--agent", default=None, help="Agent name (required for refuse suites)")
    parser.add_argument("--ids", default="", help="Comma-separated case ids")
    args = parser.parse_args()

    suite_path: Path | None = None
    if args.suite.strip():
        suite_path = Path(args.suite.strip())
        if not suite_path.is_file():
            # try under golden roots
            for root in _golden_roots():
                cand = root / args.suite.strip()
                if cand.is_file():
                    suite_path = cand
                    break
        if not suite_path or not suite_path.is_file():
            raise FileNotFoundError(f"Suite not found: {args.suite}")
    elif args.agent:
        suite_path = _find_suite_for_agent(args.agent)
        if not suite_path:
            raise FileNotFoundError(
                f"No suite with agent_name={args.agent!r} under tests/golden/"
            )
    else:
        raise SystemExit("Provide --suite and/or --agent")

    golden = _load_suite(suite_path)
    agent_name = args.agent or golden.get("agent_name")
    if not agent_name:
        raise SystemExit("Suite has no agent_name; pass --agent")

    agent_id, workspace_id = await _resolve_workspace(agent_name)
    cases = list(golden.get("cases") or [])
    if args.ids.strip():
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        cases = [c for c in cases if c.get("id") in want]

    print(
        f"suite={golden.get('suite_id')} kind={golden.get('source_kind')} "
        f"file={suite_path}\n"
        f"Running {len(cases)} cases on agent={agent_name!r} "
        f"id={agent_id} workspace={workspace_id}",
        flush=True,
    )
    rows = []
    for case in cases:
        print(f"running {case['id']}...", flush=True)
        row = await run_case(workspace_id, case)
        status = "PASS" if row["pass"] else "FAIL"
        src = row.get("source_url") or row.get("source_document") or ""
        print(
            f"  {status} decision={row['decision']} {row['elapsed_s']}s | "
            f"{(row.get('answer_preview') or '')[:90]}",
            flush=True,
        )
        if src:
            print(f"    verify↔ {src}", flush=True)
        rows.append(row)

    passed = sum(1 for r in rows if r["pass"])
    suite_id = golden.get("suite_id") or suite_path.stem
    summary = {
        "suite_id": suite_id,
        "source_kind": golden.get("source_kind"),
        "suite_path": str(suite_path),
        "agent_name": agent_name,
        "agent_id": agent_id,
        "workspace_id": workspace_id,
        "passed": passed,
        "total": len(rows),
        "fail_ids": [r["id"] for r in rows if not r["pass"]],
        "results": rows,
    }
    out_candidates = [
        Path(f"/app/data/ask_eval_{suite_id}_results.json"),
        Path(__file__).resolve().parent / f"ask_eval_{suite_id}_results.json",
    ]
    out = next((p for p in out_candidates if p.parent.exists()), out_candidates[-1])
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: summary[k] for k in ("passed", "total", "fail_ids", "suite_id", "source_kind")},
            indent=2,
        )
    )
    print(f"wrote {out}", flush=True)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
