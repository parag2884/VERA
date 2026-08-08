from __future__ import annotations

from app.agents.base import AgentContext, AgentError, AgentResult
from app.agents.ingest.contracts import EmbedInput, EmbedOutput
from app.services.tokens import count_tokens
from app.stores.vector import VectorStore


class EmbedAgent:
    id = "embed"
    display_name = "Embed Agent"
    input_model = EmbedInput
    output_model = EmbedOutput

    async def run(self, ctx: AgentContext, payload: EmbedInput) -> AgentResult[EmbedOutput]:
        if ctx.llm is None:
            return AgentResult(
                ok=False,
                error=AgentError(code="NO_LLM", message="LLM/embed provider required"),
            )
        vector: VectorStore = ctx.config.get("vector_store") or VectorStore()
        chunks = [c for c in payload.chunks if c.id and c.text.strip()]
        if not chunks:
            return AgentResult(
                ok=True,
                data=EmbedOutput(embedded_count=0, tokens_embedded=0),
                metrics={"embedded": 0},
            )

        texts = [c.text for c in chunks]
        embeddings = await ctx.llm.embed(texts)
        items = [
            {
                "id": c.id,
                "text": c.text,
                "canonical_document_id": c.canonical_document_id,
                "document_title": c.document_title,
                "locator": (c.loc or {}).get("locator", ""),
            }
            for c in chunks
        ]
        count = await vector.upsert_chunks(ctx.workspace_id, items, embeddings)
        tokens = sum(c.token_estimate or count_tokens(c.text) for c in chunks)
        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"

        ctx.emit(self.id, "embed.done", f"Embedded {count} keeper chunks", progress=1.0)
        return AgentResult(
            ok=True,
            data=EmbedOutput(embedded_count=count, tokens_embedded=tokens),
            metrics={"embedded": count, "tokens": tokens},
        )
