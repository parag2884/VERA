"""Connector registry — single place to resolve SourceKind → connector."""

from __future__ import annotations

from typing import Any

from app.knowledge.base import SourceConnector
from app.knowledge.contracts import SourceKind
from app.knowledge.sources.blob.client import BlobConnector
from app.knowledge.sources.documents.sample import SampleConnector
from app.knowledge.sources.documents.upload import DocumentsConnector
from app.knowledge.sources.planned import ROADMAP_CONNECTORS
from app.knowledge.sources.sharepoint.connector import SharePointConnector
from app.knowledge.sources.web.connector import WebConnector

_LIVE: dict[SourceKind, SourceConnector] = {
    "documents": DocumentsConnector(),
    "web": WebConnector(),
    "sharepoint": SharePointConnector(),
    "blob": BlobConnector(),
    "sample": SampleConnector(),
}

_PLANNED: dict[SourceKind, SourceConnector] = {c.kind: c for c in ROADMAP_CONNECTORS}

_CONNECTORS: dict[SourceKind, SourceConnector] = {**_LIVE, **_PLANNED}


def get_connector(kind: SourceKind) -> SourceConnector:
    try:
        return _CONNECTORS[kind]
    except KeyError as exc:
        raise KeyError(f"Unknown source kind: {kind}") from exc


def list_connector_status() -> dict[str, Any]:
    """Status map for GET /api/sources/connectors (API + UI catalog)."""
    docs = get_connector("documents").status()
    web = get_connector("web").status()
    sp = get_connector("sharepoint").status()
    blob = get_connector("blob").status()
    sample = get_connector("sample").status()

    catalog: list[dict[str, Any]] = [
        {
            "id": "upload",
            "kind": "documents",
            "title": "Files & Zip",
            "blurb": "PDF, Office, images",
            **docs,
        },
        {
            "id": "website",
            "kind": "web",
            "title": "Website",
            "blurb": "Public docs & pages",
            **web,
        },
        {
            "id": "sharepoint",
            "kind": "sharepoint",
            "title": "SharePoint",
            "blurb": "Sites & libraries",
            **sp,
        },
        {
            "id": "blob",
            "kind": "blob",
            "title": "Azure Blob",
            "blurb": "Container sync",
            **blob,
        },
    ]
    for c in ROADMAP_CONNECTORS:
        st = c.status()
        catalog.append(
            {
                "id": c.kind,
                "kind": c.kind,
                "title": st.get("title") or c.kind,
                "blurb": st.get("blurb") or "",
                **st,
            }
        )

    planned_status = {c.kind: c.status() for c in ROADMAP_CONNECTORS}

    return {
        "upload": docs,
        "documents": docs,
        "website": web,
        "web": web,
        "sharepoint": sp,
        "blob": blob,
        "sample": sample,
        **planned_status,
        "catalog": catalog,
    }
