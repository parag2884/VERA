"""CLI entry for Trust Forge.

Usage (inside vera-api):
  python -m app.trust_forge.cli --agent "PlayReady" --threshold 95 --poll
  python /app/scripts/trust_forge_run.py --agent "PlayReady" --poll
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.stores.sql import WorkspaceStore
from app.trust_forge import service as forge
from app.trust_forge.eval import resolve_agent


async def main() -> int:
    parser = argparse.ArgumentParser(description="Trust Forge — climb golden fitness")
    parser.add_argument("--workspace", default="", help="Workspace id")
    parser.add_argument("--agent", default="", help="Agent name (resolves workspace)")
    parser.add_argument("--agent-id", default="", help="Agent id")
    parser.add_argument(
        "--suite",
        default="",
        help="Golden suite path or relative under tests/golden",
    )
    parser.add_argument("--threshold", type=float, default=95.0)
    parser.add_argument("--max-generations", type=int, default=8)
    parser.add_argument("--stall-generations", type=int, default=3)
    parser.add_argument("--poll", action="store_true", help="Poll until complete")
    args = parser.parse_args()

    workspace_id = args.workspace.strip()
    agent_id = args.agent_id.strip() or None

    if args.agent.strip():
        resolved_id, resolved_ws = await resolve_agent(args.agent.strip())
        agent_id = agent_id or resolved_id
        workspace_id = workspace_id or resolved_ws
    elif not workspace_id:
        raise SystemExit("Provide --workspace and/or --agent")

    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise SystemExit(f"Workspace not found: {workspace_id}")

    run = await forge.start_run(
        workspace_id,
        agent_id=agent_id,
        suite_path=args.suite.strip() or None,
        threshold=args.threshold,
        max_generations=args.max_generations,
        stall_generations=args.stall_generations,
    )
    print(
        json.dumps(
            {
                k: run[k]
                for k in ("id", "status", "threshold", "suite_path", "workspace_id")
            },
            indent=2,
        )
    )

    if not args.poll:
        print(
            "Started. Poll with GET .../trust-forge/runs/{id} or re-run with --poll",
            flush=True,
        )
        return 0

    run_id = run["id"]
    while True:
        cur = await forge.get_run(workspace_id, run_id)
        if not cur:
            print("run disappeared", file=sys.stderr)
            return 1
        curve = cur.get("fitness_curve") or []
        print(
            f"status={cur['status']} gen={cur['generation']} "
            f"best={cur['best_fitness']} curve={curve} reason={cur.get('stop_reason')}",
            flush=True,
        )
        if cur["status"] in {"completed", "failed", "stopped"}:
            print(json.dumps(cur, indent=2)[:4000])
            return 0 if cur["status"] == "completed" else 1
        await asyncio.sleep(2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
