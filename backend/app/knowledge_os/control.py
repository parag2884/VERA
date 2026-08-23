"""KnowledgeOps control plane: recs, SLA, goals, freshness, ownership, simulation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.knowledge.sources.web.site_graph import looks_like_web_title, page_path, trust_weight
from app.knowledge_os.coverage import section_for_title

CRITICAL_HINTS = ("complian", "regulat", "policy", "legal", "security", "privacy", "mortgage", "hipaa")
IMPORTANT_HINTS = ("product", "api", "architect", "service", "auth", "payment")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        da = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if da.tzinfo is None:
            da = da.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - da).total_seconds() / 86400.0, 1)
    except Exception:  # noqa: BLE001
        return None


def criticality_for(text: str) -> str:
    t = (text or "").lower()
    if any(h in t for h in CRITICAL_HINTS):
        return "Critical"
    if any(h in t for h in IMPORTANT_HINTS):
        return "Important"
    return "Informational"


def gap_recommendations(cover: dict[str, Any], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    overall_pages = sum(int(d.get("pages") or 0) for d in (cover.get("domains") or [])) or 1
    for d in cover.get("domains") or []:
        pct = float(d.get("coverage_pct") or 0)
        if pct >= 70:
            continue
        pages = int(d.get("pages") or 0)
        gain = round((100.0 - pct) * pages / overall_pages, 1)
        section = str(d.get("section") or "")
        sample = next(
            (
                doc.get("title")
                for doc in docs
                if section_for_title(doc.get("title") or "") == section
            ),
            None,
        )
        path = page_path(str(sample)) if sample and looks_like_web_title(str(sample)) else None
        recs.append(
            {
                "kind": "crawl" if path else "topic",
                "section": section,
                "suggested": path or section,
                "expected_coverage_gain": gain,
                "criticality": criticality_for(section + " " + str(sample or "")),
                "impact": _impact(section, pages),
            }
        )
    recs.sort(key=lambda r: (-_crit_w(r["criticality"]), -float(r["expected_coverage_gain"])))
    return recs[:8]


def _crit_w(c: str) -> int:
    return {"Critical": 3, "Important": 2, "Informational": 1}.get(c, 1)


def _impact(section: str, pages: int) -> dict[str, int]:
    """Placeholder coupling until a real service catalog exists."""
    base = max(1, pages)
    return {
        "pages": pages,
        "apis": min(40, base * (3 if "api" in section or "product" in section else 1)),
        "applications": min(12, max(1, base // 3)),
        "teams": min(8, max(1, 1 + base // 8)),
    }


def evidence_quality(
    *,
    trust_pct: float,
    coverage_pct: float,
    conflict_count: int,
    freshness_avg_days: float | None,
) -> dict[str, Any]:
    fresh = 100.0
    if freshness_avg_days is not None:
        fresh = max(0.0, 100.0 - min(90.0, freshness_avg_days / 4.0))
    consist = max(0.0, 100.0 - min(80.0, conflict_count * 8.0))
    authority = float(trust_pct or 0)
    cover = float(coverage_pct or 0)
    score = round(0.28 * cover + 0.24 * authority + 0.24 * fresh + 0.24 * consist, 1)
    return {
        "score": score,
        "coverage": round(cover, 1),
        "authority": round(authority, 1),
        "freshness": round(fresh, 1),
        "consistency": round(consist, 1),
    }


def sla_status(
    *,
    coverage: float,
    debt: float,
    contradictions: int,
    targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = {k: v for k, v in (targets or {}).items() if v is not None}
    t = {
        "coverage_min": 90.0,
        "debt_max": 10.0,
        "contradictions_max": 5,
        **extra,
    }
    playbook = [
        {
            "id": "coverage",
            "title": "Coverage",
            "ok": coverage >= float(t["coverage_min"]),
            "current": coverage,
            "target": f">= {t['coverage_min']}%",
            "next": "Ingest or link pages for uncovered sections (Connect).",
            "cta": "connect",
        },
        {
            "id": "debt",
            "title": "Debt",
            "ok": debt <= float(t["debt_max"]),
            "current": debt,
            "target": f"<= {t['debt_max']}%",
            "next": "Work the Act playbook — owners, drafts, and unlinked pages.",
            "cta": "playbook",
        },
        {
            "id": "contradictions",
            "title": "Contradictions",
            "ok": contradictions <= int(t["contradictions_max"]),
            "current": contradictions,
            "target": f"<= {t['contradictions_max']}",
            "next": "Scan conflicts, then accept or reject each pair in Govern.",
            "cta": "scan_conflicts",
        },
    ]
    failed = [c for c in playbook if not c["ok"]]
    # Show-stoppers first: contradictions, then debt, then coverage.
    order = {"contradictions": 0, "debt": 1, "coverage": 2}
    failed.sort(key=lambda c: order.get(str(c["id"]), 9))
    lead = failed[0] if failed else None
    return {
        "passing": not failed,
        "checks": playbook,
        "targets": t,
        "failed_ids": [c["id"] for c in failed],
        "next": (lead or {}).get("next"),
        "cta": (lead or {}).get("cta"),
    }


def goal_progress(current: dict[str, float], goals: dict[str, Any]) -> dict[str, Any]:
    td = goals.get("target_debt")
    tc = goals.get("target_coverage")
    out: dict[str, Any] = {"targets": goals}
    if td is not None:
        cur = float(current.get("debt") or 0)
        out["debt"] = {
            "current": cur,
            "target": float(td),
            "gap": round(max(0.0, cur - float(td)), 1),
        }
    if tc is not None:
        cur = float(current.get("coverage") or 0)
        out["coverage"] = {
            "current": cur,
            "target": float(tc),
            "gap": round(max(0.0, float(tc) - cur), 1),
        }
    return out


def simulate_playbook(debt: dict[str, Any], recs: list[dict[str, Any]]) -> dict[str, Any]:
    pb = debt.get("playbook") or {}
    cov_gain = sum(float(r.get("expected_coverage_gain") or 0) for r in recs[:3])
    return {
        "if_playbook_done": {
            "debt": pb.get("expected_debt_after_fix"),
            "debt_now": pb.get("current_debt"),
        },
        "if_top_gaps_linked": {
            "expected_coverage_gain": round(cov_gain, 1),
            "sections": [r.get("section") for r in recs[:3]],
        },
        "if_source_removed": {
            "note": "Removing a source is not simulated as a graph clone; snapshot + rollback weights instead.",
        },
    }


def change_feed(versions: list[dict[str, Any]], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feed: list[dict[str, Any]] = []
    for v in versions:
        feed.append(
            {
                "at": v.get("created_at"),
                "kind": "version",
                "title": v.get("label"),
                "detail": (v.get("vs_previous") or {}).get("summary") or v.get("status"),
            }
        )
    for a in actions:
        feed.append(
            {
                "at": a.get("completed_at") or a.get("created_at"),
                "kind": "action",
                "title": a.get("driver"),
                "detail": a.get("label") or a.get("status"),
            }
        )
    feed.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    return feed[:20]


def attribution(versions: list[dict[str, Any]], by_driver: dict[str, int]) -> list[dict[str, Any]]:
    """Why quality moved — from diffs + completed operator actions."""
    out: list[dict[str, Any]] = []
    for v in versions:
        d = v.get("vs_previous") or {}
        if d.get("summary") and d["summary"] != "No material change":
            out.append({"source": "diff", "detail": d["summary"], "at": v.get("created_at")})
    labels = {
        "topics": "Topic linking",
        "coverage": "Coverage work",
        "conflicts": "Contradiction resolution",
        "weak_edges": "Weak-edge review",
        "unanswered": "Draft acceptance",
        "trust": "Source review",
    }
    for k, n in sorted(by_driver.items(), key=lambda x: -x[1]):
        out.append({"source": "operator", "detail": f"{labels.get(k, k)} ×{n}", "at": None})
    return out[:12]


def learning_efficiency(*, accepted_drafts: int, fitness_delta: float | None) -> dict[str, Any]:
    return {
        "accepted_drafts": accepted_drafts,
        "fitness_delta": fitness_delta,
        "note": "Pair accepted drafts with Trust Forge fitness across snapshots.",
    }


def explain(proof: dict[str, Any], debt: dict[str, Any], sla: dict[str, Any]) -> str:
    risk = (debt.get("risk") or {}).get("level") or "n/a"
    score = debt.get("score")
    b = proof.get("before") or {}
    a = proof.get("after") or {}
    if sla.get("passing"):
        sla_s = "Pack SLA is passing (coverage, debt, contradictions)."
    else:
        missed = ", ".join(str(x) for x in (sla.get("failed_ids") or [])) or "checks"
        sla_s = f"Pack SLA miss ({missed}). {sla.get('next') or 'Open the failed check.'}"
    parts = [
        f"This workspace is {risk} risk with knowledge debt {score}%.",
        f"Debt moved {b.get('debt')}% → {a.get('debt')}%; coverage {b.get('coverage')}% → {a.get('coverage')}%.",
        sla_s,
    ]
    acts = (debt.get("playbook") or {}).get("actions") or []
    if acts:
        parts.append("Next: " + "; ".join(str(x.get("do")) for x in acts[:3]) + ".")
    return " ".join(str(p) for p in parts if p)


def domain_confidence(cover: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for d in cover.get("domains") or []:
        pct = float(d.get("coverage_pct") or 0)
        out.append(
            {
                "domain": d.get("section"),
                "confidence": pct,
                "criticality": criticality_for(str(d.get("section") or "")),
                "pages": d.get("pages"),
            }
        )
    return out


def list_benchmarks() -> list[dict[str, Any]]:
    from app.trust_forge.eval import golden_roots

    out = []
    seen: set[str] = set()
    for root in golden_roots():
        for path in root.rglob("*.json"):
            if path.name.startswith("_"):
                continue
            stem = path.stem.lower()
            if stem.endswith("_coverage") or stem.endswith("_kb_pages") or stem.endswith("_pages"):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            cases = data.get("cases") or []
            if not cases:
                continue
            st = path.stat()
            out.append(
                {
                    "id": data.get("suite_id") or path.stem,
                    "name": data.get("agent_name") or path.stem,
                    "path": str(path),
                    "cases": len(cases),
                    "updated": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                    "protected": True,
                }
            )
    out.sort(key=lambda x: -int(x["cases"]))
    return out[:24]


def impact_aware_debt(drivers: list[dict[str, Any]], recs: list[dict[str, Any]]) -> dict[str, Any]:
    high = 0.0
    low = 0.0
    crit_sections = {r["section"] for r in recs if r.get("criticality") == "Critical"}
    for d in drivers:
        pts = float(d.get("points") or 0)
        did = str(d.get("id") or "")
        if did in {"conflicts", "trust"} or (did in {"topics", "coverage"} and crit_sections):
            high += pts
        else:
            low += pts
    return {
        "high_impact": round(high, 1),
        "low_impact": round(low, 1),
        "total": round(high + low, 1),
    }


def source_rows(
    docs: list[dict[str, Any]],
    gov: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for d in docs:
        title = str(d.get("title") or "")
        tw = trust_weight(title)
        gid = str(d.get("id") or "")
        g = gov.get(gid) or {}
        created = d.get("created_at")
        age = _age_days(g.get("reviewed_at") or created)
        rows.append(
            {
                "id": gid,
                "title": title[:160],
                "trust_pct": round(100.0 * tw, 0),
                "owner": g.get("owner") or ("Compliance" if criticality_for(title) == "Critical" else "Knowledge"),
                "reviewer": g.get("reviewer") or "",
                "reviewed_at": g.get("reviewed_at"),
                "age_days": age,
                "freshness": "stale" if (age or 0) > 180 else "ok",
                "criticality": criticality_for(title),
            }
        )
    rows.sort(key=lambda r: (0 if r["freshness"] == "stale" else 1, r["trust_pct"]))
    return rows[:20]


def scale_card(*, nodes: int, edges: int, docs: int, snapshot_ms: float) -> dict[str, Any]:
    return {
        "nodes": nodes,
        "edges": edges,
        "documents": docs,
        "snapshot_ms": round(snapshot_ms, 1),
        "note": "Counts for this workspace. 1M+ entity load tests are a later ops exercise, not a product feature.",
    }


async def load_source_gov(workspace_id: str) -> dict[str, dict[str, Any]]:
    from app.db import get_connection

    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT document_id, owner, reviewer, reviewed_at FROM knowledge_source_gov
               WHERE workspace_id = ?""",
            (workspace_id,),
        )
        return {
            str(r["document_id"]): dict(r)
            for r in await cur.fetchall()
        }
    except Exception:  # noqa: BLE001
        return {}
    finally:
        await conn.close()


async def upsert_source_gov(
    workspace_id: str,
    document_id: str,
    *,
    owner: str = "",
    reviewer: str = "",
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    now = reviewed_at or _now()
    from app.db import get_connection

    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO knowledge_source_gov (
                workspace_id, document_id, owner, reviewer, reviewed_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, document_id) DO UPDATE SET
                owner = excluded.owner,
                reviewer = excluded.reviewer,
                reviewed_at = excluded.reviewed_at""",
            (workspace_id, document_id, owner[:80], reviewer[:80], now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"ok": True, "document_id": document_id, "owner": owner, "reviewed_at": now}


async def load_goals(workspace_id: str) -> dict[str, Any]:
    from app.db import get_connection

    conn = await get_connection()
    try:
        cur = await conn.execute(
            "SELECT target_debt, target_coverage FROM knowledge_goals WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"target_debt": 10.0, "target_coverage": 90.0}
        return {
            "target_debt": float(row["target_debt"] or 10),
            "target_coverage": float(row["target_coverage"] or 90),
        }
    except Exception:  # noqa: BLE001
        return {"target_debt": 10.0, "target_coverage": 90.0}
    finally:
        await conn.close()


async def save_goals(workspace_id: str, *, target_debt: float, target_coverage: float) -> dict[str, Any]:
    from app.db import get_connection

    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO knowledge_goals (workspace_id, target_debt, target_coverage, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(workspace_id) DO UPDATE SET
                 target_debt = excluded.target_debt,
                 target_coverage = excluded.target_coverage,
                 updated_at = excluded.updated_at""",
            (workspace_id, float(target_debt), float(target_coverage), _now()),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"target_debt": target_debt, "target_coverage": target_coverage}


async def list_done_actions(workspace_id: str) -> list[dict[str, Any]]:
    from app.db import get_connection

    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT driver, label, status, created_at, completed_at
               FROM knowledge_ops_actions WHERE workspace_id = ?
               ORDER BY created_at DESC LIMIT 30""",
            (workspace_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        await conn.close()
