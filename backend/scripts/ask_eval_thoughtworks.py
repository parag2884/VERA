"""Convenience entrypoint for the Thoughtworks web golden suite.

Delegates to ask_eval_golden.py with tests/golden/web/thoughtworks_v2.json.

Usage (inside vera-api):
  python /app/scripts/ask_eval_thoughtworks.py
  python /app/scripts/ask_eval_thoughtworks.py --ids TW01,TW14
  python /app/scripts/ask_eval_thoughtworks.py --agent "Thoughtworks Assistant"
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SUITE_CANDIDATES = [
    Path("/app/tests/golden/web/thoughtworks_v2.json"),
    Path(__file__).resolve().parents[1] / "tests" / "golden" / "web" / "thoughtworks_v2.json",
]


def _suite() -> Path:
    for p in SUITE_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "thoughtworks_v2.json not found under tests/golden/web/. "
        "Mount or rebuild so /app/tests/golden is present."
    )


if __name__ == "__main__":
    suite = _suite()
    # Preserve caller flags (--agent, --ids) after injecting --suite.
    argv = [sys.argv[0], "--suite", str(suite), *sys.argv[1:]]
    sys.argv = argv
    runpy.run_path(str(Path(__file__).with_name("ask_eval_golden.py")), run_name="__main__")
