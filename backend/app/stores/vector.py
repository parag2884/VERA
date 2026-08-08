from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)


def local_embed(texts: list[str], dim: int = 384) -> list[list[float]]:
    """Deterministic fallback embedding — demo-safe when Azure embeddings absent."""
    vectors: list[list[float]] = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(dim).astype(np.float32)
        # Light bag-of-words nudge for near-duplicate detection
        for token in set(text.lower().split()):
            tseed = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
            vec[tseed % dim] += 1.0
        norm = float(np.linalg.norm(vec)) or 1.0
        vectors.append((vec / norm).tolist())
    return vectors


class VectorStore:
    """Chroma quote store. Every query MUST filter workspace_id (+ optional chunk ids)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._collection = None
        self._memory: dict[str, dict[str, Any]] = {}

    def _ensure(self) -> None:
        if self._collection is not None or self.settings.vera_vector_backend == "none":
            return
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self._client = chromadb.PersistentClient(
                path=self.settings.chroma_dir.as_posix(),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="vera_chunks",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma unavailable, using in-memory vectors: %s", exc)
            self._collection = None

    async def upsert_chunks(
        self,
        workspace_id: str,
        items: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int:
        if not items:
            return 0
        self._ensure()
        ids = [f"{workspace_id}:{it['id']}" for it in items]
        documents = [it["text"] for it in items]
        metadatas = [
            {
                "workspace_id": workspace_id,
                "chunk_id": it["id"],
                "document_id": it["canonical_document_id"],
                "document_title": it.get("document_title", ""),
                "locator": it.get("locator", ""),
            }
            for it in items
        ]
        if self._collection is not None:
            self._collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        else:
            for i, it in enumerate(items):
                self._memory[ids[i]] = {
                    "embedding": embeddings[i],
                    "document": documents[i],
                    "metadata": metadatas[i],
                }
        return len(items)

    async def query(
        self,
        workspace_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 6,
        chunk_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Storage-layer guarantee: workspace filter always applied."""
        self._ensure()
        if self._collection is not None:
            where: dict[str, Any]
            if chunk_ids:
                where = {
                    "$and": [
                        {"workspace_id": workspace_id},
                        {"chunk_id": {"$in": chunk_ids}},
                    ]
                }
            else:
                where = {"workspace_id": workspace_id}
            try:
                result = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k, max(len(chunk_ids) if chunk_ids else top_k, 1)),
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma query failed: %s", exc)
                return []
            hits: list[dict[str, Any]] = []
            if not result or not result.get("ids"):
                return hits
            for i, _id in enumerate(result["ids"][0]):
                meta = result["metadatas"][0][i] or {}
                dist = result["distances"][0][i] if result.get("distances") else 1.0
                hits.append(
                    {
                        "chunk_id": meta.get("chunk_id"),
                        "document_id": meta.get("document_id"),
                        "document_title": meta.get("document_title", ""),
                        "locator": meta.get("locator", ""),
                        "text": result["documents"][0][i],
                        "score": 1.0 - float(dist),
                    }
                )
            return hits

        # In-memory cosine
        q = np.array(query_embedding, dtype=np.float32)
        scored: list[tuple[float, dict[str, Any]]] = []
        for _id, row in self._memory.items():
            meta = row["metadata"]
            if meta.get("workspace_id") != workspace_id:
                continue
            if chunk_ids and meta.get("chunk_id") not in chunk_ids:
                continue
            v = np.array(row["embedding"], dtype=np.float32)
            score = float(np.dot(q, v) / ((np.linalg.norm(q) * np.linalg.norm(v)) or 1.0))
            scored.append(
                (
                    score,
                    {
                        "chunk_id": meta.get("chunk_id"),
                        "document_id": meta.get("document_id"),
                        "document_title": meta.get("document_title", ""),
                        "locator": meta.get("locator", ""),
                        "text": row["document"],
                        "score": score,
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:top_k]]

    async def delete_workspace(self, workspace_id: str) -> int:
        """Remove all vectors for a workspace."""
        self._ensure()
        removed = 0
        if self._collection is not None:
            try:
                existing = self._collection.get(
                    where={"workspace_id": workspace_id},
                    include=[],
                )
                ids = existing.get("ids") or []
                if ids:
                    self._collection.delete(ids=ids)
                    removed = len(ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma workspace delete failed: %s", exc)
        stale = [k for k, v in self._memory.items() if v["metadata"].get("workspace_id") == workspace_id]
        for k in stale:
            del self._memory[k]
            removed += 1
        return removed
