from __future__ import annotations

from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.agents.base import AgentContext, AgentResult
from app.agents.ingest.contracts import (
    CleanStackDecision,
    CleanStackInput,
    CleanStackOutput,
    ParsedFile,
)
from app.config import get_settings
from app.services.tokens import count_tokens, tokenizer_name


class CleanStackAgent:
    """Exact + near-duplicate detection after parse. Preserves multi-source provenance."""

    id = "cleanstack"
    display_name = "CleanStack Agent"
    input_model = CleanStackInput
    output_model = CleanStackOutput

    async def run(
        self, ctx: AgentContext, payload: CleanStackInput
    ) -> AgentResult[CleanStackOutput]:
        settings = get_settings()
        store = ctx.stores
        files = [f for f in payload.files if f.text.strip()]
        decisions: list[CleanStackDecision] = []
        keepers: list[ParsedFile] = []

        # Exact binary hash groups
        by_binary: dict[str, list[ParsedFile]] = defaultdict(list)
        for f in files:
            by_binary[f.binary_hash].append(f)

        survivor_ids: set[str] = set()
        exact_dupes = 0

        for group in by_binary.values():
            # Keep newest/largest as canonical content carrier
            group_sorted = sorted(group, key=lambda x: (x.byte_size, x.filename), reverse=True)
            canonical = group_sorted[0]
            survivor_ids.add(canonical.source_id)
            decisions.append(
                CleanStackDecision(
                    source_id=canonical.source_id,
                    filename=canonical.filename,
                    decision="keep",
                    reason="canonical_exact_group",
                    canonical_key=canonical.text_hash,
                    appears_at=canonical.appears_at,
                )
            )
            for dup in group_sorted[1:]:
                exact_dupes += 1
                decisions.append(
                    CleanStackDecision(
                        source_id=dup.source_id,
                        filename=dup.filename,
                        decision="skip_exact",
                        reason=f"exact_binary_duplicate_of:{canonical.filename}",
                        canonical_key=canonical.text_hash,
                        similarity=1.0,
                        appears_at=dup.appears_at,
                    )
                )

        candidates = [f for f in files if f.source_id in survivor_ids]

        # Exact text hash collapse
        by_text: dict[str, list[ParsedFile]] = defaultdict(list)
        for f in candidates:
            by_text[f.text_hash].append(f)

        text_survivors: list[ParsedFile] = []
        for group in by_text.values():
            group_sorted = sorted(group, key=lambda x: (len(x.text), x.filename), reverse=True)
            text_survivors.append(group_sorted[0])
            for dup in group_sorted[1:]:
                exact_dupes += 1
                # rewrite prior keep decision
                for d in decisions:
                    if d.source_id == dup.source_id and d.decision == "keep":
                        d.decision = "skip_exact"
                        d.reason = f"exact_text_duplicate_of:{group_sorted[0].filename}"
                        d.similarity = 1.0

        # Near-duplicate via TF-IDF
        near_dupes = 0
        final_keepers: list[ParsedFile] = []
        if len(text_survivors) >= 2:
            vectorizer = TfidfVectorizer(stop_words="english", max_features=4096)
            matrix = vectorizer.fit_transform([f.text for f in text_survivors])
            sims = cosine_similarity(matrix)
            skip: set[int] = set()
            for i in range(len(text_survivors)):
                if i in skip:
                    continue
                final_keepers.append(text_survivors[i])
                for j in range(i + 1, len(text_survivors)):
                    if j in skip:
                        continue
                    score = float(sims[i, j])
                    if score >= settings.vera_near_dupe_threshold:
                        skip.add(j)
                        near_dupes += 1
                        dup = text_survivors[j]
                        for d in decisions:
                            if d.source_id == dup.source_id and d.decision == "keep":
                                d.decision = "skip_near"
                                d.reason = f"near_duplicate_of:{text_survivors[i].filename}"
                                d.similarity = score
        else:
            final_keepers = text_survivors

        keepers = final_keepers
        keep_ids = {k.source_id for k in keepers}

        # Ensure decisions cover all
        decided_ids = {d.source_id for d in decisions}
        for f in files:
            if f.source_id not in decided_ids:
                decisions.append(
                    CleanStackDecision(
                        source_id=f.source_id,
                        filename=f.filename,
                        decision="keep" if f.source_id in keep_ids else "skip_exact",
                        reason="default",
                        canonical_key=f.text_hash,
                        appears_at=f.appears_at,
                    )
                )

        tokens_avoided = sum(
            count_tokens(f.text) for f in files if f.source_id not in keep_ids
        )
        tokens_kept = sum(count_tokens(f.text) for f in keepers)
        tokens_before = tokens_kept + tokens_avoided
        embeddings_avoided = len(files) - len(keepers)
        price = settings.vera_embed_price_per_1m_tokens
        usd_at_rate = round((tokens_avoided / 1_000_000) * price, 6) if price > 0 else None
        total = max(len(files), 1)
        reduction_pct = round(100.0 * embeddings_avoided / total, 1)
        token_reduction_pct = (
            round(100.0 * tokens_avoided / tokens_before, 1) if tokens_before else 0.0
        )
        groups = _groups(decisions)
        tok = tokenizer_name()

        why: list[str] = []
        if exact_dupes:
            why.append(
                f"Removed {exact_dupes} exact duplicate file(s) (same bytes or identical text)."
            )
        if near_dupes:
            why.append(
                f"Collapsed {near_dupes} near-duplicate(s) "
                f"(TF-IDF ≥ {settings.vera_near_dupe_threshold})."
            )
        if embeddings_avoided:
            why.append(
                f"Skipped {embeddings_avoided} file embedding(s) and "
                f"{tokens_avoided:,} tokenizer tokens ({tok}) — keepers only."
            )
        else:
            why.append("No duplicates found this run — every file was a unique keeper.")
        why.append(
            "Multi-source provenance is preserved on skip decisions "
            "(appears_at kept for audit)."
        )
        why.append(
            "Downstream Graph Weaver + Ask only see keepers — "
            "cleaner trails, less contradictory noise."
        )

        report = {
            "total_files": len(files),
            "keepers": len(keepers),
            "skipped": embeddings_avoided,
            "exact_duplicates": exact_dupes,
            "near_duplicates": near_dupes,
            "embeddings_before": len(files),
            "embeddings_after": len(keepers),
            "embeddings_avoided": embeddings_avoided,
            "tokens_before": tokens_before,
            "tokens_after": tokens_kept,
            "tokens_avoided": tokens_avoided,
            "token_reduction_pct": token_reduction_pct,
            "reduction_pct": reduction_pct,
            "estimated_usd_avoided": usd_at_rate,
            "near_dupe_threshold": settings.vera_near_dupe_threshold,
            "embed_price_per_1m_tokens": price,
            "tokenizer": tok,
            "token_accounting": "tiktoken",
            "headline": (
                f"CleanStack kept {len(keepers)} of {len(files)} files · "
                f"{tokens_avoided:,} tokens not embedded"
                if embeddings_avoided
                else f"CleanStack reviewed {len(files)} file(s) — all keepers"
            ),
            "why_it_helps": why,
            "parameters": {
                "fingerprint": "SHA-256 binary + text hash",
                "exact_dedupe": "binary hash, then text hash",
                "near_dedupe": f"TF-IDF cosine ≥ {settings.vera_near_dupe_threshold}",
                "embed_policy": "keepers only",
                "tokenizer": f"tiktoken {tok} (embed-compatible)",
                "usd_rate": (
                    f"${price}/1M tokens (configured; apply to tokenizer counts)"
                    if price > 0
                    else "not configured"
                ),
            },
            "pricing_note": (
                f"Token counts are measured with tiktoken ({tok}), not char÷4 guesses. "
                + (
                    f"USD uses configured rate ${price}/1M tokens — set "
                    "VERA_EMBED_PRICE_PER_1M_TOKENS to your Azure embedding price."
                    if price > 0
                    else "Set VERA_EMBED_PRICE_PER_1M_TOKENS to show USD at your rate."
                )
            ),
            "decisions": [d.model_dump() for d in decisions],
            "groups": groups,
        }

        if store is not None:
            for d in decisions:
                await store.update_source_instance(
                    ctx.workspace_id,
                    d.source_id,
                    decision=d.decision,
                    status="cleanstack_done",
                )
            await store.save_cleanstack_report(ctx.workspace_id, report, job_id=ctx.job_id)
            await store.commit()

        ctx.emit(
            self.id,
            "cleanstack.done",
            f"Keep {len(keepers)} / {len(files)}; avoided {embeddings_avoided} embeds",
            progress=1.0,
            data={"tokens_avoided": tokens_avoided},
        )
        return AgentResult(
            ok=True,
            data=CleanStackOutput(keepers=keepers, decisions=decisions, report=report),
            metrics={
                "keepers": len(keepers),
                "exact_duplicates": exact_dupes,
                "near_duplicates": near_dupes,
                "embeddings_avoided": embeddings_avoided,
            },
        )


def _groups(decisions: list[CleanStackDecision]) -> list[dict]:
    by_key: dict[str, list[CleanStackDecision]] = defaultdict(list)
    for d in decisions:
        by_key[d.canonical_key or d.source_id].append(d)
    groups = []
    for key, items in by_key.items():
        if len(items) <= 1 and all(i.decision == "keep" for i in items):
            continue
        groups.append(
            {
                "canonical_key": key,
                "members": [i.model_dump() for i in items],
            }
        )
    return groups
