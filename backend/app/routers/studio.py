from __future__ import annotations

from fastapi import APIRouter

from app.routers.agents import studio_dashboard
from app.schemas import StudioDashboard

router = APIRouter(prefix="/api/studio", tags=["studio"])


@router.get("/dashboard", response_model=StudioDashboard)
async def dashboard() -> StudioDashboard:
    """Alias path — avoids any /api/agents/{id} shadowing through proxies."""
    return await studio_dashboard()
