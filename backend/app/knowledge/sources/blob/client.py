"""Azure Blob Storage connector — stub until credentials are configured."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.knowledge.base import SourceNotConfiguredError
from app.knowledge.contracts import AcquiredFile, SourceAcquireResult


def blob_configured() -> bool:
    s = get_settings()
    return bool(
        getattr(s, "vera_azure_blob_connection_string", "")
        or getattr(s, "vera_azure_storage_account", "")
    )


class BlobConnector:
    kind = "blob"

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        container = (kwargs.get("container") or "").strip()
        if not container:
            raise ValueError("container is required")
        if not blob_configured():
            raise SourceNotConfiguredError(
                "blob",
                "Azure Blob is not configured for this VERA instance.",
                setup_hint=(
                    "Set VERA_AZURE_BLOB_CONNECTION_STRING (or account + key) "
                    "and restart the API. See docs/CONFIGURATION.md."
                ),
            )
        # Full SDK list/download lands here when credentials exist.
        _ = kwargs.get("prefix")
        files: list[AcquiredFile] = []
        return SourceAcquireResult(
            kind="blob",
            files=files,
            warnings=["BLOB_SDK_PENDING"],
            meta={"container": container, "configured": True},
        )

    def status(self) -> dict[str, Any]:
        configured = blob_configured()
        return {
            "enabled": True,
            "state": "configured" if configured else "needs_config",
            "configured": configured,
            "note": (
                "Sync files from an Azure Blob container into the shared ingest pipeline."
                if configured
                else "Set VERA_AZURE_BLOB_CONNECTION_STRING to enable."
            ),
        }
