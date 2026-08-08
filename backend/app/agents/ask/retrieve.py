"""
Unified KB retrieval for Ask.

Always merges: lexical · GPT terms · embeddings · optional graph evidence · names.
Re-ranks by multi-term coverage and gap-fills missing required terms so comparison /
how-to questions get a complete evidence pack before GPT answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import json
import logging

from app.agents.ask.contracts import QuoteHit
from app.agents.ask.lexical import distinctive_terms
from app.agents.ask.people import extract_query_names
from app.agents.base import AgentContext
from app.stores.vector import VectorStore

logger = logging.getLogger(__name__)


async def gpt_search_terms(ctx: AgentContext, question: str) -> list[str]:
    """Ask GPT for literal search phrases that should appear in source docs."""
    if ctx.llm is None:
        return []
    try:
        raw = await ctx.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract 3-8 literal search terms/phrases useful for finding "
                        "answers in a document corpus. Prefer distinctive codes, "
                        "feature names, verbs from the question, and multi-word phrases. "
                        "Include BOTH sides of a comparison when present. "
                        "Return JSON {terms: string[]}."
                    ),
                },
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        parsed = json.loads(raw)
        terms = parsed.get("terms") or []
        out: list[str] = []
        for t in terms:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if len(t) < 2 or len(t) > 80:
                continue
            out.append(t)
        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"
        return out[:8]
    except Exception as exc:  # noqa: BLE001
        logger.warning("gpt_search_terms failed: %s", exc)
        return []

_STOP_SOFT = {
    "document",
    "documents",
    "file",
    "files",
    "pdf",
    "please",
    "tell",
    "know",
    "give",
    "show",
    "explain",
    "describe",
    "define",
    "difference",
    "differences",
    "compare",
    "comparison",
    "versus",
    "between",
}


@dataclass
class RetrievalPack:
    quotes: list[QuoteHit]
    mode: str
    coverage: float  # 0..1 fraction of required terms covered
    required_terms: list[str]


def required_terms(question: str, extra: list[str] | None = None) -> list[str]:
    """Terms the evidence pack should try to cover."""
    terms = distinctive_terms(question)
    for t in extra or []:
        if t and t.lower() not in {x.lower() for x in terms}:
            terms.append(t.strip())
    # Keep strong + actionable content words
    out: list[str] = []
    for t in terms:
        tl = t.lower()
        if tl in _STOP_SOFT and len(terms) > 2:
            continue
        out.append(t)
    # Comparison codes always required
    for m in re.finditer(r"\b([A-Z]{2,}\d{2,})\b", question or ""):
        if m.group(1) not in out:
            out.insert(0, m.group(1))
    # How-to verbs that matter in corpus
    q = (question or "").lower()
    for verb in ("renew", "renewal", "install", "configure", "enable", "disable"):
        if verb in q and verb not in {x.lower() for x in out}:
            out.append(verb)
    return out[:14]


def _is_strong(term: str) -> bool:
    return bool(re.search(r"\d", term) or " " in term)


def _window(text: str, terms: list[str], *, radius: int = 220) -> str:
    """Excerpt spanning as many matched terms as possible."""
    if not text:
        return ""
    low = text.lower()
    positions: list[int] = []
    for t in terms:
        pos = low.find(t.lower())
        if pos >= 0:
            positions.append(pos)
    if not positions:
        snippet = re.sub(r"\s+", " ", text[:480]).strip()
        return snippet
    start = max(0, min(positions) - 100)
    end = min(len(text), max(positions) + radius)
    # Expand a bit if multiple terms far apart
    if max(positions) - min(positions) > 500:
        end = min(len(text), min(positions) + 700)
    return re.sub(r"\s+", " ", text[start:end].strip())


def _term_hits(text: str, title: str, terms: list[str]) -> list[str]:
    blob = f"{title}\n{text}".lower()
    return [t for t in terms if t.lower() in blob]


def _score_chunk(text: str, title: str, terms: list[str], *, base: float = 0.0) -> float:
    hits = _term_hits(text, title, terms)
    if not hits:
        return base * 0.2
    score = base
    strong = [t for t in terms if _is_strong(t)]
    soft = [t for t in terms if not _is_strong(t)]
    for t in hits:
        score += 3.5 if _is_strong(t) else 1.0
    # Big boost when ALL strong terms co-occur (comparison questions)
    if strong and all(t.lower() in f"{title}\n{text}".lower() for t in strong):
        score += 8.0
    # Co-occurrence of 2+ soft content terms (renew + license)
    soft_hits = [t for t in soft if t.lower() in f"{title}\n{text}".lower()]
    if len(soft_hits) >= 2:
        score += 3.0
    # Coverage ratio
    score += 2.0 * (len(hits) / max(len(terms), 1))
    return score


def coverage_ratio(quotes: list[QuoteHit], terms: list[str]) -> float:
    if not terms:
        return 1.0 if quotes else 0.0
    blob = " ".join(f"{q.document_title} {q.quote}" for q in quotes).lower()
    hit = sum(1 for t in terms if t.lower() in blob)
    return hit / len(terms)


async def retrieve_evidence_pack(
    ctx: AgentContext,
    store,
    vector: VectorStore,
    question: str,
    *,
    top_k: int = 8,
    graph_quotes: list[QuoteHit] | None = None,
    prefer_overview: bool = False,
    overview_quotes: list[QuoteHit] | None = None,
    name_only: bool = False,
) -> RetrievalPack:
    """Build a coverage-complete quote pack from the whole knowledge base."""
    if store is None:
        return RetrievalPack(quotes=[], mode="empty", coverage=0.0, required_terms=[])

    # --- special fast paths ---
    if name_only:
        names = await _name_quotes(store, ctx.workspace_id, question)
        return RetrievalPack(
            quotes=names,
            mode="name_lookup",
            coverage=1.0 if names else 0.0,
            required_terms=extract_query_names(question),
        )

    extra = await gpt_search_terms(ctx, question) if ctx.llm is not None else []
    terms = required_terms(question, extra)
    chunks = await store.list_chunks(ctx.workspace_id)
    docs = {d["id"]: d["title"] for d in await store.list_canonical_documents(ctx.workspace_id)}

    # Candidate map: chunk_id -> (score, chunk, text, title, edge_id?)
    cand: dict[str, tuple[float, dict, str, str, str | None]] = {}

    def add_chunk(ch: dict, text: str, title: str, base: float, edge_id: str | None = None) -> None:
        cid = ch["id"]
        sc = _score_chunk(text, title, terms, base=base)
        prev = cand.get(cid)
        if prev is None or sc > prev[0]:
            cand[cid] = (sc, ch, text, title, edge_id or (prev[4] if prev else None))

    # 1) Lexical scan of all chunks
    for ch in chunks:
        text = ch.get("text") or ""
        if len(text.strip()) < 20:
            continue
        title = docs.get(ch.get("canonical_document_id"), "") or "document"
        if not _term_hits(text, title, terms) and terms:
            continue
        add_chunk(ch, text, title, base=0.55)

    # 2) Embeddings (additive)
    if ctx.llm is not None:
        try:
            emb = (await ctx.llm.embed([question]))[0]
            hits = await vector.query(ctx.workspace_id, emb, top_k=max(top_k, 10), chunk_ids=None)
            chunk_by_id = {c["id"]: c for c in chunks}
            for h in hits:
                cid = h.get("chunk_id")
                ch = chunk_by_id.get(cid)
                if not ch:
                    continue
                title = h.get("document_title") or docs.get(ch.get("canonical_document_id"), "document")
                text = h.get("text") or ch.get("text") or ""
                add_chunk(ch, text, title, base=0.35 + float(h.get("score") or 0) * 0.4)
        except Exception:  # noqa: BLE001
            pass

    # 3) Graph evidence — boosted so evidence-bound trails lead the pack
    graph_primary = bool(graph_quotes) and any(gq.edge_id for gq in graph_quotes or [])
    for gq in graph_quotes or []:
        ch = next((c for c in chunks if c["id"] == gq.chunk_id), None)
        if not ch:
            # keep quote text even if chunk missing
            fake = {
                "id": gq.chunk_id,
                "canonical_document_id": None,
                "loc": {"locator": gq.locator},
            }
            add_chunk(fake, gq.quote, gq.document_title, base=0.85, edge_id=gq.edge_id)
            continue
        text = ch.get("text") or gq.quote
        title = docs.get(ch.get("canonical_document_id"), gq.document_title) or gq.document_title
        # Prefer shorter evidence quotes when packing the window
        prefer = gq.quote if gq.quote and len(gq.quote) >= 24 else text
        add_chunk(ch, prefer, title, base=0.9 + float(gq.score or 0) * 0.05, edge_id=gq.edge_id)

    # 4) Overview chunks (additive for deictic / summarize)
    if prefer_overview and overview_quotes:
        for oq in overview_quotes:
            ch = next((c for c in chunks if c["id"] == oq.chunk_id), None)
            if not ch:
                continue
            text = ch.get("text") or oq.quote
            title = oq.document_title
            add_chunk(ch, text, title, base=0.5)

    # Rank
    ranked = sorted(cand.values(), key=lambda x: x[0], reverse=True)

    # Gap-fill: ensure each required/strong term appears in the pack
    selected: list[tuple[float, dict, str, str, str | None]] = []
    selected_ids: set[str] = set()

    def take(row: tuple[float, dict, str, str, str | None]) -> None:
        cid = row[1]["id"]
        if cid in selected_ids:
            return
        selected_ids.add(cid)
        selected.append(row)

    for row in ranked:
        if len(selected) >= top_k:
            break
        take(row)

    must = [t for t in terms if _is_strong(t)] or terms[:3]
    pack_blob = " ".join(f"{title} {text}" for _, _, text, title, _ in selected).lower()
    for term in must:
        if term.lower() in pack_blob:
            continue
        # find best chunk for this term alone
        best = None
        best_sc = -1.0
        for row in ranked:
            sc, ch, text, title, edge = row
            if term.lower() in f"{title}\n{text}".lower():
                if sc > best_sc:
                    best = row
                    best_sc = sc
        if best:
            take(best)
            pack_blob = " ".join(
                f"{title} {text}" for _, _, text, title, _ in selected
            ).lower()

    # Prefer co-occurrence chunks at the front for comparisons
    selected.sort(
        key=lambda row: (
            len(_term_hits(row[2], row[3], must)),
            row[0],
        ),
        reverse=True,
    )

    quotes: list[QuoteHit] = []
    for sc, ch, text, title, edge_id in selected[: max(top_k, 12)]:
        # Keep graph evidence quotes intact; window hybrid chunks around terms
        if edge_id and len(text.strip()) <= 560:
            quote = text.strip()
        else:
            quote = _window(text, terms)
        if len(quote) < 24:
            continue
        quotes.append(
            QuoteHit(
                chunk_id=ch["id"],
                document_title=title or "document",
                locator=(ch.get("loc") or {}).get("locator"),
                quote=quote[:560],
                score=min(0.99, 0.55 + sc / 20.0),
                edge_id=edge_id,
            )
        )

    # Learned-ish rerank: LLM orders the candidate pack by answer utility
    quotes = await rerank_quotes(ctx, question, quotes, top_k=max(top_k, 8))

    cov = coverage_ratio(quotes, must if must else terms)
    mode = "hybrid_kb"
    if graph_primary and any(q.edge_id for q in quotes[:3]):
        mode = "graph_primary" if cov >= 0.45 else "hybrid_graph_kb"
    elif graph_quotes and any(q.edge_id for q in quotes):
        mode = "hybrid_graph_kb"
    if prefer_overview and cov < 0.35 and overview_quotes:
        # fall back to overview only if hybrid coverage is weak
        quotes = overview_quotes[:top_k]
        mode = "document_overview"
        cov = coverage_ratio(quotes, terms)

    return RetrievalPack(
        quotes=quotes[: max(top_k, 8)],
        mode=mode,
        coverage=cov,
        required_terms=terms,
    )


async def rerank_quotes(
    ctx: AgentContext,
    question: str,
    quotes: list[QuoteHit],
    *,
    top_k: int = 8,
) -> list[QuoteHit]:
    """Reorder quote candidates so the judge sees the most answer-relevant evidence first."""
    if len(quotes) <= 1:
        return quotes
    # Cheap heuristic first (always applied)
    q_l = question.lower()
    q_terms = [t for t in re.findall(r"[a-z0-9]{3,}", q_l) if t not in _STOP_SOFT]

    def _heuristic(q: QuoteHit) -> float:
        blob = f"{q.document_title} {q.quote}".lower()
        term_hit = sum(1 for t in q_terms if t in blob)
        graph_bonus = 0.35 if q.edge_id else 0.0
        length_pen = 0.05 if len(q.quote) < 40 else 0.0
        return float(q.score) + 0.08 * term_hit + graph_bonus - length_pen

    ordered = sorted(quotes, key=_heuristic, reverse=True)

    if ctx.llm is None or len(ordered) < 3:
        return ordered[:top_k]

    # LLM rerank over a shortlist (keeps latency bounded)
    shortlist = ordered[: min(12, len(ordered))]
    catalog = [
        {
            "i": i,
            "doc": q.document_title,
            "quote": q.quote[:320],
            "graph": bool(q.edge_id),
        }
        for i, q in enumerate(shortlist)
    ]
    try:
        raw = await ctx.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You rerank evidence quotes for an evidence-bound QA system. "
                        "Return JSON {order: number[]} — indices of quotes from most to least "
                        "useful for answering the question. Prefer quotes that directly support "
                        "an answer; prefer graph-backed quotes when equally relevant. "
                        "Do not invent quotes; only permute the given indices."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"question": question, "quotes": catalog}),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        data = json.loads(raw)
        order = data.get("order") if isinstance(data, dict) else None
        if not isinstance(order, list):
            return shortlist[:top_k]
        seen: set[int] = set()
        reranked: list[QuoteHit] = []
        for idx in order:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if i < 0 or i >= len(shortlist) or i in seen:
                continue
            seen.add(i)
            q = shortlist[i]
            # Nudge score to reflect new rank while preserving relative gaps
            q.score = min(0.99, 0.99 - 0.04 * len(reranked) + (0.05 if q.edge_id else 0))
            reranked.append(q)
        # Append any shortlist items the model skipped
        for i, q in enumerate(shortlist):
            if i not in seen:
                reranked.append(q)
        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"
        return reranked[:top_k]
    except Exception as exc:  # noqa: BLE001
        logger.warning("quote rerank failed: %s", exc)
        return shortlist[:top_k]


async def _name_quotes(store, workspace_id: str, question: str) -> list[QuoteHit]:
    names = extract_query_names(question)
    if not names:
        return []
    chunks = await store.list_chunks(workspace_id)
    docs = {d["id"]: d["title"] for d in await store.list_canonical_documents(workspace_id)}
    hits: list[QuoteHit] = []
    for name in names:
        pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
        for ch in chunks:
            text = ch.get("text") or ""
            title = docs.get(ch.get("canonical_document_id"), "") or ""
            m = pat.search(text)
            if not m:
                if name.lower() not in title.lower().replace("_", " ").replace("-", " "):
                    continue
                m_start = 0
            else:
                m_start = m.start()
            start = max(0, m_start - 60)
            end = min(len(text), m_start + 180) if text else 0
            quote = (text[start:end].strip() if text else "") or f"{name} appears in {title}"
            hits.append(
                QuoteHit(
                    chunk_id=ch["id"],
                    document_title=title or "document",
                    locator=(ch.get("loc") or {}).get("locator"),
                    quote=quote,
                    score=0.97,
                )
            )
            break
    return hits
