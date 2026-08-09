"""Knowledge ingest: isolated source connectors + shared pipeline.

AI that works — connectors acquire bytes; Ask never imports connectors.
"""

from app.knowledge.contracts import AcquiredFile, SourceAcquireResult, SourceKind
from app.knowledge.registry import get_connector, list_connector_status

__all__ = [
    "AcquiredFile",
    "SourceAcquireResult",
    "SourceKind",
    "get_connector",
    "list_connector_status",
]
