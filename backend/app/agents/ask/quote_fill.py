from __future__ import annotations

from app.agents.ask.contracts import QuoteFillInput, QuoteFillOutput, QuoteHit
from app.agents.ask.evidence_contract import detect_evidence_contract
from app.agents.ask.overview import (
    chunk_info_score,
    clean_excerpt,
    is_deictic_document_question,
    is_document_overview,
    score_documents,
)
from app.agents.ask.people import is_candidate_lookup
from app.agents.ask.relevance import graph_should_lead, trail_answer_relevance
from app.agents.ask.retrieve import retrieve_evidence_pack
from app.agents.base import AgentContext, AgentResult
from app.config import get_settings
from app.stores.vector import VectorStore


async def _document_overview_quotes(store, workspace_id: str, question: str) -> list[QuoteHit]:
    docs = await store.list_canonical_documents(workspace_id)
    if not docs:
        return []
    scored = score_documents(docs, question)
    deictic = is_deictic_document_question(question)
    if deictic:
        selected = [scored[0][1]] if scored else []
    else:
        positive = [d for s, d in scored if s > 0]
        selected = positive[:2] if positive else [d for _, d in scored[:1]]

    hits: list[QuoteHit] = []
    for d in selected:
        chunks = await store.list_chunks(workspace_id, document_id=d["id"])
        if not chunks:
            continue
        chosen: list[dict] = [chunks[0]]
        ranked = sorted(
            chunks,
            key=lambda c: chunk_info_score(c.get("text") or "", question),
            reverse=True,
        )
        for ch in ranked:
            if ch["id"] in {c["id"] for c in chosen}:
                continue
            if chunk_info_score(ch.get("text") or "", question) < 0.5 and len(chosen) >= 2:
                continue
            chosen.append(ch)
            if len(chosen) >= 4:
                break
        for i, ch in enumerate(chosen):
            excerpt = clean_excerpt(ch.get("text") or "", max_len=420)
            if len(excerpt) < 40:
                continue
            hits.append(
                QuoteHit(
                    chunk_id=ch["id"],
                    document_title=d.get("title") or "document",
                    locator=(ch.get("loc") or {}).get("locator"),
                    quote=excerpt,
                    score=0.95 - (0.04 * i),
                )
            )
    return hits


class QuoteFillAgent:
    """Unified evidence pack: graph + hybrid KB + gap-fill → GPT-ready quotes."""

    id = "quote_fill"
    display_name = "Quote Fill Agent"
    input_model = QuoteFillInput
    output_model = QuoteFillOutput

    async def run(self, ctx: AgentContext, payload: QuoteFillInput) -> AgentResult[QuoteFillOutput]:
        settings = get_settings()
        store = ctx.stores
        vector: VectorStore = ctx.config.get("vector_store") or VectorStore()
        reason_codes = list(payload.reason_codes)
        path_strength = payload.best_trail.path_strength if payload.best_trail else 0.0
        overview = is_document_overview(payload.question)
        candidate = is_candidate_lookup(payload.question)
        contract = payload.evidence_contract or detect_evidence_contract(payload.question)
        reason_codes.extend(c for c in contract.reason_codes if c not in reason_codes)

        graph_quotes: list[QuoteHit] = []
        if payload.viable_evidence_bound_trail and payload.best_trail and store:
            evidence = await store.get_edge_evidence(
                ctx.workspace_id, payload.best_trail.edge_ids
            )
            chunks = await store.list_chunks(
                ctx.workspace_id, ids=list({e["source_chunk_id"] for e in evidence})
            )
            chunk_map = {c["id"]: c for c in chunks}
            docs = {
                d["id"]: d["title"]
                for d in await store.list_canonical_documents(ctx.workspace_id)
            }
            for ev in evidence:
                ch = chunk_map.get(ev["source_chunk_id"], {})
                graph_quotes.append(
                    QuoteHit(
                        chunk_id=ev["source_chunk_id"],
                        document_title=docs.get(ch.get("canonical_document_id"), "document"),
                        locator=(ch.get("loc") or {}).get("locator"),
                        quote=ev["quote"],
                        score=float(ev.get("confidence") or 0.8),
                        edge_id=ev["edge_id"],
                    )
                )

        overview_quotes: list[QuoteHit] = []
        if overview and store is not None:
            overview_quotes = await _document_overview_quotes(
                store, ctx.workspace_id, payload.question
            )

        pack = await retrieve_evidence_pack(
            ctx,
            store,
            vector,
            payload.question,
            top_k=max(settings.vera_quote_top_k, 8),
            graph_quotes=graph_quotes,
            prefer_overview=overview and not candidate,
            overview_quotes=overview_quotes,
            name_only=candidate,
            contract=contract,
        )

        quotes = pack.quotes
        retrieval_mode = pack.mode
        viable_graph = bool(
            payload.viable_evidence_bound_trail and graph_quotes and path_strength >= 0.5
        )
        hop_names: list[str] = []
        if payload.best_trail:
            hop_names = [h.from_name for h in payload.best_trail.hops] + [
                h.to_name for h in payload.best_trail.hops
            ]
        evidence_blob = " ".join(q.quote for q in graph_quotes)
        trail_rel = trail_answer_relevance(
            payload.question,
            hop_names,
            evidence_blob,
            pack.required_terms,
        )
        graph_leads = viable_graph and graph_should_lead(
            trail_rel, path_strength, pack.coverage
        )
        limit = max(settings.vera_quote_top_k, 8)
        if candidate:
            retrieval_mode = "name_lookup"
            if not quotes:
                reason_codes.append("NAME_NOT_FOUND_IN_SOURCES")
        elif overview and pack.mode == "document_overview":
            retrieval_mode = "document_overview"
        elif graph_leads:
            # Graph-first, but always reserve hybrid slots so KB hits survive
            g_ids = {q.chunk_id for q in graph_quotes}
            lead = [q for q in quotes if q.edge_id or q.chunk_id in g_ids]
            rest = [q for q in quotes if q not in lead]
            if not lead:
                lead = list(graph_quotes)
            reserve = max(3, limit // 2)
            quotes = (lead[: max(1, limit - reserve)] + rest)[:limit]
            retrieval_mode = (
                "graph_primary"
                if path_strength >= 0.65 or pack.mode == "graph_primary"
                else "hybrid_graph_kb"
            )
        elif viable_graph:
            # Trail exists but does not answer the question — hybrid leads
            retrieval_mode = (
                "hybrid_kb"
                if pack.mode == "hybrid_kb"
                else ("hybrid_graph_kb" if graph_quotes else pack.mode)
            )
            reason_codes.append("GRAPH_TRAIL_LOW_RELEVANCE")
        elif pack.coverage >= 0.5:
            retrieval_mode = "hybrid_kb" if "graph" not in pack.mode else pack.mode
        elif graph_quotes and pack.coverage < 0.35 and not quotes:
            quotes = graph_quotes
            retrieval_mode = "graph_primary"

        if not quotes:
            reason_codes.append("NO_QUOTE_EVIDENCE")

        if quotes and retrieval_mode in {
            "hybrid_kb",
            "hybrid_graph_kb",
            "graph_primary",
            "document_overview",
            "name_lookup",
        }:
            reason_codes = [
                c
                for c in reason_codes
                if c not in {"ENTITY_NOT_RESOLVED", "NO_SEED_ENTITIES", "NO_EVIDENCE_BOUND_PATH"}
            ]

        # Preserve retrieve/rerank order — do not re-crown by raw score
        out_trail = payload.best_trail
        out_strength = path_strength
        if "GRAPH_TRAIL_LOW_RELEVANCE" in reason_codes:
            out_trail = None
            out_strength = 0.0

        ctx.emit(
            self.id,
            "quotes.done",
            f"mode={retrieval_mode} quotes={len(quotes)} coverage={pack.coverage:.2f}",
            progress=1.0,
            data={
                "coverage": pack.coverage,
                "required_terms": pack.required_terms,
                "trail_relevance": trail_rel,
            },
        )
        return AgentResult(
            ok=True,
            data=QuoteFillOutput(
                question=payload.question,
                intent=payload.intent,
                quotes=quotes[: max(settings.vera_quote_top_k, 8)],
                retrieval_mode=retrieval_mode,
                best_trail=out_trail,
                reason_codes=reason_codes,
                entity_resolution_score=payload.entity_resolution_score,
                path_strength=out_strength,
                evidence_contract=contract,
            ),
            metrics={
                "quotes": len(quotes),
                "mode": retrieval_mode,
                "coverage": pack.coverage,
                "trail_relevance": trail_rel,
                "contract": contract.shape,
            },
        )
