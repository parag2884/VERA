from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.runtime import get_runtime
from app.schemas import AgentInfo, HealthOut, StatusOut
from app.stores.sql import WorkspaceStore
from app import __version__

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def api_health() -> dict:
    runtime = get_runtime()
    return {
        "ok": True,
        "version": __version__,
        "demo_mode": runtime.demo_mode,
        "provider_mode": runtime.provider_mode,
    }


@router.get("/health/knowledge", response_model=HealthOut)
async def knowledge_health(workspace_id: str = Query(...)) -> HealthOut:
    runtime = get_runtime()
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        h = await store.get_health(workspace_id)
    if not h:
        return HealthOut(score=0, components={}, demo_mode=runtime.demo_mode)
    return HealthOut(score=h["score"], components=h["components"], demo_mode=runtime.demo_mode)


@router.get("/status", response_model=StatusOut)
async def status() -> StatusOut:
    runtime = get_runtime()
    return StatusOut(
        version=__version__,
        demo_mode=runtime.demo_mode,
        provider_mode=runtime.provider_mode,  # type: ignore[arg-type]
        retrieval_mode=runtime.settings.vera_retrieval_mode,
        agents=[AgentInfo(**a) for a in runtime.registry.list()],
        pipelines=runtime.orchestrator.list_pipelines(),
    )


@router.get("/registry")
async def list_registry() -> dict:
    """Internal pipeline micro-agents (not deployable product agents)."""
    runtime = get_runtime()
    return {"agents": runtime.registry.list(), "pipelines": runtime.orchestrator.list_pipelines()}
