"""Proof: operator action → knowledge improvement (adoption + ROI report)."""

from __future__ import annotations

from typing import Any


def build_ops_report(
    *,
    points: list[dict[str, Any]],
    current: dict[str, Any],
    versions: list[dict[str, Any]],
    suggested: int,
    completed: int,
    by_driver: dict[str, int],
    remaining: list[str],
) -> dict[str, Any]:
    """Monthly-style KnowledgeOps report from snapshots + adoption counts."""
    series = [p for p in points if p.get("debt") is not None or p.get("coverage") is not None]
    before = series[0] if series else {}
    after = {**current}
    if series:
        after = {**series[-1], **current}

    def _n(d: dict[str, Any], key: str) -> float | None:
        v = d.get(key)
        if v is None:
            return None
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    debt_b, debt_a = _n(before, "debt"), _n(after, "debt")
    cov_b, cov_a = _n(before, "coverage"), _n(after, "coverage")
    trust_b, trust_a = _n(before, "trust"), _n(after, "trust")
    risk_b = before.get("risk") or before.get("risk_level")
    risk_a = after.get("risk") or current.get("risk")

    improvements: list[str] = []
    if debt_b is not None and debt_a is not None and debt_a < debt_b:
        improvements.append(f"Debt {debt_b:g}% → {debt_a:g}%")
    if cov_b is not None and cov_a is not None and cov_a > cov_b:
        improvements.append(f"Coverage {cov_b:g}% → {cov_a:g}%")
    if trust_b is not None and trust_a is not None and trust_a > trust_b:
        improvements.append(f"Trust {trust_b:g}% → {trust_a:g}%")
    for v in versions[:6]:
        s = (v.get("vs_previous") or {}).get("summary")
        if s and s != "No material change":
            improvements.append(str(s))

    gains = [
        {"driver": k, "actions_completed": n}
        for k, n in sorted(by_driver.items(), key=lambda x: -x[1])
        if n
    ]
    return {
        "title": "KnowledgeOps report",
        "before": {
            "debt": debt_b,
            "coverage": cov_b,
            "trust": trust_b,
            "risk": risk_b,
            "at": before.get("created_at"),
        },
        "after": {
            "debt": debt_a,
            "coverage": cov_a,
            "trust": trust_a,
            "risk": risk_a,
            "at": after.get("created_at"),
        },
        "adoption": {
            "suggested": suggested,
            "completed": completed,
            "rate": round(completed / suggested, 3) if suggested else None,
            "by_driver": gains,
        },
        "improvements": improvements[:8],
        "remaining": remaining[:6],
        "has_history": len(series) >= 2 or (debt_b is not None and debt_a is not None and debt_b != debt_a),
    }


async def suggest_actions(workspace_id: str, playbook: dict[str, Any], *, debt: float) -> None:
    from uuid import uuid4

    from app.db import get_connection
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn = await get_connection()
    try:
        for a in playbook.get("actions") or []:
            driver = str(a.get("driver") or "")
            if not driver:
                continue
            cur = await conn.execute(
                """SELECT id FROM knowledge_ops_actions
                   WHERE workspace_id = ? AND driver = ? AND status = 'open' LIMIT 1""",
                (workspace_id, driver),
            )
            if await cur.fetchone():
                continue
            await conn.execute(
                """INSERT INTO knowledge_ops_actions (
                    id, workspace_id, driver, label, status, debt_at, created_at, completed_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?, '')""",
                (
                    str(uuid4()),
                    workspace_id,
                    driver,
                    str(a.get("do") or a.get("cause") or "")[:200],
                    str(debt),
                    now,
                ),
            )
        await conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        await conn.close()


async def complete_action(workspace_id: str, driver: str, *, debt: float) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.db import get_connection

    now = datetime.now(timezone.utc).isoformat()
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT id FROM knowledge_ops_actions
               WHERE workspace_id = ? AND driver = ? AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (workspace_id, driver),
        )
        row = await cur.fetchone()
        if row:
            await conn.execute(
                """UPDATE knowledge_ops_actions
                   SET status = 'done', completed_at = ?, debt_at = ?
                   WHERE id = ?""",
                (now, str(debt), row["id"]),
            )
        else:
            from uuid import uuid4

            await conn.execute(
                """INSERT INTO knowledge_ops_actions (
                    id, workspace_id, driver, label, status, debt_at, created_at, completed_at
                ) VALUES (?, ?, ?, ?, 'done', ?, ?, ?)""",
                (str(uuid4()), workspace_id, driver, driver, str(debt), now, now),
            )
        await conn.commit()
    except Exception:  # noqa: BLE001
        return {"ok": False}
    finally:
        await conn.close()
    return {"ok": True, "driver": driver}


async def action_stats(workspace_id: str) -> dict[str, Any]:
    from app.db import get_connection

    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT driver, status, COUNT(*) AS c FROM knowledge_ops_actions
               WHERE workspace_id = ? GROUP BY driver, status""",
            (workspace_id,),
        )
        suggested = completed = 0
        by_driver: dict[str, int] = {}
        for r in await cur.fetchall():
            n = int(r["c"] or 0)
            suggested += n
            if str(r["status"]) == "done":
                completed += n
                by_driver[str(r["driver"])] = by_driver.get(str(r["driver"]), 0) + n
        return {
            "suggested": suggested,
            "completed": completed,
            "by_driver": by_driver,
        }
    except Exception:  # noqa: BLE001
        return {"suggested": 0, "completed": 0, "by_driver": {}}
    finally:
        await conn.close()
