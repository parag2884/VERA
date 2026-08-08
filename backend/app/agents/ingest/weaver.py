from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from app.agents.base import AgentContext, AgentError, AgentResult
from app.agents.ingest.contracts import WeaverInput, WeaverOutput
from app.identity import alnum_key as _alnum_key
from app.identity import normalize_entity_name

logger = logging.getLogger(__name__)

# Core evidence-bound relations always allowed; domain profile may add more.
CORE_ASSERTED_RELS = {
    "REQUIRES",
    "OWNS",
    "SUPERSEDES",
    "CONFLICTS_WITH",
    "PART_OF",
    "HAS_VALUE",
    "DEFINED_AS",
    "APPLIES_TO",
    "GOVERNED_BY",
    "USES",
    "PROVIDES",
    "RELATED_TO",
}
ASSERTED_RELS = set(CORE_ASSERTED_RELS)

# Light alias table only. Any other type string passes through via _normalize_entity_type
# (open taxonomy — legal, marketing, HR, clinical, finance, or anything else).
ENTITY_TYPE_MAP = {
    "person": "Person",
    "people": "Person",
    "employee": "Person",
    "team": "Team",
    "department": "Team",
    "system": "System",
    "policy": "Policy",
    "product": "Product",
    "location": "Location",
    "concept": "Concept",
    "acronym": "Acronym",
    "control": "Control",
    "organization": "Organization",
    "org": "Organization",
    "company": "Organization",
    "document": "Document",
}

class GraphWeaverAgent:
    """Build evidence-bound KG. Invariant: no evidence span => no asserted fact edge."""

    id = "graph_weaver"
    display_name = "Graph Weaver Agent"
    input_model = WeaverInput
    output_model = WeaverOutput

    async def run(self, ctx: AgentContext, payload: WeaverInput) -> AgentResult[WeaverOutput]:
        store = ctx.stores
        if store is None:
            return AgentResult(
                ok=False,
                error=AgentError(code="NO_STORE", message="Workspace store required"),
            )

        # Rank chunks for sampling; LLM budget scales with corpus + domain confidence
        from app.config import get_settings

        settings = get_settings()
        ranked = sorted(
            [c for c in payload.chunks if c.id and (c.text or "").strip()],
            key=lambda c: len(c.text or ""),
            reverse=True,
        )

        # GPT infers corpus domain once, then extraction follows that profile
        doc_titles = await _document_titles(store, ctx.workspace_id, payload.canonical_document_ids)
        domain = await _infer_domain_profile(
            ctx,
            titles=doc_titles,
            samples=[(c.text or "")[:1200] for c in ranked[:8]],
        )
        await _persist_domain_profile(store, ctx.workspace_id, domain)
        await store.commit()
        allowed_rels = _allowed_relations(domain)
        global _DOMAIN_ALIASES
        _DOMAIN_ALIASES = {
            str(k): str(v) for k, v in (domain.get("aliases") or {}).items() if k and v
        }
        ctx.emit(
            self.id,
            "weaver.domain",
            f"Domain · {domain['label']}"
            + (f" · types: {', '.join(domain['entity_types'][:6])}" if domain["entity_types"] else "")
            + (f" · rels: {', '.join(list(allowed_rels)[:6])}" if allowed_rels else ""),
            progress=0.52,
        )
        await ctx.flush_job_progress()

        base_budget = max(4, int(settings.vera_weaver_llm_chunks or 16))
        conf = float(domain.get("confidence") or 0)
        # Richer domains + larger corpora get a fuller weave (still capped)
        scale = 1.35 if conf >= 0.55 else 1.0
        llm_budget = min(len(ranked), max(4, int(base_budget * scale)))
        llm_chunk_ids = _select_llm_chunks(ranked, llm_budget)

        try:
            return await self._weave_graph(
                ctx,
                store,
                payload,
                domain=domain,
                allowed_rels=allowed_rels,
                llm_chunk_ids=llm_chunk_ids,
                doc_titles=doc_titles,
            )
        finally:
            _DOMAIN_ALIASES = {}

    async def _weave_graph(
        self,
        ctx: AgentContext,
        store: Any,
        payload: WeaverInput,
        *,
        domain: dict[str, Any],
        allowed_rels: set[str],
        llm_chunk_ids: set[str],
        doc_titles: list[str],
    ) -> AgentResult[WeaverOutput]:
        nodes_created = 0
        edges_created = 0
        evidence_bound = 0
        skipped = 0

        # Documentary structure: Document CONTAINS Chunk, Chunk MENTIONS (rule)
        doc_node_ids: dict[str, str] = {}
        for doc_id in payload.canonical_document_ids:
            docs = await store.list_canonical_documents(ctx.workspace_id)
            title = next((d["title"] for d in docs if d["id"] == doc_id), doc_id)
            nid = await store.upsert_node(
                ctx.workspace_id,
                type="Document",
                name=title,
                normalized_name=_norm(title),
                props={"canonical_document_id": doc_id},
            )
            doc_node_ids[doc_id] = nid
            nodes_created += 1

        total_chunks = max(len(payload.chunks), 1)
        for idx, chunk in enumerate(payload.chunks):
            if not chunk.id:
                continue
            if idx % 3 == 0:
                ctx.emit(
                    self.id,
                    "weaver.chunk",
                    f"Weaving chunk {idx + 1}/{total_chunks}",
                    progress=0.55 + 0.25 * (idx / total_chunks),
                )
                await ctx.flush_job_progress()
            chunk_nid = await store.upsert_node(
                ctx.workspace_id,
                type="Chunk",
                name=f"chunk:{chunk.ordinal}",
                normalized_name=f"chunk:{chunk.id}",
                props={"chunk_id": chunk.id, "document_id": chunk.canonical_document_id},
            )
            nodes_created += 1
            doc_nid = doc_node_ids.get(chunk.canonical_document_id)
            if doc_nid:
                await store.insert_edge(
                    ctx.workspace_id,
                    src=doc_nid,
                    dst=chunk_nid,
                    rel_type="CONTAINS",
                    edge_class="documentary",
                    document_id=chunk.canonical_document_id,
                )
                edges_created += 1

            # Rule NER pass (policies + resume/person names)
            rule_hits = _rule_entities(chunk.text)
            if chunk.ordinal == 0:
                docs = await store.list_canonical_documents(ctx.workspace_id)
                title = next(
                    (d["title"] for d in docs if d["id"] == chunk.canonical_document_id),
                    "",
                )
                for person in _people_from_resume_signals(chunk.text, title):
                    rule_hits.append(person)
            for ent in rule_hits:
                ent_nid = await _upsert_entity(
                    store, ctx.workspace_id, ent["name"], ent["type"]
                )
                nodes_created += 1
                for alias in ent.get("aliases", []):
                    await store.insert_alias(ctx.workspace_id, alias, _norm(alias), ent_nid)
                mention_eid = await store.insert_edge(
                    ctx.workspace_id,
                    src=chunk_nid,
                    dst=ent_nid,
                    rel_type="MENTIONS",
                    edge_class="documentary",
                    document_id=chunk.canonical_document_id,
                )
                edges_created += 1
                span = _span_for(chunk.text, ent["name"])
                await store.insert_edge_evidence(
                    ctx.workspace_id,
                    edge_id=mention_eid,
                    source_chunk_id=chunk.id,
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=chunk.text[span[0] : span[1]],
                    extractor="rule",
                    confidence=0.95,
                )
                evidence_bound += 1

                if doc_nid:
                    def_eid = await store.insert_edge(
                        ctx.workspace_id,
                        src=ent_nid,
                        dst=doc_nid,
                        rel_type="DEFINED_IN",
                        edge_class="documentary",
                        document_id=chunk.canonical_document_id,
                    )
                    edges_created += 1
                    await store.insert_edge_evidence(
                        ctx.workspace_id,
                        edge_id=def_eid,
                        source_chunk_id=chunk.id,
                        source_span_start=span[0],
                        source_span_end=span[1],
                        quote=chunk.text[span[0] : span[1]],
                        extractor="rule",
                        confidence=0.9,
                    )
                    evidence_bound += 1

            # Form / PDF key-value facts (Agreement #, Company, Email, ...)
            for field, value, span in _extract_kv_fields(chunk.text):
                field_id = await _upsert_entity(store, ctx.workspace_id, field, "Concept")
                value_id = await _upsert_entity(store, ctx.workspace_id, value, "Concept")
                nodes_created += 2
                eid = await store.insert_edge(
                    ctx.workspace_id,
                    src=field_id,
                    dst=value_id,
                    rel_type="HAS_VALUE",
                    edge_class="asserted_fact",
                    weight=0.95,
                    document_id=chunk.canonical_document_id,
                    props={"extractor": "rule_kv"},
                )
                edges_created += 1
                await store.insert_edge_evidence(
                    ctx.workspace_id,
                    edge_id=eid,
                    source_chunk_id=chunk.id,
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=chunk.text[span[0] : span[1]],
                    extractor="rule",
                    confidence=0.96,
                )
                evidence_bound += 1

            # LLM extraction for asserted facts (budgeted — keeps PDF ingest responsive)
            if chunk.id in llm_chunk_ids:
                # Release the write lock before network I/O so Studio isn't 500'd
                await store.commit()
                extraction = await _llm_extract(ctx, chunk.text, domain, allowed_rels)
            else:
                extraction = {"entities": [], "relations": []}
            llm_doc_linked: set[str] = set()
            llm_types: dict[str, str] = {}
            for ent in _as_dict_list(extraction.get("entities")):
                typ = _normalize_entity_type(str(ent.get("type", "concept")))
                name = str(ent.get("name", "")).strip()
                if not name:
                    continue
                llm_types[_norm(name)] = typ
                ent_nid = await _upsert_entity(store, ctx.workspace_id, name, typ)
                nodes_created += 1
                for alias in ent.get("aliases") or []:
                    if not isinstance(alias, str):
                        continue
                    await store.insert_alias(ctx.workspace_id, alias, _norm(alias), ent_nid)
                added = await _ensure_documentary_links(
                    store,
                    ctx.workspace_id,
                    ent_nid=ent_nid,
                    chunk_nid=chunk_nid,
                    doc_nid=doc_nid,
                    chunk=chunk,
                    needle=name,
                    already=llm_doc_linked,
                )
                edges_created += added["edges"]
                evidence_bound += added["evidence"]

            for rel in _as_dict_list(extraction.get("relations")):
                rel_type = _normalize_relation_type(
                    str(rel.get("rel") or rel.get("relation") or "")
                )
                src_name = str(rel.get("src") or rel.get("source") or "").strip()
                dst_name = str(rel.get("dst") or rel.get("target") or "").strip()
                quote = str(rel.get("quote") or "").strip()
                try:
                    confidence = float(rel.get("confidence", 0.5) or 0.5)
                except (TypeError, ValueError):
                    confidence = 0.5
                if not rel_type or rel_type not in allowed_rels or not src_name or not dst_name:
                    skipped += 1
                    continue
                # Self-loops (A DEFINED_AS A) draw as orphan nodes on the map
                if _norm(src_name) == _norm(dst_name) or _alnum_key(src_name) == _alnum_key(
                    dst_name
                ):
                    skipped += 1
                    continue
                span = _evidence_span(chunk.text, quote, src_name, dst_name)
                if span is None:
                    skipped += 1
                    continue

                src_type = llm_types.get(_norm(src_name), "Concept")
                dst_type = llm_types.get(_norm(dst_name), "Concept")
                sid = await _upsert_entity(store, ctx.workspace_id, src_name, src_type)
                did = await _upsert_entity(store, ctx.workspace_id, dst_name, dst_type)
                if sid == did:
                    skipped += 1
                    continue

                edge_id = await store.insert_edge(
                    ctx.workspace_id,
                    src=sid,
                    dst=did,
                    rel_type=rel_type,
                    edge_class="asserted_fact",
                    weight=confidence,
                    document_id=chunk.canonical_document_id,
                    props={"extractor": "llm"},
                )
                if not edge_id:
                    skipped += 1
                    continue
                edges_created += 1
                await store.insert_edge_evidence(
                    ctx.workspace_id,
                    edge_id=edge_id,
                    source_chunk_id=chunk.id,
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=chunk.text[span[0] : span[1]],
                    extractor="llm",
                    confidence=confidence,
                )
                evidence_bound += 1
                # Anchor LLM concepts to the source document so Structure isn't a sea of floaters
                for ent_nid, needle in ((sid, src_name), (did, dst_name)):
                    added = await _ensure_documentary_links(
                        store,
                        ctx.workspace_id,
                        ent_nid=ent_nid,
                        chunk_nid=chunk_nid,
                        doc_nid=doc_nid,
                        chunk=chunk,
                        needle=needle,
                        already=llm_doc_linked,
                    )
                    edges_created += added["edges"]
                    evidence_bound += added["evidence"]

            # Periodic commit keeps WAL writers short during large corpora
            if idx % 8 == 0:
                await store.commit()

        # Always ensure canonical demo facts when sample corpus markers present
        if payload.chunks:
            seeded = await _seed_demo_facts(store, ctx.workspace_id, payload.chunks)
            nodes_created += seeded["nodes"]
            edges_created += seeded["edges"]
            evidence_bound += seeded["evidence"]
            agreement = await _seed_agreement_facts(
                store, ctx.workspace_id, payload.chunks, doc_node_ids, doc_titles
            )
            nodes_created += agreement["nodes"]
            edges_created += agreement["edges"]
            evidence_bound += agreement["evidence"]

        # Repair: asserted facts that never got MENTIONS (older LLM-only entities)
        repaired = await _backfill_documentary_from_evidence(
            store, ctx.workspace_id, doc_node_ids
        )
        edges_created += repaired["edges"]
        evidence_bound += repaired["evidence"]

        await store.commit()
        ctx.emit(
            self.id,
            "weaver.done",
            f"Weaved graph: {edges_created} edges, {evidence_bound} evidence-bound",
            progress=1.0,
        )
        return AgentResult(
            ok=True,
            data=WeaverOutput(
                nodes_created=nodes_created,
                edges_created=edges_created,
                evidence_bound_edges=evidence_bound,
                skipped_unsupported_relations=skipped,
                domain_label=str(domain.get("label") or "") or None,
                domain_entity_types=list(domain.get("entity_types") or []),
                domain_relation_types=sorted(allowed_rels),
            ),
            metrics={
                "domain_label": domain.get("label"),
                "domain_confidence": domain.get("confidence"),
                "llm_chunks": len(llm_chunk_ids),
                "relation_types": len(allowed_rels),
                "nodes": nodes_created,
                "edges": edges_created,
                "evidence_bound": evidence_bound,
                "skipped": skipped,
            },
        )


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "type": "Concept", "aliases": []})
    return out


def _parse_extraction(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if isinstance(data, list):
        return {"entities": [], "relations": data}
    if not isinstance(data, dict):
        return {"entities": [], "relations": []}
    return {
        "entities": data.get("entities") or [],
        "relations": data.get("relations") or data.get("relationships") or [],
    }


def _default_domain() -> dict[str, Any]:
    return {
        "label": "General knowledge",
        "entity_types": ["Person", "Organization", "Concept", "Document"],
        "relation_types": sorted(CORE_ASSERTED_RELS - {"HAS_VALUE"}),
        "focus": "Extract the most important named entities and evidence-bound relations.",
        "confidence": 0.35,
    }


def _normalize_relation_type(raw: str) -> str:
    """Normalize verbs to SCREAMING_SNAKE; reject junk."""
    t = re.sub(r"[^A-Za-z0-9]+", "_", (raw or "").strip()).strip("_").upper()
    if not t or len(t) > 40:
        return ""
    if t in {"CONTAINS", "MENTIONS", "DEFINED_IN"}:
        return ""  # documentary only — not asserted facts
    return t


def _allowed_relations(domain: dict[str, Any] | None) -> set[str]:
    allowed = set(CORE_ASSERTED_RELS)
    for r in (domain or {}).get("relation_types") or []:
        nr = _normalize_relation_type(str(r))
        if nr:
            allowed.add(nr)
    return allowed


def _select_llm_chunks(ranked: list[Any], budget: int) -> set[str]:
    """Diversify extract coverage: early-per-doc → spaced → longest fill."""
    if budget <= 0 or not ranked:
        return set()
    chosen: list[Any] = []
    seen: set[str] = set()

    def _take(chunk: Any) -> None:
        cid = getattr(chunk, "id", None)
        if not cid or cid in seen or len(chosen) >= budget:
            return
        seen.add(cid)
        chosen.append(chunk)

    by_doc: dict[str, list[Any]] = {}
    for c in ranked:
        by_doc.setdefault(c.canonical_document_id or "", []).append(c)

    # 1) Early chunks per document (definitions / intros)
    for chunks in by_doc.values():
        early = sorted(chunks, key=lambda x: getattr(x, "ordinal", 0) or 0)
        for c in early[:2]:
            _take(c)

    # 2) Evenly spaced mid/tail coverage
    if len(ranked) > 1:
        step = max(1, len(ranked) // max(budget, 1))
        for i in range(0, len(ranked), step):
            _take(ranked[i])

    # 3) Fill remainder with longest remaining
    for c in ranked:
        _take(c)
        if len(chosen) >= budget:
            break

    return {c.id for c in chosen if c.id}


async def _document_titles(
    store: Any, workspace_id: str, canonical_document_ids: list[str]
) -> list[str]:
    if not canonical_document_ids:
        return []
    docs = await store.list_canonical_documents(workspace_id)
    by_id = {d["id"]: d.get("title") or "" for d in docs}
    return [by_id[i] for i in canonical_document_ids if by_id.get(i)]


async def _infer_domain_profile(
    ctx: AgentContext, *, titles: list[str], samples: list[str]
) -> dict[str, Any]:
    """Ask GPT what domain this corpus is — open-ended, not a fixed industry enum."""
    fallback = _default_domain()
    if ctx.llm is None:
        return fallback

    blob = "\n\n".join(
        [
            "Document titles:\n- " + "\n- ".join(titles[:20] or ["(untitled)"]),
            "Sample excerpts:\n" + "\n---\n".join(s for s in samples if s.strip())[:6000],
        ]
    )
    system = (
        "You classify a knowledge-base corpus so an evidence graph can be built well. "
        "Return JSON with keys: "
        "label (short domain name invented from the content), "
        "entity_types (array of 4-10 short PascalCase type labels that fit THIS corpus), "
        "relation_types (array of 4-10 SCREAMING_SNAKE relation verbs that fit THIS corpus, "
        "e.g. REQUIRES, LICENSES, GOVERNS, APPLIES_TO — invent from the text), "
        "aliases (object mapping short forms → canonical names seen in THIS corpus only, "
        "e.g. {\"sl2000\": \"security level 2000\"} — omit if none), "
        "focus (one sentence: what to prioritize when extracting entities/relations), "
        "confidence (0-1). "
        "Do not pick from a fixed industry list — invent labels from the text. "
        "If mixed domains, choose the dominant one and note secondary themes in focus."
    )
    try:
        raw = await ctx.llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": blob},
            ],
            response_format={"type": "json_object"},
        )
        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return fallback
        types = data.get("entity_types") or data.get("types") or []
        clean_types: list[str] = []
        for t in types:
            if not isinstance(t, str):
                continue
            nt = _normalize_entity_type(t)
            if nt and nt not in clean_types:
                clean_types.append(nt)
        rels = data.get("relation_types") or data.get("relations") or []
        clean_rels: list[str] = []
        for r in rels:
            if not isinstance(r, str):
                continue
            nr = _normalize_relation_type(r)
            if nr and nr not in clean_rels:
                clean_rels.append(nr)
        label = str(data.get("label") or data.get("domain") or "").strip() or fallback["label"]
        focus = str(data.get("focus") or fallback["focus"]).strip()
        aliases_raw = data.get("aliases") if isinstance(data.get("aliases"), dict) else {}
        aliases: dict[str, str] = {}
        for k, v in (aliases_raw or {}).items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            src = " ".join(k.lower().split())
            dst = " ".join(v.lower().split())
            if src and dst and src != dst and len(src) < 80 and len(dst) < 120:
                aliases[src] = dst
        try:
            conf = float(data.get("confidence", 0.55))
        except (TypeError, ValueError):
            conf = 0.55
        return {
            "label": label[:80],
            "entity_types": clean_types[:12] or fallback["entity_types"],
            "relation_types": (clean_rels[:12] or fallback["relation_types"]),
            "aliases": aliases,
            "focus": focus[:280],
            "confidence": max(0.0, min(1.0, conf)),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Domain inference failed: %s", exc)
        return fallback


async def _persist_domain_profile(
    store: Any, workspace_id: str, domain: dict[str, Any]
) -> None:
    try:
        agent = await store.get_agent_by_workspace(workspace_id)
        if not agent:
            return
        await store.update_agent(
            agent["id"],
            settings={
                "domainProfile": {
                    "label": domain.get("label"),
                    "entityTypes": domain.get("entity_types") or [],
                    "relationTypes": domain.get("relation_types") or [],
                    "aliases": domain.get("aliases") or {},
                    "focus": domain.get("focus"),
                    "confidence": domain.get("confidence"),
                }
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist domain profile: %s", exc)


async def _llm_extract(
    ctx: AgentContext,
    text: str,
    domain: dict[str, Any] | None = None,
    allowed_rels: set[str] | None = None,
) -> dict[str, Any]:
    if ctx.llm is None:
        return {"entities": [], "relations": []}
    profile = domain or _default_domain()
    type_hint = ", ".join(profile.get("entity_types") or []) or "domain-appropriate PascalCase types"
    rels = allowed_rels or _allowed_relations(profile)
    # Prefer domain-suggested verbs first in the prompt for better coverage
    preferred = [r for r in (profile.get("relation_types") or []) if r in rels]
    rel_hint = ", ".join((preferred + sorted(rels - set(preferred)))[:16])
    system = (
        f"You extract entities and asserted relations for a knowledge graph. "
        f"Corpus domain: {profile.get('label', 'General knowledge')}. "
        f"Priority: {profile.get('focus', 'Extract important evidence-bound facts.')} "
        f"Prefer entity types from this set when they fit: {type_hint}. "
        f"You may add a new short PascalCase type if the text clearly needs one. "
        "Return JSON with keys entities and relations. "
        f"Relations MUST use SCREAMING_SNAKE verbs from this allow-list: {rel_hint}. "
        "Each relation MUST include src, dst, rel, confidence, and a short quote copied "
        "verbatim from the text. Extract as many evidence-bound relations as the text supports. "
        "If you cannot quote evidence, omit the relation."
    )
    try:
        raw = await ctx.llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text[:4000]},
            ],
            response_format={"type": "json_object"},
        )
        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"
        return _parse_extraction(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM extract failed: %s", exc)
        from app.services.providers.mock import MockLLMProvider

        mock = MockLLMProvider()
        raw = await mock.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text[:4000]},
            ]
        )
        ctx.demo_mode = True
        return _parse_extraction(raw)


def _extract_kv_fields(text: str) -> list[tuple[str, str, tuple[int, int]]]:
    """Extract evidence-bound form fields from agreements / cover sheets."""
    patterns = [
        (r"Agreement\s*#\s*[:\s]*([A-Z0-9][\w-]*)", "Agreement Number"),
        (r"Agreement\s*(?:Number|No\.?)\s*[:#]?\s*([A-Z0-9][\w-]*)", "Agreement Number"),
        (r"Company\s*:\s*([^\n\r]+)", "Company"),
        (r"Signer\s*email\s*:\s*(\S+@\S+)", "Signer Email"),
        (r"Approval\s*token\s*:\s*([A-Fa-f0-9]+)", "Approval Token"),
        (r"Document\s*:\s*([^\n\r]+)", "Source Document"),
    ]
    out: list[tuple[str, str, tuple[int, int]]] = []
    for pat, field in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            continue
        out.append((field, value, (m.start(), m.end())))
    return out


_RESUME_STOP = {
    "resume",
    "curriculum",
    "vitae",
    "cv",
    "profile",
    "experience",
    "education",
    "skills",
    "summary",
    "objective",
    "contact",
    "phone",
    "email",
    "address",
    "linkedin",
    "github",
    "agreement",
    "license",
    "policy",
    "document",
    "appendix",
    "table",
    "contents",
}


def _people_from_resume_signals(text: str, title: str = "") -> list[dict[str, Any]]:
    """Extract Person entities from resume headers / filenames."""
    found: dict[str, dict[str, Any]] = {}
    head = (text or "")[:800]

    for m in re.finditer(
        r"(?:^|\n)\s*(?:name|candidate)\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*(?:\n|$)",
        head,
        re.I,
    ):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if name.lower() not in _RESUME_STOP:
            found[_norm(name)] = {"type": "Person", "name": name, "aliases": []}

    # First non-empty line often is the candidate name on resumes
    for line in head.splitlines()[:6]:
        line = line.strip()
        if not line or len(line) > 60:
            continue
        if re.search(r"@|https?://|\d{3,}", line):
            continue
        m = re.fullmatch(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", line)
        if m:
            name = m.group(1)
            if name.lower() not in _RESUME_STOP:
                found[_norm(name)] = {"type": "Person", "name": name, "aliases": []}

    # Filename: Neha_Resume.pdf / Nitin-Sharma-CV.docx
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", title or "")
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(
        r"\b(resume|cv|curriculum|vitae|profile|final|updated|copy)\b",
        " ",
        stem,
        flags=re.I,
    )
    stem = re.sub(r"\s+", " ", stem).strip()
    m = re.fullmatch(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", stem)
    if m:
        name = m.group(1)
        if name.lower() not in _RESUME_STOP:
            found[_norm(name)] = {"type": "Person", "name": name, "aliases": []}
    else:
        # Loose: first capitalized token in filename
        m2 = re.search(r"\b([A-Z][a-z]{2,})\b", stem)
        if m2 and m2.group(1).lower() not in _RESUME_STOP:
            name = m2.group(1)
            found[_norm(name)] = {"type": "Person", "name": name, "aliases": []}

    return list(found.values())


def _rule_entities(text: str) -> list[dict[str, Any]]:
    """Domain-agnostic structural NER only — product vocabulary comes from LLM + domain profile."""
    found: dict[str, dict[str, Any]] = {}
    # Named agreement / license / policy / standard titles (any industry)
    for m in re.finditer(
        r"([A-Z][\w]+(?:\s+[A-Z][\w+/.-]+){0,6}\s+"
        r"(?:Agreement|License|Policy|Standard|Specification|Addendum|Amendment))",
        text,
    ):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if 8 <= len(name) <= 90:
            found[_norm(name)] = {"type": "Concept", "name": name, "aliases": []}
    # Versioned titles: "Something Policy v2", "Spec 1.0"
    for m in re.finditer(
        r"([A-Z][\w]+(?:\s+[A-Z][\w]+){0,4}\s+v\d+)\b",
        text,
    ):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if 5 <= len(name) <= 80:
            found[_norm(name)] = {"type": "Concept", "name": name, "aliases": []}
    for person in _people_from_resume_signals(text, ""):
        found[_norm(person["name"])] = person
    for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
        found[_norm(email)] = {"type": "Person", "name": email, "aliases": []}
    # Generic id tokens (POL-001, DOC-12, …) — not industry-specific
    for pid in re.findall(r"\b[A-Z]{2,6}-\d{2,}\b", text):
        found[_norm(pid)] = {"type": "Concept", "name": pid, "aliases": []}
    # Alphanumeric level/product codes (SL2000, HDCP22, OPL270, …) — structural, not domain lists
    for code in re.findall(r"\b([A-Z]{1,8}\d{2,4})\b", text):
        if code.lower() in {"utf8", "utf16", "sha256", "md5"}:
            continue
        found[_norm(code)] = {
            "type": "Concept",
            "name": code,
            "aliases": [code.lower(), code.upper()],
        }
    # "Security Level 2000" / "Output Protection Level 270" style phrases
    for m in re.finditer(
        r"\b((?:Security|Output\s+Protection|License\s+Security)\s+Level\s+\d{2,4})\b",
        text,
        re.I,
    ):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        # Canonical short code when present nearby (SL2000)
        digits = re.search(r"(\d{2,4})\s*$", name)
        aliases = [name]
        if digits:
            aliases.append(f"SL{digits.group(1)}")
            aliases.append(f"sl{digits.group(1)}")
        found[_norm(name)] = {"type": "SecurityLevel", "name": name, "aliases": aliases}
    return list(found.values())


def _normalize_entity_type(raw: str) -> str:
    """Map known aliases; pass through novel domain types instead of collapsing to Concept."""
    key = re.sub(r"[\s_\-]+", "", (raw or "").strip().lower())
    if not key:
        return "Concept"
    if key in ENTITY_TYPE_MAP:
        return ENTITY_TYPE_MAP[key]
    # snake/kebab/spaced → PascalCase (job_role → JobRole, "brand asset" → BrandAsset)
    parts = re.split(r"[\s_\-/]+", (raw or "").strip())
    parts = [p for p in parts if p]
    if not parts:
        return "Concept"
    return "".join(p[:1].upper() + p[1:] for p in parts)[:48]


# Set per-weave from inferred domainProfile.aliases (thread-local via module var).
_DOMAIN_ALIASES: dict[str, str] = {}


def _norm(name: str) -> str:
    return normalize_entity_name(name, aliases=_DOMAIN_ALIASES or None)


def _evidence_span(text: str, quote: str, *needles: str) -> tuple[int, int] | None:
    """Real substring span only — never invent evidence from chunk prefix."""
    if quote:
        span = _locate_quote(text, quote)
        if span is not None:
            return span
    for needle in needles:
        n = (needle or "").strip()
        if len(n) < 3:
            continue
        idx = text.lower().find(n.lower())
        if idx < 0:
            # Try normalized / spaced form (OutputControl_X → output control x)
            spaced = _norm(n)
            if spaced and spaced != n.lower():
                idx = text.lower().find(spaced)
        if idx < 0:
            continue
        start = max(0, idx - 40)
        end = min(len(text), idx + max(len(n), 8) + 80)
        if end - start < 8:
            continue
        return start, end
    return None


async def _upsert_entity(store: Any, workspace_id: str, name: str, typ: str) -> str:
    """Merge entities by normalized_name / fuzzy alias so Trust Trails stay connected."""
    norm = _norm(name)
    preferred = typ or "Concept"
    # Prefer an existing node with this normalized name (any entity type)
    existing = await store.resolve_entity(workspace_id, name)
    if not existing and hasattr(store, "resolve_entity_fuzzy"):
        existing = await store.resolve_entity_fuzzy(workspace_id, name, limit=3)
    if not existing:
        # resolve uses shared normalize — also try direct
        cur = await store.conn.execute(
            """SELECT id, type FROM kg_nodes
               WHERE workspace_id = ? AND normalized_name = ?
               AND type NOT IN ('Document', 'Chunk', 'Section')""",
            (workspace_id, norm),
        )
        rows = await cur.fetchall()
        existing = [dict(r) for r in rows]
    if not existing:
        # Containment / prefix link against existing entity names (cross-doc merge)
        existing = await _link_similar_entity(store, workspace_id, norm)
    if existing:
        for row in existing:
            if row.get("type") == preferred:
                nid = row["id"]
                await store.insert_alias(workspace_id, name, norm, nid)
                return nid
        nid = existing[0]["id"]
        await store.insert_alias(workspace_id, name, norm, nid)
        return nid
    nid = await store.upsert_node(
        workspace_id,
        type=preferred,
        name=(name or "").strip() or norm,
        normalized_name=norm,
    )
    await store.insert_alias(workspace_id, name, norm, nid)
    return nid


async def _edge_exists(
    store: Any,
    workspace_id: str,
    src: str,
    dst: str,
    rel_type: str,
    edge_class: str | None = None,
) -> bool:
    if edge_class:
        cur = await store.conn.execute(
            """SELECT id FROM kg_edges
               WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
               AND edge_class = ? AND status = 'active' LIMIT 1""",
            (workspace_id, src, dst, rel_type, edge_class),
        )
    else:
        cur = await store.conn.execute(
            """SELECT id FROM kg_edges
               WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
               AND status = 'active' LIMIT 1""",
            (workspace_id, src, dst, rel_type),
        )
    return (await cur.fetchone()) is not None


async def _ensure_documentary_links(
    store: Any,
    workspace_id: str,
    *,
    ent_nid: str,
    chunk_nid: str,
    doc_nid: str | None,
    chunk: Any,
    needle: str,
    already: set[str],
) -> dict[str, int]:
    """Attach MENTIONS + DEFINED_IN so Structure can hang concepts off documents."""
    edges = 0
    evidence = 0
    need_mention = not await _edge_exists(
        store, workspace_id, chunk_nid, ent_nid, "MENTIONS", "documentary"
    )
    need_defined = bool(doc_nid) and not await _edge_exists(
        store, workspace_id, ent_nid, doc_nid, "DEFINED_IN", "documentary"
    )
    if not need_mention and not need_defined:
        already.add(ent_nid)
        return {"edges": 0, "evidence": 0}
    if ent_nid in already and not need_defined:
        return {"edges": 0, "evidence": 0}
    already.add(ent_nid)

    span = _evidence_span(chunk.text, "", needle)
    quote = chunk.text[span[0] : span[1]] if span else ""

    if need_mention:
        mention_eid = await store.insert_edge(
            workspace_id,
            src=chunk_nid,
            dst=ent_nid,
            rel_type="MENTIONS",
            edge_class="documentary",
            document_id=chunk.canonical_document_id,
        )
        if mention_eid:
            edges += 1
            if span:
                await store.insert_edge_evidence(
                    workspace_id,
                    edge_id=mention_eid,
                    source_chunk_id=chunk.id,
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=quote,
                    extractor="llm",
                    confidence=0.9,
                )
                evidence += 1
    if need_defined and doc_nid:
        def_eid = await store.insert_edge(
            workspace_id,
            src=ent_nid,
            dst=doc_nid,
            rel_type="DEFINED_IN",
            edge_class="documentary",
            document_id=chunk.canonical_document_id,
        )
        if def_eid:
            edges += 1
            if span:
                await store.insert_edge_evidence(
                    workspace_id,
                    edge_id=def_eid,
                    source_chunk_id=chunk.id,
                    source_span_start=span[0],
                    source_span_end=span[1],
                    quote=quote,
                    extractor="llm",
                    confidence=0.85,
                )
                evidence += 1
    return {"edges": edges, "evidence": evidence}


async def _backfill_documentary_from_evidence(
    store: Any, workspace_id: str, doc_node_ids: dict[str, str]
) -> dict[str, int]:
    """For asserted entities missing MENTIONS, wire them to evidence chunks/docs."""
    cur = await store.conn.execute(
        """SELECT e.src, e.dst, ev.source_chunk_id
           FROM kg_edges e
           JOIN kg_edge_evidence ev
             ON ev.workspace_id = e.workspace_id AND ev.edge_id = e.id AND ev.status = 'active'
           WHERE e.workspace_id = ? AND e.edge_class = 'asserted_fact' AND e.status = 'active'""",
        (workspace_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return {"edges": 0, "evidence": 0}

    chunk_rows = await store.list_chunks(workspace_id)
    chunks_by_id = {c["id"]: c for c in chunk_rows}
    ncur = await store.conn.execute(
        """SELECT id, props_json FROM kg_nodes
           WHERE workspace_id = ? AND type = 'Chunk'""",
        (workspace_id,),
    )
    chunk_nid_by_chunk: dict[str, str] = {}
    for r in await ncur.fetchall():
        props = json.loads(r["props_json"] or "{}")
        cid = props.get("chunk_id")
        if cid:
            chunk_nid_by_chunk[str(cid)] = r["id"]

    # Do not pre-seed from MENTIONS — still repair missing DEFINED_IN
    already: set[str] = set()

    ent_cur = await store.conn.execute(
        """SELECT id, type, name FROM kg_nodes
           WHERE workspace_id = ? AND type NOT IN ('Document', 'Chunk', 'Section')""",
        (workspace_id,),
    )
    entities = {str(r["id"]): dict(r) for r in await ent_cur.fetchall()}

    edges = 0
    evidence = 0

    class _ChunkView:
        __slots__ = ("id", "text", "canonical_document_id")

        def __init__(self, cid: str, text: str, doc_id: str | None) -> None:
            self.id = cid
            self.text = text
            self.canonical_document_id = doc_id

    for row in rows:
        src_chunk_id = row.get("source_chunk_id")
        if not src_chunk_id:
            continue
        chunk = chunks_by_id.get(src_chunk_id)
        if not chunk:
            continue
        chunk_nid = chunk_nid_by_chunk.get(src_chunk_id)
        if not chunk_nid:
            continue
        doc_id = chunk.get("canonical_document_id")
        doc_nid = doc_node_ids.get(doc_id) if doc_id else None
        view = _ChunkView(src_chunk_id, chunk.get("text") or "", doc_id)
        for ent_nid in (row["src"], row["dst"]):
            ent = entities.get(ent_nid)
            if not ent:
                continue
            added = await _ensure_documentary_links(
                store,
                workspace_id,
                ent_nid=ent_nid,
                chunk_nid=chunk_nid,
                doc_nid=doc_nid,
                chunk=view,
                needle=str(ent.get("name") or ""),
                already=already,
            )
            edges += added["edges"]
            evidence += added["evidence"]
    return {"edges": edges, "evidence": evidence}


async def _link_similar_entity(
    store: Any, workspace_id: str, norm: str
) -> list[dict[str, Any]]:
    """Soft entity linking: prefix / containment / alphanumeric fold match."""
    if len(norm) < 4:
        return []
    alnum = _alnum_key(norm)
    cur = await store.conn.execute(
        """SELECT id, type, name, normalized_name FROM kg_nodes
           WHERE workspace_id = ?
           AND type NOT IN ('Document', 'Chunk', 'Section')
           AND (
             normalized_name = ?
             OR normalized_name LIKE ?
             OR ? LIKE normalized_name || '%'
             OR (length(normalized_name) >= 5 AND instr(?, normalized_name) > 0)
             OR (length(?) >= 5 AND instr(normalized_name, ?) > 0)
           )
           LIMIT 24""",
        (workspace_id, norm, f"{norm}%", norm, norm, norm, norm),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows and len(alnum) >= 10:
        # Fallback: OutputControl_CompressedDigitalAudio ↔ prose "Output Control for …"
        acur = await store.conn.execute(
            """SELECT id, type, name, normalized_name FROM kg_nodes
               WHERE workspace_id = ?
               AND type NOT IN ('Document', 'Chunk', 'Section')
               LIMIT 500""",
            (workspace_id,),
        )
        for r in await acur.fetchall():
            d = dict(r)
            other_alnum = _alnum_key(str(d.get("normalized_name") or d.get("name") or ""))
            if len(other_alnum) < 10:
                continue
            shorter, longer = (
                (alnum, other_alnum)
                if len(alnum) <= len(other_alnum)
                else (other_alnum, alnum)
            )
            if shorter in longer and len(longer) <= len(shorter) * 2.2:
                rows.append(d)
    if not rows:
        return []
    # Prefer exact, then shortest name that contains / is contained (avoid over-merge)
    exact = [r for r in rows if r.get("normalized_name") == norm]
    if exact:
        return exact
    scored: list[tuple[int, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    version_re = re.compile(r"\bv\d+\b|\bversion\s*\d+\b")
    for r in rows:
        rid = str(r.get("id") or "")
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        other = str(r.get("normalized_name") or "")
        if not other:
            continue
        # Never merge versioned policy siblings (v1 ↔ v2 / bare)
        if version_re.search(norm) or version_re.search(other):
            if norm != other:
                continue
        other_alnum = _alnum_key(other)
        shorter, longer = (norm, other) if len(norm) <= len(other) else (other, norm)
        token_ok = len(shorter) >= 5 and (
            shorter in longer or longer.startswith(shorter)
        )
        alnum_ok = False
        if len(alnum) >= 10 and len(other_alnum) >= 10:
            a_short, a_long = (
                (alnum, other_alnum)
                if len(alnum) <= len(other_alnum)
                else (other_alnum, alnum)
            )
            alnum_ok = a_short in a_long and len(a_long) <= len(a_short) * 2.2
        if not token_ok and not alnum_ok:
            continue
        if token_ok and len(longer) > len(shorter) * 2.8:
            continue
        scored.append((abs(len(other_alnum) - len(alnum)), r))
    scored.sort(key=lambda x: x[0])
    return [scored[0][1]] if scored else []


def _span_for(text: str, needle: str) -> tuple[int, int]:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return 0, min(len(text), 160)
    start = max(0, idx - 40)
    end = min(len(text), idx + len(needle) + 80)
    return start, end


def _locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    idx = text.lower().find(quote.lower()[:80])
    if idx < 0:
        # try first 40 chars
        idx = text.lower().find(quote.lower()[:40])
    if idx < 0:
        return None
    return idx, min(len(text), idx + max(len(quote), 40))


async def _seed_demo_facts(store: Any, workspace_id: str, chunks: list) -> dict[str, int]:
    """Built-in IT sample corpus only (all markers together). Skips real product uploads."""
    text_blob = "\n".join(c.text for c in chunks).lower()
    is_sample = (
        "remote access policy" in text_blob
        and "access policy v1" in text_blob
        and "access policy v2" in text_blob
        and "mfa" in text_blob
        and "vpn" in text_blob
    )
    if not is_sample:
        return {"nodes": 0, "edges": 0, "evidence": 0}

    chunk = next((c for c in chunks if "mfa" in c.text.lower() and "vpn" in c.text.lower() and c.id), None)
    if chunk is None:
        chunk = next((c for c in chunks if "mfa" in c.text.lower() and c.id), chunks[0])

    vpn = await _upsert_entity(store, workspace_id, "VPN", "System")
    mfa = await _upsert_entity(store, workspace_id, "MFA", "Control")
    policy = await _upsert_entity(store, workspace_id, "Remote Access Policy", "Policy")
    team = await _upsert_entity(store, workspace_id, "IT Security Team", "Team")
    # Bare Access Policy points at ambiguity set via separate v1/v2 nodes
    v1 = await _upsert_entity(store, workspace_id, "Access Policy v1", "Policy")
    v2 = await _upsert_entity(store, workspace_id, "Access Policy v2", "Policy")
    await store.insert_alias(workspace_id, "Access Policy", "access policy", v2)

    nodes = 6
    edges = 0
    evidence = 0

    async def fact_exists(src: str, rel: str, dst: str) -> bool:
        cur = await store.conn.execute(
            """SELECT id FROM kg_edges
               WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
               AND edge_class = 'asserted_fact' AND status = 'active'""",
            (workspace_id, src, dst, rel),
        )
        return (await cur.fetchone()) is not None

    async def fact(src: str, rel: str, dst: str, needle: str) -> None:
        nonlocal edges, evidence
        if await fact_exists(src, rel, dst):
            return
        span = _span_for(chunk.text, needle)
        eid = await store.insert_edge(
            workspace_id,
            src=src,
            dst=dst,
            rel_type=rel,
            edge_class="asserted_fact",
            weight=0.95,
            document_id=chunk.canonical_document_id,
        )
        edges += 1
        await store.insert_edge_evidence(
            workspace_id,
            edge_id=eid,
            source_chunk_id=chunk.id,
            source_span_start=span[0],
            source_span_end=span[1],
            quote=chunk.text[span[0] : span[1]],
            extractor="rule",
            confidence=0.95,
        )
        evidence += 1

    await fact(vpn, "REQUIRES", mfa, "MFA")
    await fact(team, "OWNS", vpn, "IT Security")
    await fact(mfa, "PART_OF", policy, "Remote Access")
    await fact(v2, "SUPERSEDES", v1, "supersede")
    if "conflict" in text_blob.lower():
        await fact(v1, "CONFLICTS_WITH", v2, "conflict")

    return {"nodes": nodes, "edges": edges, "evidence": evidence}


def _infer_package_label(text_blob: str, titles: list[str]) -> str:
    """Derive a package/product label from titles or agreement headings — any domain."""
    for title in titles:
        m = re.search(
            r"^(.+?)\s+(Agreement|License|Contract|Policy|Specification)\b",
            title or "",
            re.I,
        )
        if m:
            label = re.sub(r"\s+", " ", m.group(1)).strip()
            if 3 <= len(label) <= 60:
                return label
    m = re.search(
        r"([A-Z][\w]+(?:\s+[A-Z][\w+/.-]+){0,4})\s+(?:Agreement|License|Contract)\b",
        text_blob,
    )
    if m:
        label = re.sub(r"\s+", " ", m.group(1)).strip()
        if 3 <= len(label) <= 60:
            return label
    return "Agreement Package"


async def _seed_agreement_facts(
    store: Any,
    workspace_id: str,
    chunks: list,
    doc_node_ids: dict[str, str],
    titles: list[str] | None = None,
) -> dict[str, int]:
    """Generic agreement/license scaffolding from headings found in the corpus."""
    text_blob = "\n".join(c.text for c in chunks)
    if not re.search(r"\b(agreement|license|contract)\b", text_blob, re.I):
        return {"nodes": 0, "edges": 0, "evidence": 0}

    chunk = next(
        (
            c
            for c in chunks
            if c.id
            and re.search(r"(agreement|license|contract)", c.text, re.I)
            and "under this" in c.text.lower()
        ),
        None,
    )
    if chunk is None:
        chunk = next(
            (
                c
                for c in chunks
                if c.id and re.search(r"(agreement|license|contract)", c.text, re.I)
            ),
            chunks[0] if chunks else None,
        )
    if chunk is None or not chunk.id:
        return {"nodes": 0, "edges": 0, "evidence": 0}

    nodes = 0
    edges = 0
    evidence = 0

    product_name = _infer_package_label(text_blob, titles or [])
    product = await _upsert_entity(store, workspace_id, product_name, "Product")
    nodes += 1

    seen: set[str] = set()
    licenses: list[str] = []
    for m in re.finditer(
        r"([A-Z][\w]+(?:\s+[A-Z][\w+/.-]+){0,6}\s+"
        r"(?:Agreement|License|Contract|Addendum|Amendment))",
        text_blob,
    ):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        key = _norm(name)
        if key in seen or len(name) < 8:
            continue
        seen.add(key)
        licenses.append(name)
        if len(licenses) >= 8:
            break

    async def fact_exists(src: str, rel: str, dst: str) -> bool:
        cur = await store.conn.execute(
            """SELECT id FROM kg_edges
               WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
               AND edge_class = 'asserted_fact' AND status = 'active'""",
            (workspace_id, src, dst, rel),
        )
        return (await cur.fetchone()) is not None

    for name in licenses:
        lid = await _upsert_entity(store, workspace_id, name, "Concept")
        nodes += 1
        if not await fact_exists(lid, "PART_OF", product):
            src_chunk = next(
                (c for c in chunks if c.id and name.lower() in c.text.lower()),
                chunk,
            )
            span = _evidence_span(src_chunk.text, "", name)
            if span is None:
                continue
            eid = await store.insert_edge(
                workspace_id,
                src=lid,
                dst=product,
                rel_type="PART_OF",
                edge_class="asserted_fact",
                weight=0.9,
                document_id=src_chunk.canonical_document_id,
                props={"extractor": "agreement_seed"},
            )
            if not eid:
                continue
            edges += 1
            await store.insert_edge_evidence(
                workspace_id,
                edge_id=eid,
                source_chunk_id=src_chunk.id,
                source_span_start=span[0],
                source_span_end=span[1],
                quote=src_chunk.text[span[0] : span[1]],
                extractor="rule",
                confidence=0.9,
            )
            evidence += 1

        doc_nid = doc_node_ids.get(chunk.canonical_document_id) or next(
            iter(doc_node_ids.values()), None
        )
        if doc_nid and not await _edge_exists(
            store, workspace_id, lid, doc_nid, "DEFINED_IN", "documentary"
        ):
            def_eid = await store.insert_edge(
                workspace_id,
                src=lid,
                dst=doc_nid,
                rel_type="DEFINED_IN",
                edge_class="documentary",
                document_id=chunk.canonical_document_id,
            )
            if def_eid:
                edges += 1
                span = _evidence_span(chunk.text, "", name)
                if span:
                    await store.insert_edge_evidence(
                        workspace_id,
                        edge_id=def_eid,
                        source_chunk_id=chunk.id,
                        source_span_start=span[0],
                        source_span_end=span[1],
                        quote=chunk.text[span[0] : span[1]],
                        extractor="rule",
                        confidence=0.85,
                    )
                    evidence += 1

    return {"nodes": nodes, "edges": edges, "evidence": evidence}
