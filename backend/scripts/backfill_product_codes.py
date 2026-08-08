"""Backfill alphanumeric product/level codes (SL2000, …) as KG nodes + MENTIONS.

Run inside API container:
  PYTHONPATH=/app python scripts/backfill_product_codes.py [workspace_id]
"""
from __future__ import annotations

import asyncio
import re
import sys

from app.agents.ingest import weaver as w
from app.stores.sql import WorkspaceStore


async def main() -> None:
    ws = sys.argv[1] if len(sys.argv) > 1 else "31509630-c427-40c4-b182-e1f63fe8c91b"
    async with WorkspaceStore() as store:
        chunks = await store.list_chunks(ws)
        seen: set[str] = set()
        nodes = 0
        mentions = 0
        for ch in chunks:
            text = ch.get("text") or ""
            hits = w._rule_entities(text)
            for ent in hits:
                name = ent["name"]
                if not (
                    re.fullmatch(r"[A-Z]{1,8}\d{2,4}", name)
                    or re.search(r"level\s+\d{2,4}", name, re.I)
                ):
                    continue
                key = w._norm(name)
                ent_nid = await w._upsert_entity(store, ws, name, ent["type"])
                if key not in seen:
                    seen.add(key)
                    nodes += 1
                for alias in ent.get("aliases") or []:
                    await store.insert_alias(ws, alias, w._norm(alias), ent_nid)
                cur = await store.conn.execute(
                    """SELECT id FROM kg_nodes WHERE workspace_id=? AND normalized_name=?
                       LIMIT 1""",
                    (ws, f"chunk:{ch['id']}"),
                )
                row = await cur.fetchone()
                if not row:
                    continue
                eid = await store.insert_edge(
                    ws,
                    src=row["id"],
                    dst=ent_nid,
                    rel_type="MENTIONS",
                    edge_class="documentary",
                    document_id=ch.get("canonical_document_id"),
                )
                if not eid:
                    continue
                mentions += 1
                span = w._span_for(text, name)
                await store.insert_edge_evidence(
                    ws,
                    edge_id=eid,
                    source_chunk_id=ch["id"],
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=text[span[0] : span[1]],
                    extractor="backfill_codes",
                    confidence=0.9,
                )
        await store.commit()
        print(f"unique_codes={len(seen)} newish_nodes={nodes} mentions={mentions}")


if __name__ == "__main__":
    asyncio.run(main())
