from __future__ import annotations

from collections import defaultdict, deque

from app.agents.ask.contracts import (
    GraphRetrieveInput,
    GraphRetrieveOutput,
    RankedTrail,
)
from app.agents.ask.relevance import trail_answer_relevance
from app.agents.base import AgentContext, AgentResult
from app.config import get_settings
from app.schemas import TrustTrailHop


class GraphRetrieveAgent:
    """Walk asserted evidence-bound fact edges. Planned multi-hop between seeds."""

    id = "graph_retrieve"
    display_name = "Graph Retrieve Agent"
    input_model = GraphRetrieveInput
    output_model = GraphRetrieveOutput

    async def run(
        self, ctx: AgentContext, payload: GraphRetrieveInput
    ) -> AgentResult[GraphRetrieveOutput]:
        settings = get_settings()
        store = ctx.stores
        reason_codes = list(payload.reason_codes)
        max_hops = max(1, int(settings.vera_graph_hops or 3))

        seed_ids = []
        for ent in payload.entities:
            seed_ids.extend(ent.node_ids)
        seed_ids = list(dict.fromkeys(seed_ids))

        entity_resolution_score = 0.0
        if payload.entities:
            hit = sum(1 for e in payload.entities if e.node_ids and not e.ambiguous)
            entity_resolution_score = hit / max(len(payload.entities), 1)

        if not store or not seed_ids:
            reason_codes.append("NO_SEED_ENTITIES")
            return AgentResult(
                ok=True,
                data=GraphRetrieveOutput(
                    question=payload.question,
                    intent=payload.intent,
                    trails=[],
                    best_trail=None,
                    viable_evidence_bound_trail=False,
                    reason_codes=reason_codes,
                    entity_resolution_score=entity_resolution_score,
                ),
            )

        graph = await store.get_graph(ctx.workspace_id)
        nodes = {n["id"]: n for n in graph["nodes"]}
        # Only asserted fact edges WITH evidence qualify for answer paths
        edges = [
            e
            for e in graph["edges"]
            if e["edge_class"] == "asserted_fact" and e.get("has_evidence")
        ]
        adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e))
            adj[e["dst"]].append((e["src"], e))

        trails: list[RankedTrail] = []
        seen_path_keys: set[str] = set()

        async def _add_path(
            oriented: list[tuple[str, str, dict]], *, pair_bonus: float = 0.0
        ) -> None:
            """oriented = list of (from_id, to_id, edge) in walk order."""
            if not oriented:
                return
            key = "|".join(f"{frm}>{e['id']}>{to}" for frm, to, e in oriented)
            if key in seen_path_keys:
                return
            seen_path_keys.add(key)

            hops: list[TrustTrailHop] = []
            edge_ids: list[str] = []
            conflict = False
            for frm, to, e in oriented:
                src_name = nodes.get(frm, {}).get("name", frm)
                dst_name = nodes.get(to, {}).get("name", to)
                hops.append(
                    TrustTrailHop.model_validate(
                        {
                            "from": src_name,
                            "rel": e["rel_type"],
                            "to": dst_name,
                            "edge_id": e["id"],
                        }
                    )
                )
                edge_ids.append(e["id"])
                if e["rel_type"] == "CONFLICTS_WITH":
                    conflict = True

            evidence = await store.get_edge_evidence(ctx.workspace_id, edge_ids)
            chunk_ids = list({ev["source_chunk_id"] for ev in evidence})
            by_edge = {ev["edge_id"]: ev for ev in evidence}
            enriched = []
            for hop in hops:
                data = hop.model_dump(by_alias=True)
                ev = by_edge.get(hop.edge_id or "")
                if ev:
                    data["evidence_quote"] = ev["quote"]
                enriched.append(TrustTrailHop.model_validate(data))

            # Prefer short, well-evidenced paths over long meandering ones
            hop_pen = 0.1 * max(0, len(edge_ids) - 1)
            strength = min(
                1.0, 0.72 + 0.06 * len(chunk_ids) + pair_bonus - hop_pen
            )
            if conflict:
                strength *= 0.7
            trails.append(
                RankedTrail(
                    hops=enriched,
                    edge_ids=edge_ids,
                    chunk_ids=chunk_ids,
                    path_strength=strength,
                    conflict=conflict,
                )
            )

        # 1) Planned multi-hop: shortest evidence paths between distinct seed pairs
        if len(seed_ids) >= 2:
            for i, a in enumerate(seed_ids):
                for b in seed_ids[i + 1 :]:
                    pair_path = _shortest_path(a, b, adj, max_hops=max_hops)
                    if pair_path:
                        await _add_path(pair_path, pair_bonus=0.22)

        # 2) Ego expansion from each seed (fills single-entity questions)
        for start in seed_ids:
            paths = _bfs_paths(start, adj, max_hops=max_hops)
            for edge_path in paths:
                await _add_path(edge_path)

        q = payload.question.lower()
        seed_names = {nodes[s].get("name") for s in seed_ids if s in nodes}
        for trail in trails:
            rels = " ".join(h.rel for h in trail.hops).lower()
            hop_name_list = [h.from_name for h in trail.hops] + [
                h.to_name for h in trail.hops
            ]
            evidence_blob = " ".join(
                (h.evidence_quote or "") for h in trail.hops if h.evidence_quote
            )
            trail.path_strength += _relation_question_boost(q, rels)
            # Generic: boost/penalize by how well hops+evidence match the question
            rel = trail_answer_relevance(
                payload.question, hop_name_list, evidence_blob
            )
            trail.path_strength += 0.28 * rel
            if rel < 0.2:
                trail.path_strength -= 0.35
            hop_names = set(hop_name_list)
            overlap = len(hop_names & seed_names)
            if overlap >= 2:
                trail.path_strength += 0.12 * (overlap - 1)

        trails.sort(key=lambda t: t.path_strength, reverse=True)
        best = trails[0] if trails else None
        viable = bool(
            best and best.edge_ids and best.chunk_ids and best.path_strength >= 0.5
        )
        if not viable:
            reason_codes.append("NO_EVIDENCE_BOUND_PATH")

        ctx.emit(
            self.id,
            "graph.done",
            f"Trails={len(trails)} viable={viable} hops≤{max_hops}",
            progress=1.0,
        )
        return AgentResult(
            ok=True,
            data=GraphRetrieveOutput(
                question=payload.question,
                intent=payload.intent,
                trails=trails[:8],
                best_trail=best,
                viable_evidence_bound_trail=viable,
                reason_codes=reason_codes,
                entity_resolution_score=entity_resolution_score,
            ),
            metrics={"trails": len(trails), "viable": int(viable), "max_hops": max_hops},
        )


def _relation_question_boost(question: str, rels: str) -> float:
    """Domain-agnostic boosts from question verbs ↔ edge labels."""
    boost = 0.0
    checks = [
        (("own", "responsible", "owner"), "owns", 0.25),
        (("require", "must", "need", "depend"), "requires", 0.25),
        (("supersed", "replace", "obsolete"), "supersedes", 0.3),
        (("conflict", "contradict"), "conflicts_with", 0.3),
        (("part of", "belongs", "component"), "part_of", 0.2),
        (("govern", "policy", "applies"), "governed_by", 0.2),
        (("govern", "policy", "applies"), "applies_to", 0.2),
        (("use", "using", "via"), "uses", 0.15),
        (("provide", "offer"), "provides", 0.15),
        (("related", "relationship", "between"), "related_to", 0.2),
        (("defin", "mean", "what is"), "defined_as", 0.2),
        (("who", "employ", "works", "reports"), "employs", 0.2),
        (("who", "employ", "works", "reports"), "works_for", 0.2),
        (("who", "employ", "works", "reports"), "reports_to", 0.2),
        (("who", "found"), "founded_by", 0.22),
        (("who", "found"), "founded", 0.18),
        (("who", "lead", "leads", "heads", "run"), "led_by", 0.18),
        (("who", "lead", "leads", "heads", "run"), "leads", 0.15),
        (("who", "role"), "has_role", 0.2),
    ]
    for q_words, rel_token, score in checks:
        if any(w in question for w in q_words) and rel_token in rels:
            boost = max(boost, score)
    return boost


def _shortest_path(
    start: str,
    goal: str,
    adj: dict[str, list[tuple[str, dict]]],
    max_hops: int,
) -> list[tuple[str, str, dict]] | None:
    if start == goal:
        return None
    queue: deque[tuple[str, list[tuple[str, str, dict]]]] = deque([(start, [])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt in visited:
                continue
            nxt_path = path + [(node, nxt, edge)]
            if nxt == goal:
                return nxt_path
            visited.add(nxt)
            queue.append((nxt, nxt_path))
    return None


def _bfs_paths(
    start: str, adj: dict[str, list[tuple[str, dict]]], max_hops: int
) -> list[list[tuple[str, str, dict]]]:
    paths: list[list[tuple[str, str, dict]]] = []
    queue: deque[tuple[str, list[tuple[str, str, dict]], set[str]]] = deque(
        [(start, [], {start})]
    )
    while queue:
        node, path, visited = queue.popleft()
        if path:
            paths.append(path)
        if len(path) >= max_hops:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt in visited:
                continue
            queue.append((nxt, path + [(node, nxt, edge)], visited | {nxt}))
    paths.sort(key=len)
    return paths[:24]
