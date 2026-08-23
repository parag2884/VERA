"""Thin CLI wrapper → app.trust_forge.cli"""

from __future__ import annotations

import asyncio
import sys

from app.trust_forge.cli import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
