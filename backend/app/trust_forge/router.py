"""Trust Forge API — climb golden-suite fitness per workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import logging

from app.trust_forge import service as forge

log = logging.getLogger("vera.trust_forge")

router = APIRouter(prefix="/api/workspaces", tags=["trust-forge"])


class TrustForgeStartBody(BaseModel):
    agent_id: str | None = None
    suite_path: str | None = None
    threshold: float = Field(default=95.0, ge=0, le=100)
    max_generations: int = Field(default=8, ge=1, le=40)
    stall_generations: int = Field(default=3, ge=1, le=20)


@router.post("/{workspace_id}/trust-forge/runs")
async def start_trust_forge(workspace_id: str, body: TrustForgeStartBody) -> dict[str, Any]:
    try:
        return await forge.start_run(
            workspace_id,
            agent_id=body.agent_id,
            suite_path=body.suite_path,
            threshold=body.threshold,
            max_generations=body.max_generations,
            stall_generations=body.stall_generations,
        )
    except KeyError as exc:
        code = str(exc)
        if code == "workspace_not_found":
            raise HTTPException(404, "Workspace not found") from exc
        if code == "agent_not_found":
            raise HTTPException(404, "Agent not found") from exc
        raise HTTPException(400, code) from exc
    except PermissionError as exc:
        raise HTTPException(403, "Agent does not belong to this workspace") from exc
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        log.exception("trust forge start failed workspace=%s", workspace_id)
        raise HTTPException(500, f"Could not start evaluation: {exc}") from exc


@router.get("/{workspace_id}/trust-forge/runs")
async def list_trust_forge_runs(workspace_id: str) -> dict[str, Any]:
    runs = await forge.list_runs(workspace_id)
    return {"workspace_id": workspace_id, "runs": runs}


@router.get("/{workspace_id}/trust-forge/runs/{run_id}")
async def get_trust_forge_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    run = await forge.get_run(workspace_id, run_id)
    if not run:
        raise HTTPException(404, "Trust Forge run not found")
    return run


@router.post("/{workspace_id}/trust-forge/runs/{run_id}/stop")
async def stop_trust_forge_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    try:
        return await forge.request_stop(workspace_id, run_id)
    except KeyError as exc:
        raise HTTPException(404, "Trust Forge run not found") from exc
