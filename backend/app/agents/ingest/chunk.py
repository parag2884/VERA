from __future__ import annotations

from uuid import uuid4

from app.agents.base import AgentContext, AgentError, AgentResult
from app.agents.ingest.contracts import ChunkInput, ChunkOutput, ChunkRecord
from app.services.tokens import count_tokens


class ChunkAgent:
    id = "chunk"
    display_name = "Chunk Agent"
    input_model = ChunkInput
    output_model = ChunkOutput

    def __init__(self, chunk_size: int = 900, overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    async def run(self, ctx: AgentContext, payload: ChunkInput) -> AgentResult[ChunkOutput]:
        store = ctx.stores
        if store is None:
            return AgentResult(
                ok=False,
                error=AgentError(code="NO_STORE", message="Workspace store required"),
            )

        all_chunks: list[ChunkRecord] = []
        doc_ids: list[str] = []
        source_links: list[dict] = []

        for keeper in payload.keepers:
            existing = await store.find_canonical_by_text_hash(ctx.workspace_id, keeper.text_hash)
            if existing:
                doc_id = existing["id"]
            else:
                doc_id = await store.upsert_canonical_document(
                    ctx.workspace_id,
                    title=keeper.filename,
                    mime=keeper.mime,
                    text_hash=keeper.text_hash,
                    checksum=keeper.binary_hash,
                    char_count=len(keeper.text),
                )
            doc_ids.append(doc_id)

            # Link all sources that map to this canonical (keepers + skipped dupes)
            related = [
                d
                for d in payload.decisions
                if (d.canonical_key == keeper.text_hash)
                or (d.source_id == keeper.source_id)
            ]
            if not related:
                related_ids = [keeper.source_id]
            else:
                related_ids = [d.source_id for d in related]

            for sid in related_ids:
                await store.update_source_instance(
                    ctx.workspace_id,
                    sid,
                    canonical_document_id=doc_id,
                    status="materialized",
                )
                source_links.append(
                    {
                        "source_id": sid,
                        "canonical_document_id": doc_id,
                        "relation": "MATERIALIZES",
                    }
                )

            # Skip re-chunk if already chunked
            existing_chunks = await store.list_chunks(ctx.workspace_id, document_id=doc_id)
            if existing_chunks:
                for ch in existing_chunks:
                    all_chunks.append(
                        ChunkRecord(
                            id=ch["id"],
                            canonical_document_id=doc_id,
                            document_title=keeper.filename,
                            ordinal=ch["ordinal"],
                            text=ch["text"],
                            loc=ch.get("loc") or {},
                            char_start=ch.get("char_start") or 0,
                            char_end=ch.get("char_end") or 0,
                            token_estimate=ch.get("token_estimate") or 0,
                        )
                    )
                continue

            pieces = _chunk_text(keeper.text, self.chunk_size, self.overlap)
            for ordinal, (start, end, text) in enumerate(pieces):
                cid = str(uuid4())
                loc = {
                    "filename": keeper.filename,
                    "char_start": start,
                    "char_end": end,
                    "locator": f"chars {start}-{end}",
                }
                await store.insert_chunk(
                    ctx.workspace_id,
                    id=cid,
                    canonical_document_id=doc_id,
                    ordinal=ordinal,
                    text=text,
                    loc=loc,
                    char_start=start,
                    char_end=end,
                    token_estimate=count_tokens(text),
                )
                all_chunks.append(
                    ChunkRecord(
                        id=cid,
                        canonical_document_id=doc_id,
                        document_title=keeper.filename,
                        ordinal=ordinal,
                        text=text,
                        loc=loc,
                        char_start=start,
                        char_end=end,
                        token_estimate=count_tokens(text),
                    )
                )

        await store.commit()
        ctx.emit(self.id, "chunk.done", f"Created/loaded {len(all_chunks)} chunks", progress=1.0)
        return AgentResult(
            ok=True,
            data=ChunkOutput(
                canonical_document_ids=list(dict.fromkeys(doc_ids)),
                chunks=all_chunks,
                source_links=source_links,
            ),
            metrics={"chunks": len(all_chunks), "documents": len(set(doc_ids))},
        )


def _chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    if not text:
        return []
    chunks: list[tuple[int, int, str]] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        # prefer break on paragraph
        if end < n:
            window = text[start:end]
            br = window.rfind("\n\n")
            if br > size // 3:
                end = start + br
        piece = text[start:end].strip()
        if piece:
            chunks.append((start, end, piece))
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks
