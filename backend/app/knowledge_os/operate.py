"""Thin Operate board: outcomes, not a metric dump. Detect / recommend only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def health_label(*, debt: float, sla_ok: bool, risk: str) -> str:
    if not sla_ok or (risk or "").lower() == "high" or debt >= 28:
        return "Action"
    if debt >= 12 or (risk or "").lower() == "medium":
        return "Watch"
    return "Good"


def drift_flags(points: list[dict[str, Any]], current: dict[str, float]) -> list[dict[str, Any]]:
    """Flag movement vs ~7d-ago snapshot. No auto-fix."""
    if not points:
        return []
    prior = points[0]
    if len(points) >= 2:
        prior = points[0]
    flags: list[dict[str, Any]] = []
    mapping = [
        ("debt", "Debt", 3.0, True),
        ("coverage", "Coverage", 5.0, False),
        ("trust", "Trust", 5.0, False),
        ("contradictions", "Contradictions", 2.0, True),
        ("refusals", "Refusals", 3.0, True),
    ]
    for key, label, thresh, up_is_bad in mapping:
        try:
            now = float(current.get(key) if current.get(key) is not None else 0)
            then = float(prior.get(key) if prior.get(key) is not None else now)
        except (TypeError, ValueError):
            continue
        delta = round(now - then, 1)
        bad = (delta >= thresh) if up_is_bad else (delta <= -thresh)
        if not bad:
            continue
        flags.append(
            {
                "metric": label,
                "from": then,
                "to": now,
                "delta": delta,
                "note": f"{label} {then} → {now}. Flag only — autopilot will not change policy.",
            }
        )
    return flags


def changes_since(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    def _f(d: dict[str, Any], k: str) -> float | None:
        v = d.get(k)
        if v is None:
            return None
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    db, da = _f(before, "debt"), _f(after, "debt")
    if db is not None and da is not None and da != db:
        lines.append(f"Debt {db}% → {da}%")
    cb, ca = _f(before, "coverage"), _f(after, "coverage")
    if cb is not None and ca is not None and ca != cb:
        sign = "+" if ca - cb > 0 else ""
        lines.append(f"Coverage {sign}{round(ca - cb, 1)}%")
    tb, ta = _f(before, "contradictions"), _f(after, "contradictions")
    if tb is not None and ta is not None and ta != tb:
        dlt = round(ta - tb, 0)
        if dlt < 0:
            lines.append(f"{int(abs(dlt))} contradictions resolved")
        else:
            lines.append(f"+{int(dlt)} contradictions")
    return lines[:6]


def recommended_today(playbook: dict[str, Any] | None, recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current = float((playbook or {}).get("current_debt") or 0)
    for a in (playbook or {}).get("actions") or []:
        after = float(a.get("expected_debt_after_this") or current)
        out.append(
            {
                "title": a.get("do") or a.get("cause"),
                "expected_debt_delta": round(after - current, 1),
                "driver": a.get("driver"),
                "policy": str(a.get("driver") or "") == "unanswered",
            }
        )
        current = after
    for r in recs[:2]:
        title = r.get("suggested") or r.get("section")
        if not title:
            continue
        if any(title == x.get("title") for x in out):
            continue
        out.append(
            {
                "title": f"Link {title}",
                "expected_debt_delta": None,
                "coverage_gain": r.get("expected_coverage_gain"),
                "driver": "coverage",
                "policy": False,
            }
        )
    # Drafts stay recommendations that require a human — never auto
    return out[:5]


def source_delta(previous_urls: list[str], current_urls: list[str]) -> dict[str, Any]:
    prev, cur = set(previous_urls or []), set(current_urls or [])
    gone = sorted(prev - cur)[:20]
    added = sorted(cur - prev)[:20]
    return {
        "disappeared": gone,
        "added": added,
        "disappeared_count": len(prev - cur),
        "added_count": len(cur - prev),
    }


def weekly_summary(
    points: list[dict[str, Any]],
    current: dict[str, Any],
    *,
    risk: str,
) -> dict[str, Any] | None:
    """Leadership evidence, not a daily dashboard. Needs at least two snapshots."""
    if len(points) < 1:
        return None

    def _n(d: dict[str, Any], k: str) -> float | None:
        v = d.get(k)
        if v is None:
            return None
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    then = points[0]
    cov = _n(current, "coverage")
    cov0 = _n(then, "coverage")
    debt = _n(current, "debt")
    debt0 = _n(then, "debt")
    trust = _n(current, "trust")
    trust0 = _n(then, "trust")
    contra = _n(current, "contradictions")
    contra0 = _n(then, "contradictions")
    lines: list[str] = []
    if cov is not None and cov0 is not None:
        d = round(cov - cov0, 1)
        if d:
            lines.append(f"Coverage: {'+' if d > 0 else ''}{d}%")
    if debt is not None and debt0 is not None:
        d = round(debt - debt0, 1)
        if d:
            lines.append(f"Debt: {'+' if d > 0 else ''}{d}%")
    if trust is not None and trust0 is not None:
        d = round(trust - trust0, 1)
        if d:
            lines.append(f"Trust: {'+' if d > 0 else ''}{d}%")
    if contra is not None and contra0 is not None:
        d = int(round(contra - contra0))
        if d < 0:
            lines.append(f"{abs(d)} contradictions resolved")
        elif d > 0:
            lines.append(f"+{d} contradictions")
    if not lines:
        return None
    return {
        "lines": lines,
        "risk": risk,
        "text": " · ".join(lines) + f" · Risk: {risk}",
    }


def in_maintenance_window(
    *,
    hour_utc: int,
    start_hour: int,
    duration_hours: int,
) -> bool:
    if duration_hours <= 0:
        return False
    end = (start_hour + duration_hours) % 24
    if start_hour < end:
        return start_hour <= hour_utc < end
    return hour_utc >= start_hour or hour_utc < end


def board(
    *,
    debt: dict[str, Any],
    sla: dict[str, Any],
    playbook: dict[str, Any] | None,
    recs: list[dict[str, Any]],
    points: list[dict[str, Any]],
    hygiene: dict[str, Any],
    sources: dict[str, Any] | None,
    window: bool,
    busy: str | None,
) -> dict[str, Any]:
    score = float(debt.get("score") or 0)
    risk = str((debt.get("risk") or {}).get("level") or "Low")
    sla_ok = bool(sla.get("passing"))
    label = health_label(debt=score, sla_ok=sla_ok, risk=risk)
    prior = points[0] if points else {}
    now = {
        "debt": score,
        "coverage": float(debt.get("coverage_pct") or 0),
        "trust": float(debt.get("trust_pct") or 0),
        "contradictions": 0.0,
        "refusals": 0.0,
    }
    for c in sla.get("checks") or []:
        if c.get("id") == "contradictions":
            try:
                now["contradictions"] = float(c.get("current") or 0)
            except (TypeError, ValueError):
                now["contradictions"] = 0.0

    recs_today = recommended_today(playbook, recs)
    human = label == "Action" or any(
        str(a.get("driver")) in {"unanswered", "trust"} for a in recs_today
    )
    return {
        "status": label,
        "risk": risk,
        "debt": score,
        "coverage": now["coverage"],
        "trust": now["trust"],
        "changes": changes_since(prior, now),
        "drift": drift_flags(points, now),
        "recommended": recs_today,
        "hygiene": hygiene.get("counts") or {},
        "sources": sources or {"disappeared_count": 0, "added_count": 0},
        "maintenance_window": window,
        "busy": busy,
        "human_needed": human,
        "week": weekly_summary(list(points), now, risk=risk),
        "guardrail": (
            "Care can detect, suggest, and maintain. "
            "Care cannot govern (drafts, versions, locks, new knowledge, hierarchy)."
        ),
        "actions_needed": 0 if label == "Good" else min(3, len(recs_today)),
        "quiet": label == "Good" and not human,
    }


def utc_hour() -> int:
    return datetime.now(timezone.utc).hour
