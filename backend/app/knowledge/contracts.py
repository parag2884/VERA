"""Shared knowledge contracts — AcquiredFile handoff + source kinds."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal[
    "documents",
    "web",
    "sharepoint",
    "blob",
    "sample",
    # Roadmap knowledge connectors (stubs until implemented)
    "outlook",
    "onedrive",
    "teams",
    "onelake",
    "azure_sql",
    "confluence",
    "gdrive",
]


class AcquiredFile(BaseModel):
    source_id: str | None = None
    filename: str
    mime: str | None = None
    content: bytes = Field(repr=False)
    appears_at: str | None = None
    binary_hash: str | None = None
    storage_path: str | None = None
    source_kind: SourceKind | None = None


class SourceAcquireResult(BaseModel):
    """Result of a connector.acquire() call before the shared ingest pipeline."""

    kind: SourceKind
    files: list[AcquiredFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# Re-export pipeline stage models so agents/ingest can stay thin later.
# Full stage models remain in agents.ingest.contracts for orchestrator compatibility;
# AcquiredFile is the cross-boundary type owned here.
