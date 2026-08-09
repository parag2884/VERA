"""SourceConnector protocol — every knowledge source implements acquire()."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.knowledge.contracts import SourceAcquireResult, SourceKind


class SourceNotConfiguredError(RuntimeError):
    """Raised when a connector is present but missing credentials/config."""

    def __init__(self, kind: SourceKind, message: str, *, setup_hint: str = "") -> None:
        self.kind = kind
        self.setup_hint = setup_hint
        super().__init__(message)


@runtime_checkable
class SourceConnector(Protocol):
    kind: SourceKind

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        """Fetch raw files for the shared ingest pipeline."""
        ...

    def status(self) -> dict[str, Any]:
        """Connector capability / configuration status for /api/sources/connectors."""
        ...
