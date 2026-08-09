"""CI harness: Ask readiness for known workspaces.

Exit 1 when any evaluated workspace is not ready.
Run inside vera-api:  python /app/scripts/ask_readiness_ci.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.runtime import get_runtime
from app.services.ask_readiness import evaluate_workspace_readiness
from app.stores.sql import WorkspaceStore

# Optional hard-coded IDs for local CI; skipped when workspace has no docs.
PLAYREADY_WS = "31509630-c427-40c4-b182-e1f63fe8c91b"
KFORCE_WS = "cb89a5e6-20a0-4aaf-b093-c2339b1c7ce3"

OUT_CANDIDATES = [
    Path("/app/data/ask_readiness_ci.json"),
    Path(__file__).resolve().parents[1] / "data" / "ask_readiness_ci.json",
]


async def main() -> int:
    runtime = get_runtime()
    reports: dict = {}
    ok_all = True
    async with WorkspaceStore() as store:
        for name, ws in (("PlayReady", PLAYREADY_WS), ("KFORCE", KFORCE_WS)):
            docs = await store.list_canonical_documents(ws)
            if not docs:
                reports[name] = {"status": "skip", "reason": "no documents"}
                continue
            report = await evaluate_workspace_readiness(
                runtime, store, ws, run_live_asks=True
            )
            reports[name] = report
            if report.get("status") != "ready":
                ok_all = False
            health = await store.get_health(ws) or {}
            components = dict(health.get("components") or {})
            components["ask_readiness"] = report
            await store.save_health(ws, float(health.get("score") or 0), components)

    out = next((p for p in OUT_CANDIDATES if p.parent.exists()), OUT_CANDIDATES[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    summary = {
        k: {"status": v.get("status"), "pass_rate": v.get("pass_rate")}
        for k, v in reports.items()
        if isinstance(v, dict)
    }
    print(json.dumps(summary, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
