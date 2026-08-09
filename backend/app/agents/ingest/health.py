from __future__ import annotations

from app.agents.base import AgentContext, AgentResult
from app.agents.ingest.contracts import HealthInput, HealthOutput
from app.services.passage_signals import summarize_passage_readiness


class IndexHealthAgent:
    id = "index_health"
    display_name = "Index Health Agent"
    input_model = HealthInput
    output_model = HealthOutput

    async def run(self, ctx: AgentContext, payload: HealthInput) -> AgentResult[HealthOutput]:
        store = ctx.stores
        counts = await store.counts(ctx.workspace_id) if store else {}
        report = payload.cleanstack_report or {}

        ingest_success = 1.0 if counts.get("documents", 0) > 0 else 0.0
        embed_ratio = 1.0 if payload.embedded_count > 0 else 0.0
        evidence_ratio = (
            payload.evidence_bound_edges / max(payload.edges_created, 1)
            if payload.edges_created
            else 0.0
        )
        connectivity = min(1.0, counts.get("edges", 0) / max(counts.get("nodes", 1), 1))
        dupe_hygiene = min(1.0, (report.get("embeddings_avoided") or 0) / max(report.get("total_files") or 1, 1) + 0.5)

        passage = {}
        if store is not None:
            docs = await store.list_canonical_documents(ctx.workspace_id)
            chunks = await store.list_chunks(ctx.workspace_id)
            passage = summarize_passage_readiness(chunks, docs)

        chrome_pct = float(passage.get("chrome_heavy_pct") or 0)
        passage_hygiene = max(0.0, min(1.0, 1.0 - chrome_pct / 100.0))

        score = round(
            100
            * (
                0.22 * ingest_success
                + 0.18 * embed_ratio
                + 0.22 * evidence_ratio
                + 0.18 * connectivity
                + 0.10 * min(dupe_hygiene, 1.0)
                + 0.10 * passage_hygiene
            ),
            1,
        )
        components = {
            "ingest_success": ingest_success,
            "embed_ratio": embed_ratio,
            "evidence_bound_ratio": round(evidence_ratio, 3),
            "graph_connectivity": round(connectivity, 3),
            "cleanstack_hygiene": round(min(dupe_hygiene, 1.0), 3),
            "passage_hygiene": round(passage_hygiene, 3),
            "passage": passage,
            "counts": counts,
            "cleanstack": {
                "keepers": report.get("keepers"),
                "embeddings_avoided": report.get("embeddings_avoided"),
                "tokens_avoided": report.get("tokens_avoided"),
            },
        }
        if store is not None:
            await store.save_health(ctx.workspace_id, score, components)

        ctx.emit(self.id, "health.done", f"Knowledge Health Score {score}", progress=1.0)
        return AgentResult(
            ok=True,
            data=HealthOutput(score=score, components=components),
            metrics={"score": score, "chrome_heavy_pct": chrome_pct},
        )
