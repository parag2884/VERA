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
from app.agents.ask.evidence_contract import (
    EvidenceContract,
    contract_fit_score,
    detect_evidence_contract,
    prune_supporting_quotes,
)
from app.agents.ask.lexical import distinctive_terms
from app.agents.ask.people import extract_query_names
from app.agents.ask.page_signals import (
    has_transformation_triad,
    is_career_pathway_page,
    is_insight_chrome_page,
    is_service_page,
    offering_list_density,
    service_support_hit,
    triad_span_pos,
)
from app.knowledge.sources.web.path_policy import filename_term_bonus, path_rank_bonus
from app.agents.ask.relevance import (
    boilerplate_penalty,
    graph_quote_base,
    is_org_roster_question,
    is_officer_attribute_question,
    officer_role_evidence_bonus,
    person_title_names,
    question_term_overlap,
    recency_bonus,
    roster_evidence_bonus,
    trail_answer_relevance,
)
from app.agents.base import AgentContext
from app.services.passage_signals import signals_from_chunk
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
                        "feature names, titles, proper nouns, verbs from the question, "
                        "and multi-word phrases. "
                        "Include BOTH sides of a comparison when present. "
                        "Expand short acronyms from the question into full phrases when "
                        "obvious from the question text alone. "
                        "Do NOT include vague singleton words like about/team/page/"
                        "leadership/executive/home/menu. "
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
    "name",
    "some",
    "roughly",
    "long",
    "many",
    "much",
    "offer",
    "offers",
    "one",
    "two",
    "three",
    "four",
    "five",
    "several",
    "various",
    "main",
    "key",
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
    # Comparison codes + standards always required (ISO 27001, SL2000, …)
    for m in re.finditer(r"\b([A-Z]{2,}\d{2,})\b", question or ""):
        if m.group(1) not in out:
            out.insert(0, m.group(1))
    for m in re.finditer(r"\b([A-Z]{2,})\s*[- ]?\s*(\d{2,}(?:\.\d+)?)\b", question or ""):
        phrase = f"{m.group(1)} {m.group(2)}"
        compact = f"{m.group(1)}{m.group(2)}"
        if phrase not in out:
            out.insert(0, phrase)
        if compact not in out:
            out.insert(0, compact)
    # How-to verbs that matter in corpus
    q = (question or "").lower()
    for verb in ("renew", "renewal", "install", "configure", "enable", "disable"):
        if verb in q and verb not in {x.lower() for x in out}:
            out.append(verb)
    # Officer acronyms → full titles (org charts rarely say "CEO", they spell it out)
    _officer_expand = (
        (r"\bceo\b", ("chief executive officer", "chief executive")),
        (r"\bcfo\b", ("chief financial officer", "chief financial")),
        (r"\bcto\b", ("chief technology officer", "chief technology")),
        (r"\bcoo\b", ("chief operating officer", "chief operating")),
    )
    for pat, phrases in _officer_expand:
        if re.search(pat, q):
            for phrase in phrases:
                if phrase not in {x.lower() for x in out}:
                    out.append(phrase)
    # Keep multi-word phrases the user actually said (no invented brand lexicon)
    for phrase in (
        "transformation pathways",
        "transformation pathway",
        "ai transformation",
        "what we do",
    ):
        if phrase in q and phrase not in {x.lower() for x in out}:
            out.insert(0, phrase)
    if re.search(r"\b(capabilities|services|offerings?|solutions)\b", q) and re.search(
        r"\b(name|list|offer|what|which)\b", q
    ):
        for t in ("capabilities", "services", "offerings", "solutions"):
            if t in q and t not in {x.lower() for x in out}:
                out.append(t)
        # Drop awkward "capabilities OrgName" concatenations that never appear in prose
        out = [
            t
            for t in out
            if not re.search(r"^capabilities\s+\w+$", t, re.I)
        ]
    return out[:14]


def _is_strong(term: str) -> bool:
    return bool(re.search(r"\d", term) or " " in term)


def _window(text: str, terms: list[str], *, radius: int = 220, question: str = "") -> str:
    """Excerpt spanning as many matched terms as possible."""
    if not text:
        return ""
    # Roster questions: prefer a window around named officers, not nav chrome
    if is_org_roster_question(question):
        people = person_title_names(text)
        if people:
            pos = text.find(people[0])
            if pos >= 0:
                start = max(0, pos - 80)
                end = min(len(text), pos + 480)
                return re.sub(r"\s+", " ", text[start:end].strip())
    # Single-role who-is: center on the role binding (not a mid-list slice)
    if is_officer_attribute_question(question):
        ql_w = (question or "").lower()
        role_rx = None
        if re.search(r"\b(ceo|chief\s+executive)\b", ql_w):
            role_rx = re.compile(
                r"(serves\s+as\s+chief\s+executive|chief\s+executive\s+officer)",
                re.I,
            )
        elif re.search(r"\b(cfo|chief\s+financial)\b", ql_w):
            role_rx = re.compile(
                r"(serves\s+as\s+chief\s+financial|chief\s+financial\s+officer)",
                re.I,
            )
        elif re.search(r"\b(cto|chief\s+technology)\b", ql_w):
            role_rx = re.compile(
                r"(serves\s+as\s+chief\s+technology|chief\s+technology\s+officer)",
                re.I,
            )
        if role_rx:
            m = role_rx.search(text)
            if m:
                start = max(0, m.start() - 100)
                end = min(len(text), m.end() + 160)
                return re.sub(r"\s+", " ", text[start:end].strip())
    ql = (question or "").lower()
    # Pathway / triad pages: center on any branded Word. Word. Word. strip
    if "pathway" in ql or "transformation" in ql:
        pos = triad_span_pos(text)
        if pos >= 0:
            start = max(0, pos - 120)
            end = min(len(text), pos + 360)
            return re.sub(r"\s+", " ", text[start:end].strip())
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


def _score_chunk(
    text: str,
    title: str,
    terms: list[str],
    *,
    base: float = 0.0,
    question: str = "",
    contract: EvidenceContract | None = None,
    signals: dict | None = None,
) -> float:
    hits = _term_hits(text, title, terms)
    sig = signals or {}
    # Contract-shaped passages may enter with weak term hits (list_people officers)
    if not hits and not (
        contract
        and contract.shape == "list_people"
        and (sig.get("has_person_role") or person_title_names(f"{title}\n{text}"))
    ):
        return base * 0.2
    score = base
    strong = [t for t in terms if _is_strong(t)]
    soft = [t for t in terms if not _is_strong(t)]
    for t in hits:
        score += 3.5 if _is_strong(t) else 1.0
    blob = f"{title}\n{text}"
    blob_l = blob.lower()
    if strong and all(t.lower() in blob_l for t in strong):
        score += 8.0
    soft_hits = [t for t in soft if t.lower() in blob_l]
    if len(soft_hits) >= 2:
        score += 3.0
    if terms:
        score += 2.0 * (len(hits) / max(len(terms), 1))

    # Title match: distinctive terms in document title are high-signal
    title_hits = sum(1 for t in terms if t.lower() in title.lower())
    if title_hits:
        score += 2.5 * title_hits

    # Site-agnostic path + filename/title overlap (PDFs + crawled URL titles)
    if question:
        score += path_rank_bonus(question, title)
        score += filename_term_bonus(question, title, terms)

    # Generic quality: demote chrome, prefer dated materials when present
    chrome = float(sig.get("chrome_score") or 0.0)
    prose = float(sig.get("prose_score") or 0.0)
    if chrome or prose:
        score -= 5.0 * chrome
        score += 2.5 * prose
    else:
        score -= 4.0 * boilerplate_penalty(blob)
    score += recency_bonus(title, text)
    score += roster_evidence_bonus(question, title, text)
    score += officer_role_evidence_bonus(question, title, text)

    # Evidence-contract fit (primary smart ranking signal)
    if contract is not None:
        fit = contract_fit_score(contract, title, text, question=question, signals=sig)
        score += 10.0 * fit
        if sig.get("doc_kind") == "spotlight" and contract.shape == "list_people":
            score -= 6.0
        # Press/letters help appointment news for rosters; for single-role who-is
        # they often preserve former officers — demote when we have org-chart text.
        if sig.get("doc_kind") in {"press", "letter"}:
            if contract.shape == "list_people":
                score += 3.0
            elif contract.shape == "attribute" and is_officer_attribute_question(question):
                score -= 6.0

    # Slight boost when many question terms co-occur (answer-shaped passage)
    if question:
        ov = question_term_overlap(terms, blob)
        score += 3.0 * ov
        if is_org_roster_question(question) and person_title_names(blob):
            score += 2.0
        elif is_org_roster_question(question) and not person_title_names(blob):
            score -= 3.0
        # Factoid: boost metric numerals near distinctive terms
        if contract is not None and contract.shape == "factoid":
            if re.search(
                r"\b\d{1,3}(?:,\d{3})+\+?\b|\b\d+\+\s*(?:years?|offices?|countries?)?\b",
                blob,
                re.I,
            ):
                score += 4.0
            # Demote personal tenure narratives for org how-long / how-many
            ql = question.lower()
            if re.search(r"\b(how\s+long|how\s+many)\b", ql) and re.search(
                r"\b\d+\+?\s+years?\s+of\s+(?:experience|career|technology consulting)\b",
                blob,
                re.I,
            ):
                if not re.search(
                    r"\b(?:more\s+than|over)\s+\d{1,3}(?:,\d{3})+|"
                    r"\b\d+\+\s+years?\s+of\s+technology\s+consulting\b|"
                    r"\b\d+\s+offices?\b",
                    blob,
                    re.I,
                ):
                    score -= 5.0
        # Define / capabilities: prefer service-shaped pages and triad / list structure
        if contract is not None and contract.shape == "define":
            ql = question.lower()
            dens = offering_list_density(text)
            if dens >= 0.55 or is_service_page(title):
                score += 3.5
            if ("pathway" in ql or "transformation" in ql) and has_transformation_triad(
                text
            ):
                score += 10.0
            if "pathway" in ql and is_career_pathway_page(title):
                score -= 12.0
            if re.search(r"\b(capabilities|services|offerings?|solutions)\b", ql):
                if is_service_page(title):
                    score += 8.0
                elif dens >= 0.55:
                    score += 5.0
            # Demote blog/news chrome for short define/list asks
            if is_insight_chrome_page(title) and re.search(
                r"\b(pathway|capabilities|services|offerings?)\b", ql
            ):
                score -= 6.0
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
    contract: EvidenceContract | None = None,
) -> RetrievalPack:
    """Build a coverage-complete quote pack from the whole knowledge base."""
    if store is None:
        return RetrievalPack(quotes=[], mode="empty", coverage=0.0, required_terms=[])

    contract = contract or detect_evidence_contract(question)

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
        sig = signals_from_chunk(ch, title=title, text=text)
        if sig.get("quarantine"):
            return
        sc = _score_chunk(
            text,
            title,
            terms,
            base=base,
            question=question,
            contract=contract,
            signals=sig,
        )
        prev = cand.get(cid)
        if prev is None or sc > prev[0]:
            cand[cid] = (sc, ch, text, title, edge_id or (prev[4] if prev else None))

    roster_q = contract.shape == "list_people" or is_org_roster_question(question)

    # 1) Lexical scan of all chunks
    for ch in chunks:
        text = ch.get("text") or ""
        if len(text.strip()) < 20:
            continue
        title = docs.get(ch.get("canonical_document_id"), "") or "document"
        sig = signals_from_chunk(ch, title=title, text=text)
        if sig.get("quarantine"):
            continue
        low = f"{title}\n{text}".lower()
        shape_hit = False
        if contract.shape == "define":
            ql = question.lower()
            if ("pathway" in ql or "transformation" in ql) and has_transformation_triad(
                text
            ):
                shape_hit = True
            if re.search(
                r"\b(capabilities|services|offerings?|solutions)\b", ql
            ) and service_support_hit(title, text):
                shape_hit = True
        if not _term_hits(text, title, terms) and terms:
            # Contract: still consider passages that satisfy shape without soft terms
            if not (
                (
                    roster_q
                    and (
                        sig.get("has_person_role")
                        or len(person_title_names(f"{title}\n{text}")) >= 1
                    )
                )
                or shape_hit
            ):
                continue
        add_chunk(ch, text, title, base=0.85 if shape_hit else 0.55)

    # 1b) Roster / list_people scan — surface officer-named passages
    if roster_q:
        for ch in chunks:
            text = ch.get("text") or ""
            if len(text.strip()) < 40:
                continue
            title = docs.get(ch.get("canonical_document_id"), "") or "document"
            sig = signals_from_chunk(ch, title=title, text=text)
            if sig.get("quarantine"):
                continue
            people = person_title_names(f"{title}\n{text}")
            if len(people) < 1 and not sig.get("has_person_role"):
                continue
            add_chunk(ch, text, title, base=0.7 + 0.05 * min(len(people) or 1, 6))

    # 1b2) Single-role who-is (CEO/CFO/CTO) — prefer org-chart bindings over bios/letters
    if is_officer_attribute_question(question):
        ql_off = question.lower()
        role_pats: list[re.Pattern[str]] = []
        if re.search(r"\b(ceo|chief\s+executive)\b", ql_off):
            role_pats.append(
                re.compile(
                    r"(serves\s+as\s+chief\s+executive|chief\s+executive\s+officer)",
                    re.I,
                )
            )
        if re.search(r"\b(cfo|chief\s+financial)\b", ql_off):
            role_pats.append(
                re.compile(
                    r"(serves\s+as\s+chief\s+financial|chief\s+financial\s+officer)",
                    re.I,
                )
            )
        if re.search(r"\b(cto|chief\s+technology)\b", ql_off):
            role_pats.append(
                re.compile(
                    r"(serves\s+as\s+chief\s+technology|chief\s+technology\s+officer)",
                    re.I,
                )
            )
        for ch in chunks:
            text = ch.get("text") or ""
            if len(text.strip()) < 20:
                continue
            title = docs.get(ch.get("canonical_document_id"), "") or "document"
            blob = f"{title}\n{text}"
            if not any(p.search(blob) for p in role_pats):
                continue
            # Need a person name near the role binding
            if not person_title_names(blob) and not re.search(
                r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b.{0,80}chief", blob
            ):
                continue
            base = 1.4
            tl = title.lower()
            if "leaders" in tl:
                base += 0.4
            add_chunk(ch, text, title, base=base)

    # 1c) Define pathway / offerings — force triad & service-shaped pages into the pack
    if contract.shape == "define":
        ql = question.lower()
        for ch in chunks:
            text = ch.get("text") or ""
            if len(text.strip()) < 40:
                continue
            title = docs.get(ch.get("canonical_document_id"), "") or "document"
            if ("pathway" in ql or "transformation" in ql) and has_transformation_triad(
                text
            ):
                add_chunk(ch, text, title, base=1.35)
            elif re.search(
                r"\b(capabilities|services|offerings?|solutions|capability)\b", ql
            ) and (is_service_page(title) or offering_list_density(text) >= 0.55):
                add_chunk(ch, text, title, base=1.2)

    # 1d) Section-path force — when the question names a site section, prefer that path
    # (works for /history, /partnerships, /careers, /radar, etc. on any domain)
    ql = question.lower()
    section_hints: list[tuple[str, tuple[str, ...]]] = [
        (r"\b(history|founded|founding)\b", ("_history", "/history", "about-us_history")),
        (r"\b(purpose|mission)\b", ("purpose", "our-purpose", "our_purpose")),
        (r"\b(partner|partnership|aws|azure|gcp)\b", ("partnership", "partners")),
        (r"\b(career|careers|working there|join us)\b", ("career", "careers")),
        (r"\b(radar)\b", ("_radar", "/radar", "radar_")),
        (
            r"\b(diversity|inclusion|equity|dei)\b",
            ("diversity", "inclusion"),
        ),
        (r"\b(social change|social impact)\b", ("social-change", "social_change")),
        (
            r"\b(software-defined|software defined)\b",
            ("software-defined", "software_defined"),
        ),
        (
            r"\b(iso\s*27001|iso27001|certification)\b",
            ("iso-27001", "iso_27001", "iso27001", "certification"),
        ),
        (
            r"\b(readiness)\b",
            ("readiness",),
        ),
    ]
    active_markers: list[str] = []
    for pat, markers in section_hints:
        if re.search(pat, ql):
            active_markers.extend(markers)
    if is_officer_attribute_question(question):
        active_markers.extend(
            ("_leaders", "/leaders", "about-us_leaders", "profiles_leaders")
        )
    if active_markers:
        for ch in chunks:
            text = ch.get("text") or ""
            if len(text.strip()) < 40:
                continue
            title = docs.get(ch.get("canonical_document_id"), "") or "document"
            tl = title.lower()
            if any(m in tl for m in active_markers):
                # Prefer corporate section pages over news that merely mention the word
                boost = 1.4 if not is_insight_chrome_page(title) else 0.95
                # history ask: demote "natural history museum" news vs about/history
                if "history" in ql and "history" in tl and "museum" in tl:
                    continue
                add_chunk(ch, text, title, base=boost)

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

    # 3) Graph evidence — base scaled by question relevance (never flat crown)
    graph_primary = bool(graph_quotes) and any(gq.edge_id for gq in graph_quotes or [])
    graph_blob = " ".join(
        f"{gq.document_title} {gq.quote}" for gq in (graph_quotes or [])
    )
    trail_rel = trail_answer_relevance(question, None, graph_blob, terms)
    for gq in graph_quotes or []:
        ch = next((c for c in chunks if c["id"] == gq.chunk_id), None)
        g_blob = f"{gq.document_title}\n{gq.quote}"
        quote_rel = trail_answer_relevance(question, None, g_blob, terms)
        g_base = graph_quote_base(
            max(trail_rel, quote_rel),
            float(gq.score or 0.8),
        )
        if not ch:
            fake = {
                "id": gq.chunk_id,
                "canonical_document_id": None,
                "loc": {"locator": gq.locator},
            }
            add_chunk(fake, gq.quote, gq.document_title, base=min(g_base, 0.85), edge_id=gq.edge_id)
            continue
        text = ch.get("text") or gq.quote
        title = docs.get(ch.get("canonical_document_id"), gq.document_title) or gq.document_title
        prefer = gq.quote if gq.quote and len(gq.quote) >= 24 else text
        add_chunk(ch, prefer, title, base=g_base, edge_id=gq.edge_id)

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

    # Prefer multi-word / coded terms; drop filler number-word phrases for gap-fill
    must = [
        t
        for t in terms
        if _is_strong(t)
        and not re.search(
            r"\b(one|two|three|four|five|six|seven|eight|nine|ten|some|several)\b",
            t,
            re.I,
        )
    ] or [t for t in terms[:5] if t.lower() not in _STOP_SOFT] or terms[:3]
    pack_blob = " ".join(f"{title} {text}" for _, _, text, title, _ in selected).lower()
    for term in must:
        if term.lower() in pack_blob:
            continue
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
        if edge_id and len(text.strip()) <= 560:
            quote = text.strip()
        else:
            quote = _window(text, terms, question=question)
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

    quotes = await rerank_quotes(ctx, question, quotes, top_k=max(top_k, 8))

    # Roster: drop chrome/culture quotes that name nobody with a title
    if roster_q and quotes:
        named = [q for q in quotes if person_title_names(f"{q.document_title}\n{q.quote}")]
        if named:
            # Keep named officers first; allow at most one unnamed context quote
            rest = [q for q in quotes if q not in named][:1]
            quotes = (named + rest)[: max(top_k, 8)]

    # Trust: drop padding quotes that don't support the question
    if quotes and not prefer_overview:
        pruned = prune_supporting_quotes(
            contract, quotes, question, min_support=0.38, max_keep=max(5, top_k // 2)
        )
        if pruned:
            quotes = pruned

    cov = coverage_ratio(quotes, must if must else terms)
    mode = "hybrid_kb"
    top_overlap = 0.0
    if quotes[:3]:
        top_blob = " ".join(f"{q.document_title} {q.quote}" for q in quotes[:3])
        top_overlap = question_term_overlap(terms, top_blob)
    graph_tops = sum(1 for q in quotes[:3] if q.edge_id)
    if graph_primary and graph_tops >= 1 and top_overlap >= 0.45 and trail_rel >= 0.45:
        mode = "graph_primary" if cov >= 0.45 else "hybrid_graph_kb"
    elif graph_quotes and any(q.edge_id for q in quotes):
        mode = "hybrid_graph_kb"
    # Weak trail relevance → never crown as graph_primary
    if trail_rel < 0.35:
        mode = "hybrid_kb" if not any(q.edge_id for q in quotes) else "hybrid_graph_kb"
        if trail_rel < 0.2:
            mode = "hybrid_kb"
    if prefer_overview and cov < 0.35 and overview_quotes:
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
    q_l = question.lower()
    q_terms = [t for t in re.findall(r"[a-z0-9]{3,}", q_l) if t not in _STOP_SOFT]

    def _heuristic(q: QuoteHit) -> float:
        blob = f"{q.document_title} {q.quote}"
        term_hit = sum(1 for t in q_terms if t in blob.lower())
        # Graph is a weak prior — only helps when overlap is already decent
        ov = question_term_overlap(q_terms, blob)
        graph_bonus = 0.12 if q.edge_id and ov >= 0.35 else 0.0
        length_pen = 0.05 if len(q.quote) < 40 else 0.0
        roster_b = roster_evidence_bonus(question, q.document_title, q.quote)
        contract = detect_evidence_contract(question)
        fit = contract_fit_score(contract, q.document_title, q.quote, question=question)
        return (
            float(q.score)
            + 0.08 * term_hit
            + graph_bonus
            + 0.1 * recency_bonus(q.document_title, q.quote)
            + 0.08 * roster_b
            + 0.35 * fit
            - 0.25 * boilerplate_penalty(blob)
            - length_pen
        )

    ordered = sorted(quotes, key=_heuristic, reverse=True)

    if ctx.llm is None or len(ordered) < 3:
        return ordered[:top_k]

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
                        "useful for answering the question. Prefer passages that directly "
                        "support an answer with specific facts. Prefer concrete content over "
                        "navigation/menus/footers. When sources conflict, prefer current/"
                        "newer dated wording over outdated. Prefer graph-backed quotes only "
                        "when equally relevant. Do not invent quotes; only permute indices."
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
            # Rank position only — no free edge_id score bump
            q.score = min(0.99, 0.99 - 0.04 * len(reranked))
            reranked.append(q)
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
