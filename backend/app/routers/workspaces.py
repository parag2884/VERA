from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.runtime import get_runtime
from app.schemas import WorkspaceCreate, WorkspaceOut
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut)
async def create_workspace(body: WorkspaceCreate) -> WorkspaceOut:
    async with WorkspaceStore() as store:
        ws = await store.create_workspace(body.name)
    return WorkspaceOut(id=ws["id"], name=ws["name"], created_at=ws["created_at"])


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: str) -> WorkspaceOut:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return WorkspaceOut(id=ws["id"], name=ws["name"], created_at=ws["created_at"])


@router.post("/{workspace_id}/hygiene")
async def hygiene_workspace_knowledge(workspace_id: str) -> dict:
    """Prune over-aliases and retype junk Person nodes (non-destructive)."""
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        report = await store.hygiene_knowledge(workspace_id)
    return {"workspace_id": workspace_id, **report}


@router.post("/{workspace_id}/purge")
async def purge_workspace_knowledge(workspace_id: str) -> dict:
    """Wipe knowledge graph, documents, chunks, vectors, and chat for this workspace."""
    runtime = get_runtime()
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        counts = await store.purge_knowledge(workspace_id)

    vectors_removed = await runtime.vector_store.delete_workspace(workspace_id)

    settings = get_settings()
    upload_dir = settings.data_dir / "uploads" / workspace_id
    uploads_removed = False
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
        uploads_removed = True

    return {
        "workspace_id": workspace_id,
        "counts": counts,
        "vectors_removed": vectors_removed,
        "uploads_removed": uploads_removed,
    }
