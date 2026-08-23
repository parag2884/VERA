"""Version diffs and debt trend — no I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def diff_payloads(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    """What changed between two version payloads (CTO change-diff)."""
    om = older.get("metrics") if isinstance(older.get("metrics"), dict) else {}
    nm = newer.get("metrics") if isinstance(newer.get("metrics"), dict) else {}

    def _delta(key: str) -> float | None:
        if key not in om and key not in nm:
            return None
        try:
            return round(float(nm.get(key) or 0) - float(om.get(key) or 0), 2)
        except (TypeError, ValueError):
            return None

    old_w = {
        str(e.get("id")): float(e.get("weight") or 1)
        for e in (older.get("edges") or [])
        if e.get("id")
    }
    new_w = {
        str(e.get("id")): float(e.get("weight") or 1)
        for e in (newer.get("edges") or [])
        if e.get("id")
    }
    strengthened = 0
    weakened = 0
    for eid, nw in new_w.items():
        ow = old_w.get(eid)
        if ow is None:
            continue
        if nw - ow >= 0.02:
            strengthened += 1
        elif ow - nw >= 0.02:
            weakened += 1
    added_edges = len(set(new_w) - set(old_w))
    removed_edges = len(set(old_w) - set(new_w))
    lines: list[str] = []
    cov = _delta("coverage")
    if cov is not None:
        lines.append(f"Coverage {cov:+g}%")
    debt = _delta("debt")
    if debt is not None:
        lines.append(f"Debt {debt:+g}%")
    fit = _delta("fitness")
    if fit is not None:
        lines.append(f"Fitness {fit:+g}%")
    if strengthened:
        lines.append(f"{strengthened} edges strengthened")
    if weakened:
        lines.append(f"{weakened} edges weakened")
    cd = _delta("contradictions")
    if cd:
        verb = "resolved" if cd < 0 else "added"
        lines.append(f"{abs(int(cd))} contradictions {verb}")
    td = _delta("topic_nodes")
    if td:
        lines.append(f"{int(td):+d} topic nodes")
    if added_edges:
        lines.append(f"{added_edges} new edges")
    if removed_edges:
        lines.append(f"{removed_edges} edges removed")
    return {
        "coverage_delta": cov,
        "debt_delta": debt,
        "fitness_delta": fit,
        "edges_strengthened": strengthened,
        "edges_weakened": weakened,
        "edges_added": added_edges,
        "edges_removed": removed_edges,
        "contradictions_delta": cd,
        "topic_nodes_delta": td,
        "summary": " · ".join(x for x in lines if x) or "No material change",
    }


def debt_trend(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Leadership view: current debt vs prior (≈ last month or previous snapshot)."""
    series: list[tuple[str, float]] = []
    for p in points:
        d = p.get("debt")
        if d is None:
            continue
        try:
            series.append((str(p.get("created_at") or ""), float(d)))
        except (TypeError, ValueError):
            continue
    if not series:
        return {"current": None, "prior": None, "delta": None, "label": "No history yet"}
    current_at, current = series[-1]
    if len(series) < 2:
        return {
            "current": current,
            "prior": None,
            "delta": None,
            "prior_at": None,
            "current_at": current_at,
            "label": "Need another snapshot",
        }
    prior_at, prior = series[-2]
    for ts, val in reversed(series[:-1]):
        if _days_apart(ts, current_at) >= 20:
            prior_at, prior = ts, val
            break
    delta = round(current - prior, 1)
    if abs(delta) < 0.3:
        label = "Stable"
    elif delta < 0:
        label = "Improving"
    else:
        label = "Deteriorating"
    return {
        "current": current,
        "prior": prior,
        "delta": delta,
        "prior_at": prior_at,
        "current_at": current_at,
        "label": label,
    }


def _days_apart(a: str, b: str) -> float:
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return abs((db - da).total_seconds()) / 86400.0
    except Exception:  # noqa: BLE001
        return 0.0
