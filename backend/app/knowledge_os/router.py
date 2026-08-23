from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.knowledge_os import service as kos
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/workspaces", tags=["knowledge-os"])


class FeedbackIn(BaseModel):
    message_id: str
    rating: str = Field(description="up or down")
    note: str = ""


@router.get("/{workspace_id}/knowledge-os")
async def get_knowledge_os(workspace_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        return await kos.snapshot(store, workspace_id)


@router.post("/{workspace_id}/knowledge-os/enrich")
async def enrich_knowledge_os(workspace_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        report = await kos.enrich_graph(store, workspace_id)
        snap = await kos.snapshot(store, workspace_id)
        snap["enrich"] = report
        return snap


class DraftAcceptIn(BaseModel):
    must_any: list[str] = Field(default_factory=list)


@router.post("/{workspace_id}/knowledge-os/drafts/{draft_id}/accept")
async def accept_draft(workspace_id: str, draft_id: str, body: DraftAcceptIn) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        must = "|".join(p.strip() for p in body.must_any if p.strip())
        await store.set_draft_golden(workspace_id, draft_id, status="accepted", must_any=must)
        return {"ok": True, "status": "accepted"}


@router.post("/{workspace_id}/knowledge-os/drafts/{draft_id}/reject")
async def reject_draft(workspace_id: str, draft_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        await store.set_draft_golden(workspace_id, draft_id, status="rejected")
        return {"ok": True, "status": "rejected"}


class PolicyIn(BaseModel):
    kind: str = "lock_rel"
    target: str
    note: str = ""


@router.post("/{workspace_id}/knowledge-os/versions")
async def snapshot_version(workspace_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.governance import capture_version, record_metric_snapshot

        snap = await kos.snapshot(store, workspace_id)
        ver = await capture_version(
            store,
            workspace_id,
            label="manual snapshot",
            status="snapshot",
            metrics={
                "debt": (snap.get("debt") or {}).get("score"),
                "fitness": snap.get("fitness"),
                "coverage": (snap.get("coverage") or {}).get("overall_pct"),
                "trust": (snap.get("debt") or {}).get("trust_pct"),
                "risk": ((snap.get("debt") or {}).get("risk") or {}).get("level"),
            },
        )
        await record_metric_snapshot(
            workspace_id,
            {
                "debt": (snap.get("debt") or {}).get("score"),
                "fitness": snap.get("fitness"),
                "coverage": (snap.get("coverage") or {}).get("overall_pct"),
                "trust": (snap.get("debt") or {}).get("trust_pct"),
                "risk": ((snap.get("debt") or {}).get("risk") or {}).get("level"),
            },
        )
        return ver


@router.post("/{workspace_id}/knowledge-os/versions/{version_id}/rollback")
async def rollback_version(workspace_id: str, version_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.governance import restore_version

        try:
            return await restore_version(store, workspace_id, version_id)
        except KeyError:
            raise HTTPException(404, "Version not found") from None


@router.post("/{workspace_id}/knowledge-os/versions/{version_id}/promote")
async def promote_graph_version(workspace_id: str, version_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.governance import promote_version

        try:
            return await promote_version(workspace_id, version_id)
        except KeyError:
            raise HTTPException(404, "Version not found") from None


@router.post("/{workspace_id}/knowledge-os/policies")
async def add_graph_policy(workspace_id: str, body: PolicyIn) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.governance import add_policy

        return await add_policy(
            workspace_id, kind=body.kind, target=body.target, note=body.note
        )


class ActionDoneIn(BaseModel):
    driver: str


@router.post("/{workspace_id}/knowledge-os/actions/complete")
async def complete_ops_action(workspace_id: str, body: ActionDoneIn) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        snap = await kos.snapshot(store, workspace_id)
        from app.knowledge_os.governance import record_metric_snapshot
        from app.knowledge_os.proof import complete_action

        debt = float((snap.get("debt") or {}).get("score") or 0)
        await complete_action(workspace_id, body.driver, debt=debt)
        await record_metric_snapshot(
            workspace_id,
            {
                "debt": debt,
                "fitness": snap.get("fitness"),
                "coverage": (snap.get("coverage") or {}).get("overall_pct"),
                "trust": (snap.get("debt") or {}).get("trust_pct"),
                "risk": ((snap.get("debt") or {}).get("risk") or {}).get("level"),
            },
        )
        return {"ok": True, "driver": body.driver}


class SourceGovIn(BaseModel):
    document_id: str
    owner: str = ""
    reviewer: str = ""


@router.post("/{workspace_id}/knowledge-os/sources")
async def review_source(workspace_id: str, body: SourceGovIn) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.control import upsert_source_gov

        return await upsert_source_gov(
            workspace_id,
            body.document_id,
            owner=body.owner,
            reviewer=body.reviewer,
        )


class GoalsIn(BaseModel):
    target_debt: float = 10
    target_coverage: float = 90


@router.post("/{workspace_id}/knowledge-os/goals")
async def set_goals(workspace_id: str, body: GoalsIn) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        from app.knowledge_os.control import save_goals

        return await save_goals(
            workspace_id, target_debt=body.target_debt, target_coverage=body.target_coverage
        )


board_router = APIRouter(prefix="/api/knowledge-os", tags=["knowledge-os"])


@board_router.get("/fleet")
async def fleet_knowledge_health() -> dict:
    async with WorkspaceStore() as store:
        cards = []
        for a in await store.list_agents():
            try:
                snap = await kos.snapshot(store, a["workspace_id"])
            except Exception:  # noqa: BLE001
                continue
            debt = snap.get("debt") or {}
            slos = (snap.get("governance") or {}).get("slos") or {}
            cards.append(
                {
                    "agent_id": a.get("id"),
                    "name": a.get("name"),
                    "workspace_id": a.get("workspace_id"),
                    "risk": (debt.get("risk") or {}).get("level"),
                    "debt": debt.get("score"),
                    "coverage": (snap.get("coverage") or {}).get("overall_pct"),
                    "trust": debt.get("trust_pct"),
                    "fitness": snap.get("fitness"),
                    "refusal_rate": slos.get("refusal_rate"),
                    "sla_ok": ((snap.get("ops") or {}).get("sla") or {}).get("passing"),
                    "sla_miss": ((snap.get("ops") or {}).get("sla") or {}).get("failed_ids")
                    or [],
                }
            )
        return {"workspaces": cards}
