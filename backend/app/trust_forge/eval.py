"""Ask golden-suite evaluation used by Trust Forge and CLI."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agents.base import AgentContext
from app.runtime import get_runtime
from app.stores.sql import WorkspaceStore

REPO_GOLDEN_ROOTS = [
    Path("/app/tests/golden"),
    Path(__file__).resolve().parents[2] / "tests" / "golden",
    Path(__file__).resolve().parents[3] / "tests" / "golden",
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def golden_roots() -> list[Path]:
    return [p for p in REPO_GOLDEN_ROOTS if p.is_dir()]


def load_suite(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_suite_path"] = str(path)
    return data


def resolve_suite_path(suite: str) -> Path:
    """Resolve absolute path, relative path, or path under golden roots."""
    raw = (suite or "").strip()
    if not raw:
        raise FileNotFoundError("Empty suite path")
    path = Path(raw)
    if path.is_file():
        return path.resolve()
    for root in golden_roots():
        cand = root / raw
        if cand.is_file():
            return cand.resolve()
        # allow suite_id stem search
        for hit in root.rglob("*.json"):
            if hit.name.startswith("_"):
                continue
            if hit.stem == raw or hit.name == raw:
                return hit.resolve()
    raise FileNotFoundError(f"Suite not found: {suite}")


def find_suite_for_agent(agent_name: str) -> Path | None:
    """Pick the best golden suite for an agent (must include non-empty cases[]).

    Skips inventory files like thoughtworks_kb_pages.json that share agent_name
    but have no eval cases (those produced Trust Forge 0/0 runs).
    Preference: most cases, then newer-looking suite_id / filename.
    """
    key = agent_name.strip().lower()
    candidates: list[tuple[int, str, Path]] = []
    for root in golden_roots():
        for path in root.rglob("*.json"):
            if path.name.startswith("_"):
                continue
            # Coverage / page dumps are not golden ask suites
            stem = path.stem.lower()
            if stem.endswith("_coverage") or stem.endswith("_kb_pages") or stem.endswith("_pages"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            name = (data.get("agent_name") or "").strip().lower()
            if not name or name != key:
                continue
            cases = data.get("cases")
            if not isinstance(cases, list) or len(cases) == 0:
                continue
            # Prefer real ask cases (must have question)
            ask_cases = [
                c
                for c in cases
                if isinstance(c, dict) and (c.get("question") or "").strip()
            ]
            if not ask_cases:
                continue
            suite_id = str(data.get("suite_id") or path.stem)
            candidates.append((len(ask_cases), suite_id, path))
    if not candidates:
        return None
    return pick_best_suite(candidates)


def pick_best_suite(candidates: list[tuple[int, str, Path]]) -> Path:
    """Prefer *_core web suites (exclude news archive) over largest full dumps."""
    if not candidates:
        raise FileNotFoundError("no suite candidates")
    cleaned = [
        c
        for c in candidates
        if "overlap" not in c[1].lower() and "overlap" not in c[2].stem.lower()
    ] or candidates
    core = [
        c
        for c in cleaned
        if "_core" in c[1].lower() or c[2].stem.lower().endswith("_core")
    ]
    pool = core or cleaned
    pool.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return pool[0][2]


async def resolve_agent(agent_name: str) -> tuple[str, str]:
    async with WorkspaceStore() as store:
        agents = await store.list_agents()
        for a in agents:
            if (a.get("name") or "").strip().lower() == agent_name.strip().lower():
                return a["id"], a["workspace_id"]
        names = [a.get("name") for a in agents]
        raise RuntimeError(f"Agent {agent_name!r} not found. Present: {names}")


async def run_case(workspace_id: str, case: dict[str, Any]) -> dict[str, Any]:
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
    ans_n = norm(answer)
    expect = (case.get("expect_decision") or "answer").lower()

    ok = True
    notes: list[str] = []
    fail_kind = ""
    if expect == "either":
        if decision not in {"answer", "refuse", "clarify"}:
            ok = False
            notes.append(f"decision={decision}")
            fail_kind = "bad_decision"
    elif decision != expect:
        ok = False
        notes.append(f"decision={decision} expected={expect}")
        if expect == "answer" and decision == "refuse":
            fail_kind = "refuse_wrong"
        elif expect == "answer" and decision == "clarify":
            fail_kind = "clarify_wrong"
        elif expect == "refuse" and decision == "answer":
            fail_kind = "should_refuse"
        else:
            fail_kind = "decision_mismatch"

    must_any = case.get("must_any") or []
    if must_any and expect == "answer" and decision == "answer":
        if not any(norm(p) in ans_n for p in must_any):
            ok = False
            notes.append("missing must_any")
            fail_kind = fail_kind or "must_any_miss"

    for phrase in case.get("forbid_any") or []:
        if norm(phrase) and norm(phrase) in ans_n:
            ok = False
            notes.append(f"forbid:{phrase}")
            fail_kind = fail_kind or "forbid_hit"
            break

    cites = bag.get("citations") or bag.get("quote_citations") or []
    cite_blob = norm(
        " ".join(
            str(c.get("document_title") or c.get("title") or c.get("doc_id") or "")
            for c in cites
            if isinstance(c, dict)
        )
    )
    citation_any = case.get("citation_any") or []
    if citation_any and decision == "answer" and cites:
        if not any(norm(p) in cite_blob for p in citation_any):
            notes.append("citation_soft_miss")

    retrieval_ok: bool | None = None
    source_url = case.get("source_url")
    if source_url:
        from app.knowledge.sources.web.site_graph import slug_tokens

        hay = cite_blob + " " + ans_n
        toks = slug_tokens(str(source_url))
        retrieval_ok = bool(toks) and any(t.replace(" ", "") in hay.replace(" ", "") for t in toks[-2:])

    if ok:
        fail_kind = ""

    try:
        from app.knowledge_os.learn import credit_outcome, propose_draft

        eids: list[str] = []
        for hop in bag.get("trust_trail") or []:
            if isinstance(hop, dict) and hop.get("edge_id"):
                eids.append(str(hop["edge_id"]))
            else:
                eid = getattr(hop, "edge_id", None)
                if eid:
                    eids.append(str(eid))
        async with WorkspaceStore() as store:
            if eids:
                await credit_outcome(store, workspace_id, edge_ids=eids, won=ok)
            if not ok and retrieval_ok is False:
                await propose_draft(
                    store,
                    workspace_id,
                    question=case["question"],
                    answer_preview=answer[:400],
                    source_url=case.get("source_url"),
                    retrieval_ok=False,
                    fail_kind=fail_kind or "fail",
                    origin="eval",
                )
    except Exception:  # noqa: BLE001
        pass

    return {
        "id": case["id"],
        "pass": ok,
        "decision": decision,
        "fail_kind": fail_kind,
        "retrieval_ok": retrieval_ok,
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


ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]


async def eval_suite(
    workspace_id: str,
    suite: dict[str, Any],
    *,
    case_ids: set[str] | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Run all (or filtered) cases; return fitness summary."""
    cases = list(suite.get("cases") or [])
    if not case_ids:
        try:
            from app.knowledge_os.learn import draft_to_case

            async with WorkspaceStore() as store:
                drafts = await store.list_draft_goldens(workspace_id, status="accepted")
            extra = [draft_to_case(r) for r in drafts if r.get("question")]
            cases = extra + cases
        except Exception:  # noqa: BLE001
            pass
    if case_ids:
        cases = [c for c in cases if c.get("id") in case_ids]

    rows: list[dict[str, Any]] = []
    total_cases = len(cases)
    for i, case in enumerate(cases):
        if on_progress is not None:
            await on_progress(
                {
                    "phase": "evaluating",
                    "case_index": i + 1,
                    "case_total": total_cases,
                    "case_id": case.get("id"),
                    "question": case.get("question") or "",
                    "expected_answer": case.get("expected_answer") or "",
                    "passed_so_far": sum(1 for r in rows if r.get("pass")),
                    "failed_so_far": sum(1 for r in rows if not r.get("pass")),
                    "message": f"Evaluating {(case.get('id') or '?')} ({i + 1}/{total_cases})",
                }
            )
        row = await run_case(workspace_id, case)
        rows.append(row)
        if on_progress is not None:
            await on_progress(
                {
                    "phase": "evaluating",
                    "case_index": i + 1,
                    "case_total": total_cases,
                    "case_id": case.get("id"),
                    "question": case.get("question") or "",
                    "expected_answer": case.get("expected_answer") or "",
                    "got_answer": row.get("answer_preview") or "",
                    "decision": row.get("decision") or "",
                    "case_pass": bool(row.get("pass")),
                    "fail_kind": row.get("fail_kind") or "",
                    "passed_so_far": sum(1 for r in rows if r.get("pass")),
                    "failed_so_far": sum(1 for r in rows if not r.get("pass")),
                    "message": (
                        f"{'PASS' if row.get('pass') else 'FAIL'} "
                        f"{(case.get('id') or '?')} ({i + 1}/{total_cases})"
                    ),
                }
            )

    passed = sum(1 for r in rows if r["pass"])
    total = len(rows)
    fail_taxonomy: dict[str, int] = {}
    for r in rows:
        kind = (r.get("fail_kind") or "").strip()
        if kind:
            fail_taxonomy[kind] = fail_taxonomy.get(kind, 0) + 1

    retrieval_known = [r for r in rows if r.get("retrieval_ok") is not None]
    retrieval_hits = sum(1 for r in retrieval_known if r.get("retrieval_ok"))
    fitness = round(100.0 * passed / max(total, 1), 2)
    return {
        "suite_id": suite.get("suite_id"),
        "suite_path": suite.get("_suite_path"),
        "source_kind": suite.get("source_kind"),
        "workspace_id": workspace_id,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "fitness": fitness,
        "pass_rate": round(passed / max(total, 1), 4),
        "retrieval_rate": (
            round(retrieval_hits / max(len(retrieval_known), 1), 4) if retrieval_known else None
        ),
        "fail_ids": [r["id"] for r in rows if not r["pass"]],
        "fail_taxonomy": fail_taxonomy,
        "results": rows,
    }
