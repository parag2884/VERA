"""SharePoint SourceConnector wrapper."""

from __future__ import annotations

from typing import Any

from app.knowledge.contracts import SourceAcquireResult
from app.knowledge.sources.sharepoint.client import fetch_sharepoint, graph_configured


class SharePointConnector:
    kind = "sharepoint"

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        files = await fetch_sharepoint(kwargs.get("url"), demo=bool(kwargs.get("demo")))
        return SourceAcquireResult(
            kind="sharepoint",
            files=files,
            meta={"demo": bool(kwargs.get("demo")), "count": len(files)},
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "state": "configured" if graph_configured() else "demo_available",
            "graph_configured": graph_configured(),
            "demo_available": True,
            "recursive_folders": True,
        }
