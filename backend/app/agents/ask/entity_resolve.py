from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.ask.contracts import (
    EntityResolveInput,
    EntityResolveOutput,
    ResolvedEntity,
)
from app.agents.ask.comparison import extract_compare_sides, is_comparison_question
from app.agents.ask.overview import is_document_overview, mentions_document
from app.agents.base import AgentContext, AgentResult
from app.identity import normalize_entity_name
from app.schemas import ClarifyOption

logger = logging.getLogger(__name__)

# Structural term harvest only — no product vocabulary.
# Acronym patterns stay CASE-SENSITIVE so English words like "and"/"for" are not harvested.
TERM_PATTERNS = [
    (r"\b[A-Z]{2,6}\b", 0),  # flags=0 → require real capitals (MFA, VPN, SL)
    (r"\b[A-Z]{2,6}-\d{2,}\b", 0),
    (r"(?:Agreement|License|Policy|Contract)\s*(?:Number|#|No\.?)", re.I),
    (r"\b[\w][\w\s/-]{2,40}\s+v\d+\b", re.I),
]

_STOP_TERMS = {
    "what",
    "how",
    "who",
    "the",
    "this",
    "that",
    "does",
    "can",
    "and",
    "or",
    "for",
    "with",
    "from",
    "into",
    "vs",
    "versus",
    "between",
    "compare",
    "difference",
    "about",
    "which",
    "when",
    "where",
    "your",
    "our",
    "any",
    "all",
}


class EntityResolveAgent:
    id = "entity_resolve"
    display_name = "Entity Resolve Agent"
    input_model = EntityResolveInput
    output_model = EntityResolveOutput

    async def run(
        self, ctx: AgentContext, payload: EntityResolveInput
    ) -> AgentResult[EntityResolveOutput]:
        store = ctx.stores
        comparison = is_comparison_question(payload.question)
        compare_sides = extract_compare_sides(payload.question)

        terms: list[str] = []
        # Comparison sides first — these are the answer subjects
        terms.extend(compare_sides)
        for pat, flags in TERM_PATTERNS:
            for m in re.finditer(pat, payload.question, flags):
                terms.append(m.group(0))
        # Token codes like SL3000 / PlayReady (capitalized runs) — not lowercase glue words
        terms.extend(
            re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*\b", payload.question)
        )
        terms.extend(re.findall(r"[\"“]([^\"”]{2,60})[\"”]", payload.question))
        # Alphanumeric product codes that mixed patterns may miss (e.g. SL3000)
        terms.extend(re.findall(r"\b[A-Za-z]{1,8}\d{2,}\b", payload.question))
        if len(terms) < 2 and ctx.llm is not None:
            terms.extend(await _llm_terms(ctx, payload.question))

        # Prefer longer/specific terms; drop bare stem if versioned siblings appear in question
        versioned_in_q = {
            normalize_entity_name(t)
            for t in terms
            if re.search(r"\bv\d+\b", t, re.I)
        }
        seen: set[str] = set()
        uniq_terms = []
        # Keep compare-side order first, then other terms by length
        ordered = list(compare_sides) + sorted(
            [t for t in terms if t not in compare_sides], key=len, reverse=True
        )
        for t in ordered:
            key = t.lower().strip()
            if not key or key in seen or key in _STOP_TERMS:
                continue
            # Drop "Compare SL3000"-style harvests that start with framing words
            lead = key.split()[0] if key.split() else key
            if lead in _STOP_TERMS and len(key.split()) > 1:
                rest = " ".join(t.split()[1:]).strip()
                if rest and rest.lower() not in seen:
                    t = rest
                    key = rest.lower()
                else:
                    continue
            stem = normalize_entity_name(re.sub(r"\s+v\d+\b", "", t, flags=re.I))
            if (
                stem
                and normalize_entity_name(t) == stem
                and any(v.startswith(stem + " v") for v in versioned_in_q)
            ):
                continue
            seen.add(key)
            uniq_terms.append(t.strip())

        entities: list[ResolvedEntity] = []
        clarify_options: list[ClarifyOption] = []
        ambiguous = False
        compare_side_keys = {s.lower() for s in compare_sides}

        for term in uniq_terms[:12]:
            matches = []
            if store:
                matches = await store.resolve_entity(ctx.workspace_id, term)
                if not matches and hasattr(store, "resolve_entity_fuzzy"):
                    matches = await store.resolve_entity_fuzzy(
                        ctx.workspace_id, term, limit=4
                    )
                # Bare "X" when graph has "X v1" / "X v2" → clarify (any domain)
                # Skip for explicit comparison sides / product codes — keep moving to hybrid
                if (
                    store
                    and not comparison
                    and not re.search(r"\b[A-Za-z]{1,8}\d{2,}\b", term)
                    and not re.search(r"\bv\d+\b", term, re.I)
                ):
                    siblings = await _version_siblings(store, ctx.workspace_id, term)
                    if len(siblings) > 1:
                        matches = siblings

            # For comparisons: only clarify when a *side* itself is multi-match ambiguous
            allow_clarify = (not comparison) or (term.lower() in compare_side_keys)

            if len(matches) > 1 and _looks_ambiguous(matches, term) and allow_clarify:
                # Codes like SL3000 must not clarify against unrelated nodes (PlayReady, …)
                if _is_product_code(term) and not _matches_relate_to_term(matches, term):
                    matches = _prefer_related(matches, term)[:1] or matches[:1]
                else:
                    ambiguous = True
                    for n in matches[:4]:
                        clarify_options.append(
                            ClarifyOption(
                                id=n["id"],
                                label=n["name"],
                                description=f"{n.get('type', 'Entity')} in knowledge graph",
                            )
                        )
                    entities.append(
                        ResolvedEntity(
                            query_term=term,
                            node_ids=[n["id"] for n in matches[:4]],
                            names=[n["name"] for n in matches[:4]],
                            ambiguous=True,
                        )
                    )
                    continue

            if matches:
                # Prefer a match that actually looks like the term for codes
                related = _prefer_related(matches, term)
                if _is_product_code(term) and not related:
                    # e.g. SL3000 must not bind to over-aliased PlayReady
                    entities.append(
                        ResolvedEntity(
                            query_term=term, node_ids=[], names=[], ambiguous=False
                        )
                    )
                else:
                    pick = related[0] if related else matches[0]
                    entities.append(
                        ResolvedEntity(
                            query_term=term,
                            node_ids=[pick["id"]],
                            names=[pick["name"]],
                            ambiguous=False,
                        )
                    )
            else:
                entities.append(
                    ResolvedEntity(query_term=term, node_ids=[], names=[], ambiguous=False)
                )

        overview = is_document_overview(payload.question) or (
            payload.intent == "fuzzy" and mentions_document(payload.question)
        )
        if store and overview:
            graph = await store.get_graph(ctx.workspace_id)
            doc_nodes = [n for n in graph["nodes"] if n.get("type") == "Document"]
            q_l = payload.question.lower()
            tokens = [
                w
                for w in re.findall(r"[a-z0-9]{4,}", q_l)
                if w
                not in {
                    "what",
                    "whats",
                    "there",
                    "this",
                    "that",
                    "agreement",
                    "document",
                    "about",
                    "tell",
                }
            ]
            prefer = [
                n
                for n in doc_nodes
                if any(k in (n.get("name") or "").lower() for k in tokens)
                or any(
                    k in (n.get("name") or "").lower()
                    for k in ("agreement", "contract", "license", "policy")
                )
            ]
            chosen = prefer or doc_nodes
            if chosen:
                entities.append(
                    ResolvedEntity(
                        query_term="document",
                        node_ids=[n["id"] for n in chosen[:4]],
                        names=[n["name"] for n in chosen[:4]],
                        ambiguous=False,
                    )
                )

        if clarify_options:
            uniq_opts: list[ClarifyOption] = []
            seen_opt: set[str] = set()
            for opt in clarify_options:
                key = opt.label.lower()
                if key in seen_opt:
                    continue
                seen_opt.add(key)
                uniq_opts.append(opt)
            clarify_options = uniq_opts

        # Comparisons with two clear sides proceed even without graph node hits —
        # quote_fill / hybrid KB covers document evidence for SL2000 vs SL3000 etc.
        if comparison and len(compare_sides) >= 2 and not ambiguous:
            resolved_clearly = True
        else:
            resolved_clearly = not ambiguous and any(e.node_ids for e in entities)
        reason_codes: list[str] = []
        prompt = None
        if ambiguous and not (comparison and len(compare_sides) >= 2):
            reason_codes.append("ENTITY_AMBIGUOUS")
            labels = ", ".join(o.label for o in clarify_options[:4]) or "those options"
            prompt = f"I found multiple matching entities ({labels}). Which one do you mean?"
            resolved_clearly = False
        elif ambiguous and comparison and len(compare_sides) >= 2:
            # Do not block comparisons on tangential ambiguity
            ambiguous = False
            clarify_options = []
            reason_codes = []
            prompt = None
            resolved_clearly = True
        elif not any(e.node_ids for e in entities):
            if not overview and not comparison:
                reason_codes.append("ENTITY_NOT_RESOLVED")
            if payload.intent == "structural" and not comparison:
                resolved_clearly = False
                prompt = (
                    "I couldn't clearly resolve the entities in your question "
                    "against the connected knowledge graph. Can you name the concept "
                    "or document more specifically?"
                )
        ctx.emit(
            self.id,
            "resolve.done",
            f"Resolved {sum(1 for e in entities if e.node_ids)} entities",
            progress=1.0,
        )
        return AgentResult(
            ok=True,
            data=EntityResolveOutput(
                question=payload.question,
                intent=payload.intent,
                entities=entities,
                resolved_clearly=resolved_clearly,
                reason_codes=reason_codes,
                clarify_options=clarify_options,
                clarification_prompt=prompt,
                comparison=comparison,
                compare_sides=compare_sides,
            ),
            metrics={
                "entities": len(entities),
                "ambiguous": int(ambiguous),
                "comparison": int(comparison),
                "compare_sides": len(compare_sides),
            },
        )


def _is_product_code(term: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{1,8}\d{2,}", (term or "").strip()))


def _matches_relate_to_term(matches: list[dict], term: str) -> bool:
    return bool(_prefer_related(matches, term))


def _prefer_related(matches: list[dict], term: str) -> list[dict]:
    """Keep nodes whose name/normalized form shares the term (esp. codes)."""
    t = (term or "").strip().lower()
    t_alnum = re.sub(r"[^a-z0-9]", "", t)
    if not t_alnum:
        return []
    related: list[dict] = []
    for m in matches:
        blob = f"{m.get('name') or ''} {m.get('normalized_name') or ''}".lower()
        blob_alnum = re.sub(r"[^a-z0-9]", "", blob)
        if t in blob or (len(t_alnum) >= 4 and t_alnum in blob_alnum):
            related.append(m)
    return related


async def _version_siblings(store: Any, workspace_id: str, term: str) -> list[dict]:
    """If bare term has versioned siblings in the graph, return them for clarify."""
    stem = normalize_entity_name(term)
    if len(stem) < 4:
        return []
    cur = await store.conn.execute(
        """SELECT id, name, type, normalized_name FROM kg_nodes
           WHERE workspace_id = ?
           AND type NOT IN ('Document', 'Chunk', 'Section')
           AND (
             normalized_name = ?
             OR normalized_name LIKE ?
           )
           LIMIT 12""",
        (workspace_id, stem, f"{stem} v%"),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    versioned = [r for r in rows if re.search(r"\bv\d+\b", r.get("normalized_name") or "")]
    if len(versioned) >= 2:
        return versioned
    return []


def _looks_ambiguous(matches: list[dict], term: str) -> bool:
    """True when several distinct entities match a short query term equally well."""
    if len(matches) < 2:
        return False
    names = {str(m.get("normalized_name") or m.get("name") or "").lower() for m in matches}
    if len(names) < 2:
        return False
    t = term.lower().strip()
    if any(n == t for n in names) and sum(1 for n in names if n == t) == 1:
        return False
    lengths = sorted(len(n) for n in names if n)
    if not lengths:
        return False
    return lengths[-1] - lengths[0] <= 8


async def _llm_terms(ctx: AgentContext, question: str) -> list[str]:
    try:
        raw = await ctx.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract 2-6 key entity phrases from the user question for "
                        "knowledge-graph lookup. Return JSON {\"terms\": string[]}. "
                        "Use noun phrases only; no filler words."
                    ),
                },
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        terms = data.get("terms") if isinstance(data, dict) else []
        out: list[str] = []
        for t in terms or []:
            if isinstance(t, str) and 2 <= len(t.strip()) <= 80:
                out.append(t.strip())
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM term extract skipped: %s", exc)
        return []
