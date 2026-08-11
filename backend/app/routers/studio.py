from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.routers.agents import studio_dashboard
from app.schemas import FindingProofOut, StudioDashboard
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/studio", tags=["studio"])

_PROOF_KINDS = frozenset(
    {"compliance", "concepts", "relationships", "conflicts", "unsupported"}
)


@router.get("/dashboard", response_model=StudioDashboard)
async def dashboard() -> StudioDashboard:
    """Alias path — avoids any /api/agents/{id} shadowing through proxies."""
    return await studio_dashboard()


@router.get("/findings/{kind}", response_model=FindingProofOut)
async def finding_proof(
    kind: str,
    limit: int = Query(50, ge=1, le=200),
) -> FindingProofOut:
    """Prove-it drill-down for a Home AI Finding card row."""
    key = (kind or "").strip().lower()
    if key not in _PROOF_KINDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown finding kind '{kind}'. Expected one of: {', '.join(sorted(_PROOF_KINDS))}",
        )
    async with WorkspaceStore() as store:
        raw = await store.studio_finding_proof(key, limit=limit)
    return FindingProofOut(**raw)
