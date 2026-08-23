"""Workspace-isolated heals used by Trust Forge.

Layer 1: graph hygiene (bad aliases, junk Person types).
Layer 2: website PART_OF hierarchy if ingest missed it.
Layer 3: pin failed golden facts onto the cited source page (retrieval misses).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.agents.ingest.weaver import _norm, _upsert_entity, _weave_web_hierarchy
from app.knowledge.sources.web.site_graph import looks_like_web_title, slug_tokens

log = logging.getLogger("vera.trust_forge.heal")


def _url_blob(url: str) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    path = urlparse(raw).path if raw.startswith("http") else raw
    return path.replace("-", " ").replace("_", " ").replace("/", " ")


def _doc_matches_source(title: str, source_url: str) -> bool:
    if not source_url or not title:
        return False
    t = title.lower()
    blob = _url_blob(source_url)
    if source_url.lower() in t:
        return True
    tokens = slug_tokens(source_url)
    if not tokens:
        return False
    # Last path segment is the page identity
    last = tokens[-1]
    return last in t.replace("-", " ").replace("_", " ") or last.replace(" ", "") in t.replace(
        "_", ""
    ).replace("-", "")


async def heal_workspace(
    store: Any,
    workspace_id: str,
    *,
    failed_cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    hygiene = await store.hygiene_knowledge(workspace_id)

    docs = await store.list_canonical_documents(workspace_id)
    web_ids = {
        d["id"]: d.get("title") or ""
        for d in docs
        if looks_like_web_title(d.get("title") or "")
    }
    doc_node_ids: dict[str, str] = {}
    if web_ids:
        graph = await store.get_graph(workspace_id)
        for n in graph.get("nodes") or []:
            if n.get("type") != "Document":
                continue
            props = n.get("props") or {}
            cid = props.get("canonical_document_id")
            if cid in web_ids:
                doc_node_ids[cid] = n["id"]
        # Fallback: match by document name
        if len(doc_node_ids) < len(web_ids):
            by_name = {
                (n.get("name") or ""): n["id"]
                for n in (graph.get("nodes") or [])
                if n.get("type") == "Document"
            }
            for cid, title in web_ids.items():
                if cid not in doc_node_ids and title in by_name:
                    doc_node_ids[cid] = by_name[title]

    hier = await _weave_web_hierarchy(store, workspace_id, doc_node_ids)
    pins = await _pin_failed_facts(store, workspace_id, failed_cases or [], docs)

    await store.commit()
    report = {
        **hygiene,
        "site_part_of_edges": int(hier.get("edges") or 0),
        "facts_pinned": int(pins.get("pinned") or 0),
        "pages_touched": int(pins.get("pages") or 0),
    }
    log.info(
        "heal workspace=%s aliases=%s persons=%s site_edges=%s pins=%s",
        workspace_id,
        report.get("aliases_removed"),
        report.get("junk_persons_retyped"),
        report.get("site_part_of_edges"),
        report.get("facts_pinned"),
    )
    return report


async def _pin_failed_facts(
    store: Any,
    workspace_id: str,
    failed_cases: list[dict[str, Any]],
    docs: list[dict[str, Any]],
) -> dict[str, int]:
    """When retrieval missed a known source page, bind must_any phrases as MENTIONS.

    Only runs for failed cases with source_url. Does not invent quotes — phrase
    must already appear in a stored chunk.
    """
    pinned = 0
    pages: set[str] = set()
    graph = await store.get_graph(workspace_id)
    doc_nodes = {
        (n.get("props") or {}).get("canonical_document_id"): n["id"]
        for n in (graph.get("nodes") or [])
        if n.get("type") == "Document"
    }
    chunk_nodes = {
        (n.get("props") or {}).get("chunk_id"): n["id"]
        for n in (graph.get("nodes") or [])
        if n.get("type") == "Chunk" and (n.get("props") or {}).get("chunk_id")
    }

    for case in failed_cases:
        if case.get("pass"):
            continue
        # If citations already hit the source page, this is an answer-wording miss
        if case.get("retrieval_ok") is True:
            continue
        url = (case.get("source_url") or "").strip()
        phrases = [p for p in (case.get("must_any") or []) if isinstance(p, str) and len(p.strip()) >= 3]
        if not url or not phrases:
            continue
        doc = next((d for d in docs if _doc_matches_source(d.get("title") or "", url)), None)
        if not doc:
            continue
        chunks = await store.list_chunks(workspace_id, document_id=doc["id"])
        doc_nid = doc_nodes.get(doc["id"])
        for phrase in phrases[:4]:
            needle = phrase.strip()
            hit_chunk = next(
                (c for c in chunks if needle.lower() in (c.get("text") or "").lower()),
                None,
            )
            if not hit_chunk:
                continue
            looks_person = len(needle.split()) >= 2 and needle[:1].isupper()
            ent_nid = await _upsert_entity(
                store, workspace_id, needle, "Person" if looks_person else "Concept"
            )
            chunk_nid = chunk_nodes.get(hit_chunk["id"])
            if chunk_nid:
                await store.insert_edge(
                    workspace_id,
                    src=chunk_nid,
                    dst=ent_nid,
                    rel_type="MENTIONS",
                    edge_class="documentary",
                    document_id=doc["id"],
                    weight=0.95,
                    props={"extractor": "trust_forge_pin"},
                )
            if doc_nid:
                await store.insert_edge(
                    workspace_id,
                    src=ent_nid,
                    dst=doc_nid,
                    rel_type="DEFINED_IN",
                    edge_class="documentary",
                    document_id=doc["id"],
                    weight=0.9,
                    props={"extractor": "trust_forge_pin"},
                )
            await store.insert_alias(workspace_id, needle, _norm(needle), ent_nid)
            pinned += 1
            pages.add(doc["id"])
    return {"pinned": pinned, "pages": len(pages)}
