from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import GraphEdgeOut, GraphNodeOut, GraphOut, TrustTrailHop
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphOut)
async def get_graph(workspace_id: str = Query(...)) -> GraphOut:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        g = await store.get_graph(workspace_id)
    return GraphOut(
        nodes=[
            GraphNodeOut(
                id=n["id"],
                type=n["type"],
                name=n["name"],
                normalized_name=n["normalized_name"],
                props=n.get("props") or {},
            )
            for n in g["nodes"]
        ],
        edges=[
            GraphEdgeOut(
                id=e["id"],
                src=e["src"],
                dst=e["dst"],
                rel_type=e["rel_type"],
                edge_class=e["edge_class"],
                weight=e.get("weight") or 1.0,
                status=e.get("status") or "active",
                has_evidence=bool(e.get("has_evidence")),
            )
            for e in g["edges"]
        ],
    )


@router.get("/path")
async def graph_path(
    workspace_id: str = Query(...),
    source: str = Query(..., description="Entity name"),
    target: str = Query(..., description="Entity name"),
) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        src_nodes = await store.resolve_entity(workspace_id, source)
        dst_nodes = await store.resolve_entity(workspace_id, target)
        if not src_nodes or not dst_nodes:
            return {"found": False, "trail": [], "reason_codes": ["ENTITY_NOT_RESOLVED"]}
        g = await store.get_graph(workspace_id)
        nodes = {n["id"]: n for n in g["nodes"]}
        edges = [e for e in g["edges"] if e["edge_class"] == "asserted_fact" and e.get("has_evidence")]
        # Simple BFS
        from collections import deque

        start, goal = src_nodes[0]["id"], dst_nodes[0]["id"]
        # path steps: (from_id, to_id, edge)
        q: deque[tuple[str, list[tuple[str, str, dict]]]] = deque([(start, [])])
        seen = {start}
        while q:
            node, path = q.popleft()
            if node == goal and path:
                hops = []
                for frm, to, e in path:
                    hops.append(
                        TrustTrailHop.model_validate(
                            {
                                "from": nodes[frm]["name"],
                                "rel": e["rel_type"],
                                "to": nodes[to]["name"],
                                "edge_id": e["id"],
                            }
                        ).model_dump(by_alias=True)
                    )
                return {"found": True, "trail": hops}
            if len(path) >= 6:
                continue
            for e in edges:
                nxt = None
                if e["src"] == node:
                    nxt = e["dst"]
                elif e["dst"] == node:
                    nxt = e["src"]
                if nxt and nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, path + [(node, nxt, e)]))
        return {"found": False, "trail": [], "reason_codes": ["NO_EVIDENCE_BOUND_PATH"]}
