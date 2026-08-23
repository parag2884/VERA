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
from pathlib import Path

from app.trust_forge.eval import (
    eval_suite,
    find_suite_for_agent,
    golden_roots,
    load_suite,
    resolve_agent,
    resolve_suite_path,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run KB-grounded Ask golden suites")
    parser.add_argument("--suite", default="", help="Path to suite JSON")
    parser.add_argument("--agent", default=None, help="Agent name (required for refuse suites)")
    parser.add_argument("--ids", default="", help="Comma-separated case ids")
    args = parser.parse_args()

    suite_path: Path | None = None
    if args.suite.strip():
        suite_path = resolve_suite_path(args.suite.strip())
    elif args.agent:
        suite_path = find_suite_for_agent(args.agent)
        if not suite_path:
            raise FileNotFoundError(
                f"No suite with agent_name={args.agent!r} under tests/golden/"
            )
    else:
        raise SystemExit("Provide --suite and/or --agent")

    golden = load_suite(suite_path)
    agent_name = args.agent or golden.get("agent_name")
    if not agent_name:
        raise SystemExit("Suite has no agent_name; pass --agent")

    agent_id, workspace_id = await resolve_agent(agent_name)
    case_ids = None
    if args.ids.strip():
        case_ids = {x.strip() for x in args.ids.split(",") if x.strip()}

    print(
        f"suite={golden.get('suite_id')} kind={golden.get('source_kind')} "
        f"file={suite_path}\n"
        f"Running cases on agent={agent_name!r} "
        f"id={agent_id} workspace={workspace_id}",
        flush=True,
    )
    summary = await eval_suite(workspace_id, golden, case_ids=case_ids)
    for row in summary.get("results") or []:
        status = "PASS" if row["pass"] else "FAIL"
        src = row.get("source_url") or row.get("source_document") or ""
        print(
            f"  {status} {row['id']} decision={row['decision']} {row['elapsed_s']}s | "
            f"{(row.get('answer_preview') or '')[:90]}",
            flush=True,
        )
        if src:
            print(f"    verify↔ {src}", flush=True)

    suite_id = summary.get("suite_id") or suite_path.stem
    out_payload = {
        **summary,
        "agent_name": agent_name,
        "agent_id": agent_id,
        "pass_rate": summary["pass_rate"],
    }
    out_candidates = [
        Path(f"/app/data/ask_eval_{suite_id}_results.json"),
        Path(__file__).resolve().parent / f"ask_eval_{suite_id}_results.json",
    ]
    out = next((p for p in out_candidates if p.parent.exists()), out_candidates[-1])
    out.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: out_payload[k]
                for k in (
                    "passed",
                    "total",
                    "fitness",
                    "pass_rate",
                    "fail_taxonomy",
                    "fail_ids",
                    "suite_id",
                    "source_kind",
                )
                if k in out_payload
            },
            indent=2,
        )
    )
    print(f"wrote {out}", flush=True)
    roots = golden_roots()
    if not roots:
        print("warning: no golden roots found on disk", flush=True)
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
