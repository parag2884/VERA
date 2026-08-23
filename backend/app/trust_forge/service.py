"""Trust Forge — workspace-isolated eval → heal → climb toward fitness threshold."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db import get_connection
from app.stores.sql import WorkspaceStore
from app.trust_forge.eval import (
    eval_suite,
    find_suite_for_agent,
    load_suite,
    resolve_suite_path,
)
from app.trust_forge.heal import heal_workspace
from app.knowledge_os.service import enrich_graph

log = logging.getLogger("vera.trust_forge")

_stop_flags: dict[str, bool] = {}
_tasks: dict[str, asyncio.Task[None]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jid() -> str:
    return str(uuid4())


async def _row_to_run(row: Any) -> dict[str, Any]:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    progress_raw = row["progress_json"] if "progress_json" in keys else "{}"
    try:
        progress = json.loads(progress_raw or "{}")
    except Exception:  # noqa: BLE001
        progress = {}
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "agent_id": row["agent_id"],
        "suite_path": row["suite_path"],
        "threshold": row["threshold"],
        "max_generations": row["max_generations"],
        "stall_generations": row["stall_generations"],
        "status": row["status"],
        "best_fitness": row["best_fitness"],
        "generation": row["generation"],
        "stop_reason": row["stop_reason"],
        "error": row["error"],
        "progress": progress if isinstance(progress, dict) else {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _set_progress(run_id: str, workspace_id: str, progress: dict[str, Any]) -> None:
    await _update_run(
        run_id,
        workspace_id,
        progress_json=json.dumps(progress or {}),
    )


def _case_map(rows: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("id"):
            out[str(r["id"])] = r
    return out


def _diff_generations(
    prev_cases: dict[str, dict[str, Any]] | None,
    cur_cases: dict[str, dict[str, Any]],
    *,
    prev_fitness: float | None,
    cur_fitness: float,
    hygiene: dict[str, Any],
) -> dict[str, Any]:
    """Explain real improvement vs prior generation (not just a higher %)."""
    if not prev_cases:
        return {
            "vs_gen": None,
            "fitness_before": None,
            "fitness_after": cur_fitness,
            "fitness_delta": None,
            "newly_passed": [],
            "newly_failed": [],
            "still_failed": [
                {
                    "id": cid,
                    "fail_kind": (row.get("fail_kind") or "") or "fail",
                }
                for cid, row in sorted(cur_cases.items())
                if not row.get("pass")
            ],
            "heal": hygiene or {},
            "summary": f"Baseline · {cur_fitness:g}%",
        }

    newly_passed: list[dict[str, Any]] = []
    newly_failed: list[dict[str, Any]] = []
    still_failed: list[dict[str, Any]] = []
    for cid, cur in cur_cases.items():
        prev = prev_cases.get(cid) or {}
        cur_ok = bool(cur.get("pass"))
        prev_ok = bool(prev.get("pass"))
        if cur_ok and not prev_ok:
            newly_passed.append(
                {
                    "id": cid,
                    "was_fail_kind": (prev.get("fail_kind") or "") or "fail",
                }
            )
        elif (not cur_ok) and prev_ok:
            newly_failed.append(
                {
                    "id": cid,
                    "fail_kind": (cur.get("fail_kind") or "") or "fail",
                }
            )
        elif not cur_ok:
            still_failed.append(
                {
                    "id": cid,
                    "fail_kind": (cur.get("fail_kind") or "") or "fail",
                }
            )

    before = float(prev_fitness if prev_fitness is not None else 0)
    delta = round(cur_fitness - before, 2)
    parts = [f"{before:g}% → {cur_fitness:g}% ({delta:+g} pts)"]
    if newly_passed:
        parts.append(
            "now pass: " + ", ".join(x["id"] for x in newly_passed[:8])
            + ("…" if len(newly_passed) > 8 else "")
        )
    if newly_failed:
        parts.append(
            "regressed: " + ", ".join(x["id"] for x in newly_failed[:6])
        )
    removed = int((hygiene or {}).get("aliases_removed") or 0)
    retyped = int((hygiene or {}).get("junk_persons_retyped") or 0)
    if removed or retyped:
        parts.append(f"heal: −{removed} aliases, {retyped} persons retyped")

    return {
        "vs_gen": True,
        "fitness_before": before,
        "fitness_after": cur_fitness,
        "fitness_delta": delta,
        "newly_passed": newly_passed,
        "newly_failed": newly_failed,
        "still_failed": still_failed,
        "heal": hygiene or {},
        "summary": " · ".join(parts),
    }


async def get_run(workspace_id: str, run_id: str) -> dict[str, Any] | None:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            "SELECT * FROM trust_forge_runs WHERE id = ? AND workspace_id = ?",
            (run_id, workspace_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        run = await _row_to_run(row)
        cur = await conn.execute(
            """
            SELECT gen, fitness, passed, failed, total, hygiene_report_json,
                   case_results_json, created_at
            FROM trust_forge_generations
            WHERE run_id = ? AND workspace_id = ?
            ORDER BY gen ASC
            """,
            (run_id, workspace_id),
        )
        gens = []
        prev_cases: dict[str, dict[str, Any]] | None = None
        prev_fitness: float | None = None
        for g in await cur.fetchall():
            case_rows = json.loads(g["case_results_json"] or "[]")
            cur_cases = _case_map(case_rows if isinstance(case_rows, list) else [])
            hygiene = json.loads(g["hygiene_report_json"] or "{}")
            delta = _diff_generations(
                prev_cases,
                cur_cases,
                prev_fitness=prev_fitness,
                cur_fitness=float(g["fitness"] or 0),
                hygiene=hygiene if isinstance(hygiene, dict) else {},
            )
            gens.append(
                {
                    "gen": g["gen"],
                    "fitness": g["fitness"],
                    "passed": g["passed"],
                    "failed": g["failed"],
                    "total": g["total"],
                    "hygiene_report": hygiene,
                    "fail_ids": [
                        r.get("id")
                        for r in case_rows
                        if isinstance(r, dict) and not r.get("pass")
                    ],
                    "case_results": [
                        {
                            "id": r.get("id"),
                            "pass": bool(r.get("pass")),
                            "fail_kind": r.get("fail_kind") or "",
                            "decision": r.get("decision") or "",
                            "question": r.get("question") or "",
                            "expected_answer": r.get("expected_answer") or "",
                            "answer_preview": r.get("answer_preview") or "",
                            "must_any": r.get("must_any") or [],
                            "notes": r.get("notes") or [],
                        }
                        for r in case_rows
                        if isinstance(r, dict) and r.get("id")
                    ],
                    "delta": delta,
                    "created_at": g["created_at"],
                }
            )
            prev_cases = cur_cases
            prev_fitness = float(g["fitness"] or 0)
        run["generations"] = gens
        run["fitness_curve"] = [g["fitness"] for g in gens]
        # Latest non-baseline improvement story for the panel
        improvements = [g["delta"] for g in gens if g.get("delta", {}).get("vs_gen")]
        run["latest_improvement"] = improvements[-1] if improvements else (
            gens[-1]["delta"] if gens else None
        )
        suite_meta = _suite_case_meta(str(run.get("suite_path") or ""))
        run["case_matrix"] = _build_case_matrix(gens, suite_meta=suite_meta)
        run["graph_changes"] = _build_graph_changes(gens)
        return run
    finally:
        await conn.close()


def _suite_case_meta(suite_path: str) -> dict[str, dict[str, Any]]:
    """Load question / expected answer from golden suite (works for older runs too)."""
    if not suite_path:
        return {}
    try:
        path = Path(suite_path)
        if not path.is_file():
            path = resolve_suite_path(suite_path)
        suite = load_suite(path)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    for c in suite.get("cases") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        out[str(c["id"])] = {
            "question": c.get("question") or "",
            "expected_answer": c.get("expected_answer") or "",
            "must_any": c.get("must_any") or [],
            "kb_quote_hint": c.get("kb_quote_hint") or "",
            "source_document": c.get("source_document") or c.get("source_url") or "",
        }
    return out


def _build_case_matrix(
    gens: list[dict[str, Any]],
    *,
    suite_meta: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Case × generation pass/fail matrix for the Trust Forge page."""
    if not gens:
        return {"generations": [], "rows": []}
    suite_meta = suite_meta or {}
    gen_nums = [int(g["gen"]) for g in gens]
    maps: list[dict[str, dict[str, Any]]] = []
    all_ids: set[str] = set()
    for g in gens:
        m = {
            str(r["id"]): r
            for r in (g.get("case_results") or [])
            if isinstance(r, dict) and r.get("id")
        }
        maps.append(m)
        all_ids.update(m.keys())
    all_ids.update(suite_meta.keys())

    rows = []
    latest = maps[-1] if maps else {}
    for cid in sorted(all_ids):
        cells = []
        first: bool | None = None
        last: bool | None = None
        for m in maps:
            if cid not in m:
                cells.append({"status": "unknown", "fail_kind": ""})
                continue
            ok = bool(m[cid].get("pass"))
            cells.append(
                {
                    "status": "pass" if ok else "fail",
                    "fail_kind": m[cid].get("fail_kind") or "",
                    "decision": m[cid].get("decision") or "",
                    "answer_preview": (m[cid].get("answer_preview") or "")[:220],
                }
            )
            if first is None:
                first = ok
            last = ok
        trend = "same"
        if first is True and last is False:
            trend = "regressed"
        elif first is False and last is True:
            trend = "improved"
        elif first is False and last is False:
            trend = "still_fail"
        elif first is True and last is True:
            trend = "still_pass"

        meta = suite_meta.get(cid) or {}
        latest_row = latest.get(cid) or {}
        rows.append(
            {
                "id": cid,
                "cells": cells,
                "trend": trend,
                "question": latest_row.get("question") or meta.get("question") or "",
                "expected_answer": latest_row.get("expected_answer")
                or meta.get("expected_answer")
                or "",
                "got_answer": latest_row.get("answer_preview") or "",
                "decision": latest_row.get("decision") or "",
                "fail_kind": latest_row.get("fail_kind") or "",
                "must_any": latest_row.get("must_any") or meta.get("must_any") or [],
                "kb_quote_hint": meta.get("kb_quote_hint") or "",
                "source": meta.get("source_document") or "",
                "notes": latest_row.get("notes") or [],
            }
        )

    improved = sum(1 for r in rows if r["trend"] == "improved")
    regressed = sum(1 for r in rows if r["trend"] == "regressed")
    still_fail = sum(1 for r in rows if r["trend"] == "still_fail")
    return {
        "generations": gen_nums,
        "rows": rows,
        "summary": {
            "improved": improved,
            "regressed": regressed,
            "still_fail": still_fail,
            "total": len(rows),
        },
    }


def _build_graph_changes(gens: list[dict[str, Any]]) -> dict[str, Any]:
    """KG hygiene timeline for a simple graph-change visualization."""
    steps = []
    total_aliases = 0
    total_retyped = 0
    for g in gens:
        h = g.get("hygiene_report") or {}
        if not isinstance(h, dict):
            h = {}
        removed = int(h.get("aliases_removed") or 0)
        retyped = int(h.get("junk_persons_retyped") or 0)
        total_aliases += removed
        total_retyped += retyped
        steps.append(
            {
                "gen": g.get("gen"),
                "aliases_removed": removed,
                "junk_persons_retyped": retyped,
                "alias_count": h.get("alias_count"),
                "entity_count": h.get("entity_count"),
                "code_or_level_nodes": h.get("code_or_level_nodes"),
                "had_heal": removed > 0 or retyped > 0 or int(g.get("gen") or 0) > 0,
            }
        )
    return {
        "steps": steps,
        "totals": {
            "aliases_removed": total_aliases,
            "junk_persons_retyped": total_retyped,
        },
    }


async def list_runs(workspace_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """
            SELECT * FROM trust_forge_runs
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        )
        rows = await cur.fetchall()
        return [await _row_to_run(r) for r in rows]
    finally:
        await conn.close()


async def abandon_orphaned_runs() -> int:
    """After a container restart, queued/running rows have no worker. Unblock Start."""
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """
            UPDATE trust_forge_runs
            SET status = 'stopped', stop_reason = 'process_restart', error = NULL, updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (_now(),),
        )
        await conn.commit()
        return int(cur.rowcount or 0)
    except Exception:  # noqa: BLE001
        return 0
    finally:
        await conn.close()


async def _active_run_for_workspace(workspace_id: str) -> dict[str, Any] | None:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """
            SELECT * FROM trust_forge_runs
            WHERE workspace_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (workspace_id,),
        )
        row = await cur.fetchone()
        return await _row_to_run(row) if row else None
    finally:
        await conn.close()


async def _update_run(run_id: str, workspace_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [run_id, workspace_id]
    conn = await get_connection()
    try:
        await conn.execute(
            f"UPDATE trust_forge_runs SET {cols} WHERE id = ? AND workspace_id = ?",
            vals,
        )
        await conn.commit()
    finally:
        await conn.close()


async def _insert_generation(
    *,
    run_id: str,
    workspace_id: str,
    gen: int,
    summary: dict[str, Any],
    hygiene_report: dict[str, Any],
) -> None:
    conn = await get_connection()
    try:
        # Persist case outcomes + Q/A previews for the matrix detail pane
        compact = [
            {
                "id": r.get("id"),
                "pass": r.get("pass"),
                "fail_kind": r.get("fail_kind"),
                "decision": r.get("decision"),
                "question": r.get("question"),
                "expected_answer": r.get("expected_answer"),
                "answer_preview": r.get("answer_preview"),
                "must_any": r.get("must_any") or [],
                "source_url": r.get("source_url"),
                "retrieval_ok": r.get("retrieval_ok"),
                "notes": r.get("notes") or [],
            }
            for r in (summary.get("results") or [])
        ]
        await conn.execute(
            """
            INSERT INTO trust_forge_generations (
                id, run_id, workspace_id, gen, fitness, passed, failed, total,
                hygiene_report_json, case_results_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _jid(),
                run_id,
                workspace_id,
                gen,
                float(summary.get("fitness") or 0),
                int(summary.get("passed") or 0),
                int(summary.get("failed") or 0),
                int(summary.get("total") or 0),
                json.dumps(hygiene_report or {}),
                json.dumps(compact),
                _now(),
            ),
        )
        await conn.commit()
    finally:
        await conn.close()


async def request_stop(workspace_id: str, run_id: str) -> dict[str, Any]:
    run = await get_run(workspace_id, run_id)
    if not run:
        raise KeyError("run_not_found")
    if run["status"] in {"completed", "failed", "stopped"}:
        return run
    _stop_flags[run_id] = True
    await _update_run(run_id, workspace_id, status="stopped", stop_reason="user_stop")
    return await get_run(workspace_id, run_id) or run


async def start_run(
    workspace_id: str,
    *,
    agent_id: str | None = None,
    suite_path: str | None = None,
    threshold: float = 95.0,
    max_generations: int = 8,
    stall_generations: int = 3,
) -> dict[str, Any]:
    threshold = max(0.0, min(100.0, float(threshold)))
    max_generations = max(1, min(40, int(max_generations)))
    stall_generations = max(1, min(20, int(stall_generations)))

    active = await _active_run_for_workspace(workspace_id)
    if active:
        raise RuntimeError(
            f"Trust Forge already {active['status']} for this workspace "
            f"(run_id={active['id']}). Stop it or wait."
        )

    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise KeyError("workspace_not_found")
        agent = None
        if agent_id:
            agent = await store.get_agent(agent_id)
        else:
            agent = await store.get_agent_by_workspace(workspace_id)
        if not agent:
            raise KeyError("agent_not_found")
        if agent["workspace_id"] != workspace_id:
            raise PermissionError("agent_workspace_mismatch")
        agent_id = agent["id"]
        agent_name = agent.get("name") or ""

    resolved_suite: str
    if suite_path and suite_path.strip():
        resolved_suite = str(resolve_suite_path(suite_path.strip()))
    else:
        found = find_suite_for_agent(agent_name)
        if not found:
            raise FileNotFoundError(
                f"No golden suite for agent {agent_name!r}. Pass suite_path."
            )
        resolved_suite = str(found)

    # Validate suite loads and has ask cases (avoid 0/0 plateau runs)
    suite_check = load_suite(Path(resolved_suite))
    ask_n = sum(
        1
        for c in (suite_check.get("cases") or [])
        if isinstance(c, dict) and (c.get("question") or "").strip()
    )
    if ask_n <= 0:
        raise FileNotFoundError(
            f"Suite {resolved_suite!r} has no ask cases. "
            "Use a golden file under tests/golden with a non-empty cases[] "
            "(not a kb_pages / coverage dump)."
        )

    run_id = _jid()
    now = _now()
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO trust_forge_runs (
                id, workspace_id, agent_id, suite_path, threshold,
                max_generations, stall_generations, status, best_fitness,
                generation, stop_reason, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, NULL, NULL, ?, ?)
            """,
            (
                run_id,
                workspace_id,
                agent_id,
                resolved_suite,
                threshold,
                max_generations,
                stall_generations,
                now,
                now,
            ),
        )
        await conn.commit()
    finally:
        await conn.close()

    _stop_flags[run_id] = False
    task = asyncio.create_task(
        _run_loop(run_id, workspace_id),
        name=f"trust-forge-{run_id[:8]}",
    )
    _tasks[run_id] = task

    def _done(t: asyncio.Task[None]) -> None:
        _tasks.pop(run_id, None)
        try:
            t.result()
        except Exception:  # noqa: BLE001
            log.exception("trust forge task failed run_id=%s", run_id)

    task.add_done_callback(_done)
    return await get_run(workspace_id, run_id)  # type: ignore[return-value]


async def _run_loop(run_id: str, workspace_id: str) -> None:
    try:
        await _update_run(run_id, workspace_id, status="running")
        await _set_progress(
            run_id,
            workspace_id,
            {
                "phase": "starting",
                "message": "Starting Trust Forge…",
                "log": ["Queued climb for this workspace only"],
            },
        )
        conn = await get_connection()
        try:
            cur = await conn.execute(
                "SELECT * FROM trust_forge_runs WHERE id = ? AND workspace_id = ?",
                (run_id, workspace_id),
            )
            row = await cur.fetchone()
        finally:
            await conn.close()
        if not row:
            return

        threshold = float(row["threshold"])
        max_gen = int(row["max_generations"])
        stall_limit = int(row["stall_generations"])
        suite = load_suite(Path(row["suite_path"]))
        case_total = len(suite.get("cases") or [])
        activity_log: list[str] = [
            f"Loaded suite · {case_total} golden cases · target {threshold:g}%"
        ]

        best_f = -1.0
        stall = 0
        stop_reason = "max_generations"
        last_gen = 0
        prev_case_map: dict[str, dict[str, Any]] | None = None
        prev_fitness: float | None = None
        latest_delta: dict[str, Any] | None = None
        summary_for_heal: list[dict[str, Any]] = []

        for gen in range(0, max_gen + 1):
            last_gen = gen
            if _stop_flags.get(run_id):
                stop_reason = "user_stop"
                break

            hygiene_report: dict[str, Any] = {}
            if gen > 0:
                activity_log.append(f"Gen {gen}: healing knowledge graph…")
                await _set_progress(
                    run_id,
                    workspace_id,
                    {
                        "phase": "healing",
                        "generation": gen,
                        "max_generations": max_gen,
                        "case_total": case_total,
                        "message": f"Gen {gen}: hygiene + site graph + failed-fact pins…",
                        "log": activity_log[-12:],
                    },
                )
                await _update_run(run_id, workspace_id, generation=gen)
                failed_for_heal = [
                    r
                    for r in (summary_for_heal or [])
                    if isinstance(r, dict) and not r.get("pass")
                ]
                async with WorkspaceStore() as store:
                    from app.knowledge_os.governance import capture_version

                    await capture_version(
                        store,
                        workspace_id,
                        label=f"pre-heal gen {gen}",
                        status="snapshot",
                        metrics={"generation": gen, "phase": "pre_heal"},
                    )
                    hygiene_report = await heal_workspace(
                        store, workspace_id, failed_cases=failed_for_heal
                    )
                    os_report = await enrich_graph(store, workspace_id)
                    hygiene_report.update(os_report)
                removed = hygiene_report.get("aliases_removed", 0)
                retyped = hygiene_report.get("junk_persons_retyped", 0)
                site_e = hygiene_report.get("site_part_of_edges", 0)
                pins = hygiene_report.get("facts_pinned", 0)
                activity_log.append(
                    f"Gen {gen}: heal done · aliases −{removed} · persons retyped {retyped}"
                    f" · site PART_OF {site_e} · pins {pins}"
                )
                log.info(
                    "trust_forge heal workspace=%s gen=%s aliases_removed=%s junk_persons_retyped=%s",
                    workspace_id,
                    gen,
                    removed,
                    retyped,
                )
            else:
                activity_log.append("Gen 0: baseline eval (no heal yet)")

            if _stop_flags.get(run_id):
                stop_reason = "user_stop"
                break

            async def _on_case(progress: dict[str, Any], *, _gen: int = gen) -> None:
                msg = progress.get("message") or "Evaluating…"
                await _set_progress(
                    run_id,
                    workspace_id,
                    {
                        **progress,
                        "generation": _gen,
                        "max_generations": max_gen,
                        "best_fitness": max(best_f, 0.0),
                        "threshold": threshold,
                        "log": (activity_log + [msg])[-12:],
                    },
                )

            await _set_progress(
                run_id,
                workspace_id,
                {
                    "phase": "evaluating",
                    "generation": gen,
                    "max_generations": max_gen,
                    "case_index": 0,
                    "case_total": case_total,
                    "message": f"Gen {gen}: scoring golden suite…",
                    "log": activity_log[-12:],
                },
            )
            await _update_run(run_id, workspace_id, generation=gen)

            summary = await eval_suite(workspace_id, suite, on_progress=_on_case)
            summary_for_heal = [
                r for r in (summary.get("results") or []) if isinstance(r, dict)
            ]
            fitness = float(summary["fitness"])
            passed = int(summary.get("passed") or 0)
            total = int(summary.get("total") or 0)
            cur_case_map = _case_map(
                [
                    {
                        "id": r.get("id"),
                        "pass": r.get("pass"),
                        "fail_kind": r.get("fail_kind"),
                        "decision": r.get("decision"),
                    }
                    for r in (summary.get("results") or [])
                    if isinstance(r, dict)
                ]
            )
            delta = _diff_generations(
                prev_case_map,
                cur_case_map,
                prev_fitness=prev_fitness,
                cur_fitness=fitness,
                hygiene=hygiene_report,
            )
            latest_delta = delta
            activity_log.append(
                f"Gen {gen}: fitness {fitness:g}% ({passed}/{total} passed)"
            )
            if delta.get("vs_gen"):
                activity_log.append(f"Why it changed · {delta.get('summary')}")
                for item in (delta.get("newly_passed") or [])[:6]:
                    activity_log.append(
                        f"  ✓ {item.get('id')} now passes "
                        f"(was {item.get('was_fail_kind') or 'fail'})"
                    )
                for item in (delta.get("newly_failed") or [])[:4]:
                    activity_log.append(
                        f"  ✗ {item.get('id')} regressed "
                        f"({item.get('fail_kind') or 'fail'})"
                    )
            await _insert_generation(
                run_id=run_id,
                workspace_id=workspace_id,
                gen=gen,
                summary=summary,
                hygiene_report=hygiene_report,
            )
            try:
                from app.knowledge_os.governance import (
                    capture_version,
                    record_metric_snapshot,
                )

                async with WorkspaceStore() as store:
                    await capture_version(
                        store,
                        workspace_id,
                        label=f"eval gen {gen} · {fitness:g}%",
                        status="candidate",
                        metrics={
                            "generation": gen,
                            "fitness": fitness,
                            "passed": passed,
                            "total": total,
                        },
                    )
                await record_metric_snapshot(
                    workspace_id,
                    {
                        "fitness": fitness,
                        "passed": passed,
                        "total": total,
                        "generation": gen,
                    },
                )
            except Exception:  # noqa: BLE001
                log.exception("graph version snapshot failed")
            await _update_run(
                run_id,
                workspace_id,
                generation=gen,
                best_fitness=max(best_f, fitness) if best_f >= 0 else fitness,
            )

            if fitness > best_f + 1e-6:
                best_f = fitness
                stall = 0
                activity_log.append(f"↑ New best {best_f:g}%")
            else:
                stall += 1
                activity_log.append(f"No improvement (stall {stall}/{stall_limit})")

            await _set_progress(
                run_id,
                workspace_id,
                {
                    "phase": "generation_done",
                    "generation": gen,
                    "max_generations": max_gen,
                    "case_index": total,
                    "case_total": total,
                    "passed_so_far": passed,
                    "failed_so_far": total - passed,
                    "fitness": fitness,
                    "best_fitness": best_f,
                    "threshold": threshold,
                    "message": f"Gen {gen} complete · {fitness:g}%",
                    "improvement": delta,
                    "log": activity_log[-14:],
                },
            )
            prev_case_map = cur_case_map
            prev_fitness = fitness

            if fitness >= threshold:
                stop_reason = "threshold_reached"
                activity_log.append(f"Threshold reached ({threshold:g}%)")
                break
            if stall >= stall_limit and gen > 0:
                stop_reason = "plateau"
                activity_log.append("Plateau — stopping climb")
                break

        final_status = "stopped" if stop_reason == "user_stop" else "completed"
        await _set_progress(
            run_id,
            workspace_id,
            {
                "phase": final_status,
                "generation": last_gen,
                "max_generations": max_gen,
                "best_fitness": max(best_f, 0.0),
                "threshold": threshold,
                "message": {
                    "threshold_reached": f"Done — hit {threshold:g}% target",
                    "plateau": "Done — plateau (no further gains)",
                    "max_generations": "Done — generation limit",
                    "user_stop": "Stopped by user",
                }.get(stop_reason, f"Done · {stop_reason}"),
                "improvement": latest_delta,
                "log": activity_log[-14:],
            },
        )
        await _update_run(
            run_id,
            workspace_id,
            status=final_status,
            stop_reason=stop_reason,
            best_fitness=max(best_f, 0.0),
        )
        log.info(
            "trust_forge done workspace=%s run=%s reason=%s best=%.2f",
            workspace_id,
            run_id,
            stop_reason,
            best_f,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("trust_forge failed workspace=%s run=%s", workspace_id, run_id)
        await _set_progress(
            run_id,
            workspace_id,
            {"phase": "failed", "message": str(exc)[:240], "log": [str(exc)[:240]]},
        )
        await _update_run(
            run_id,
            workspace_id,
            status="failed",
            stop_reason="error",
            error=str(exc)[:2000],
        )
    finally:
        _stop_flags.pop(run_id, None)
