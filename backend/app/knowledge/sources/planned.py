"""Roadmap connectors — real module slots, not fake ingest.

Each kind can later grow into ``sources/<kind>/`` without changing Ask or the
shared pipeline. Until then, status is ``planned``.

Email & calendar is knowledge for Ask (briefs, important mail, meetings) — not
separate send-mail / post-to-Teams action tiles.
"""

from __future__ import annotations

from typing import Any

from app.knowledge.base import SourceNotConfiguredError
from app.knowledge.contracts import SourceAcquireResult, SourceKind


class PlannedConnector:
    """Stub SourceConnector reserved for a realistic future integration."""

    def __init__(
        self,
        kind: SourceKind,
        *,
        title: str,
        blurb: str,
        setup_hint: str,
        graph_scopes: list[str] | None = None,
    ) -> None:
        self.kind = kind
        self.title = title
        self.blurb = blurb
        self.setup_hint = setup_hint
        self.graph_scopes = graph_scopes or []

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        raise SourceNotConfiguredError(
            self.kind,
            f"{self.title} is reserved but not implemented yet.",
            setup_hint=self.setup_hint,
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "state": "planned",
            "title": self.title,
            "blurb": self.blurb,
            "category": "knowledge",
            "setup_hint": self.setup_hint,
            "graph_scopes": self.graph_scopes,
            "note": "Module slot reserved — same AcquiredFile → ingest pipeline when built.",
        }


ROADMAP_CONNECTORS: list[PlannedConnector] = [
    PlannedConnector(
        "outlook",
        title="Email & calendar",
        blurb="Ask about important mail, meetings, summaries",
        setup_hint="Microsoft Graph Mail.Read + Calendars.Read (delegated) + user consent.",
        graph_scopes=["Mail.Read", "Calendars.Read"],
    ),
    PlannedConnector(
        "onedrive",
        title="OneDrive",
        blurb="Personal / work files",
        setup_hint="Microsoft Graph Files.Read.All (delegated) + user consent.",
        graph_scopes=["Files.Read.All"],
    ),
    PlannedConnector(
        "teams",
        title="Microsoft Teams",
        blurb="Channel posts & files",
        setup_hint="Graph ChannelMessage.Read.All / Files.Read.All as appropriate.",
        graph_scopes=["ChannelMessage.Read.All", "Files.Read.All"],
    ),
    PlannedConnector(
        "onelake",
        title="OneLake / Fabric",
        blurb="Lakehouse files",
        setup_hint="Fabric OneLake / ADLS Gen2 credentials or workspace identity.",
    ),
    PlannedConnector(
        "azure_sql",
        title="Azure SQL",
        blurb="Structured facts tables",
        setup_hint="SQL connection string + allowlisted views (no raw PII dumps).",
    ),
    PlannedConnector(
        "confluence",
        title="Confluence",
        blurb="Wiki spaces",
        setup_hint="Atlassian Cloud API token + space keys.",
    ),
    PlannedConnector(
        "gdrive",
        title="Google Drive",
        blurb="Shared drives & Docs",
        setup_hint="Google OAuth Drive readonly scope.",
    ),
]
