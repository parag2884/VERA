"""Domain-agnostic answer-relevance helpers for Ask retrieval.

Graph and KB compete on the same signals: term overlap, boilerplate demotion,
recency when dates appear. No question-type / role / domain word lists.
"""

from __future__ import annotations

import re

from app.knowledge.signals.text_terms import boilerplate_penalty, person_title_names

# Soft words that match site chrome but rarely answer anything alone.
_VAGUE_SINGLETONS = frozenset(
    {
        "about",
        "team",
        "teams",
        "page",
        "home",
        "site",
        "menu",
        "contact",
        "learn",
        "more",
        "click",
        "here",
        "read",
        "see",
        "view",
        "info",
        "information",
        "general",
        "overview",
        "introduction",
        "leadership",
        "leader",
        "leaders",
        "executive",
        "executives",
        "management",
    }
)

# Person + senior org-role co-occurrence (generic — not company-specific).
# Case-sensitive on names so soft words are never treated as person tokens.
# Avoid bare Director/Officer/Partner — too common in spotlights and nav.
# Allow "Chief People and Leadership Officer" / multi-word Chief titles
_ORG_TITLE = (
    r"(?:Executive\s+Vice\s+President|Vice\s+President|"
    r"Chief\s+Executive\s+Officer|Chief\s+Operating\s+Officer|"
    r"Chief\s+Financial\s+Officer|Chief\s+Information\s+Officer|"
    r"Chief\s+[A-Z][A-Za-z]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z]+)*"
    r"(?:\s+[A-Z][A-Za-z]+){0,3}\s+Officer|"
    r"Managing\s+Director|President(?:\s+and\s+CEO)?|Chairman|Chairwoman|Chair|"
    r"CEO|COO|CFO|CTO|CIO|CHRO|CMO|CLO|EVP|SVP)"
)
# Names stay mostly on one line; allow a single newline before the title (roster pages)
# Allow hyphenated surnames (Reid-Dodick) and internal capitals after hyphen
_PERSON_NAME = (
    r"([A-Z][a-z]+(?:[ \t]+[A-Z]\.?)?(?:[ \t]+[A-Z][A-Za-z'’-]+)+)"
)
_NAME_TITLE_GAP = r"(?:[ \t]*[,–—\-][ \t]*|[ \t]+|[ \t]*\n[ \t]*)"
_PERSON_THEN_TITLE = re.compile(
    rf"\b{_PERSON_NAME}\b{_NAME_TITLE_GAP}{_ORG_TITLE}\b"
)
_TITLE_THEN_PERSON = re.compile(
    rf"\b{_ORG_TITLE}\b(?:[ \t]+|[ \t]*\n[ \t]*){_PERSON_NAME}\b"
)
# Words that look like person-name tokens but are titles/org/legal crumbs.
_NAME_BLOCKLIST = frozenset(
    {
        "president",
        "chairman",
        "chairwoman",
        "chief",
        "executive",
        "operating",
        "financial",
        "information",
        "officer",
        "vice",
        "managing",
        "director",
        "partner",
        "board",
        "company",
        "senior",
        "global",
        "recognized",
        "search",
        "articles",
        "editor",
        "more",
        "office",
        "march",
        "april",
        "june",
        "july",
        "both",
        "says",
        "great",
        "place",
        "work",
        "regional",
        "services",
        "inc",
        "llc",
        "corp",
        "corporation",
        "limited",
        "group",
        "holdings",
    }
)
_SPOTLIGHT_TITLE = re.compile(
    r"\b(spotlight|employee of the|team of the|"
    r"celebrat(?:e|ing)|culture\s+story|meet (?:the|our) team)\b",
    re.I,
)
_ORG_ROSTER_SCOPE = re.compile(
    r"\b(leadership|executive|executives|c-?suite|"
    r"board(?:\s+of\s+directors)?|officers?|"
    r"management\s+team|senior\s+leaders?)\b",
    re.I,
)


def normalize_terms(terms: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in terms or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if len(s) < 2:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def question_terms_from_text(question: str) -> list[str]:
    """Lightweight distinctive terms from the question (no domain lists)."""
    q = question or ""
    terms: list[str] = []
    for m in re.finditer(r"\b([A-Z]{2,}\d{2,}|\d{3,}[A-Z]+|[A-Z]{3,}\d+)\b", q):
        terms.append(m.group(1))
    for m in re.finditer(r"[\"']([^\"']{3,80})[\"']", q):
        terms.append(m.group(1).strip())
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", q):
        if w.lower() in _VAGUE_SINGLETONS:
            continue
        terms.append(w)
    # Short uppercase tokens in the query (CEO, API, SLA, …) — no domain list
    for w in re.findall(r"\b[A-Z]{2,4}\b", q):
        terms.append(w)
    return normalize_terms(terms)


def question_term_overlap(terms: list[str], blob: str) -> float:
    """Fraction of distinctive terms present in blob (0..1)."""
    terms = [t for t in normalize_terms(terms) if t.lower() not in _VAGUE_SINGLETONS]
    if not terms:
        return 0.0
    low = (blob or "").lower()
    hit = sum(1 for t in terms if t.lower() in low)
    return hit / len(terms)


def recency_bonus(title: str, text: str) -> float:
    """Mild preference for newer dated materials when years appear."""
    blob = f"{title}\n{(text or '')[:500]}"
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", blob)]
    if not years:
        return 0.0
    newest = max(years)
    return max(0.0, min(1.6, (newest - 2016) * 0.16))


def trail_answer_relevance(
    question: str,
    hop_names: list[str] | None,
    evidence_blob: str,
    terms: list[str] | None = None,
) -> float:
    """0..1 how well a graph trail's hops+evidence match the question."""
    terms = normalize_terms(terms) or question_terms_from_text(question)
    # Drop pure stop-ish who/what from overlap for graph (keep content terms)
    content = [
        t
        for t in terms
        if t.lower()
        not in {
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "which",
            "does",
            "did",
            "are",
            "is",
        }
    ]
    if not content:
        content = terms
    blob_parts = [evidence_blob or ""]
    blob_parts.extend(n for n in (hop_names or []) if n)
    blob = "\n".join(blob_parts)
    overlap = question_term_overlap(content, blob)
    # Boilerplate evidence cannot be "highly relevant" even if soft terms match
    pen = boilerplate_penalty(evidence_blob or "")
    score = max(0.0, overlap - 0.35 * pen)
    # Require at least one non-entity content hit for mid/high scores when
    # hop names alone echo a company seed entity → anything.
    evidence_overlap = question_term_overlap(content, evidence_blob or "")
    if evidence_overlap < 0.15 and pen >= 0.35:
        score = min(score, 0.12)
    return max(0.0, min(1.0, score))


def graph_should_lead(
    relevance: float,
    path_strength: float,
    pack_coverage: float,
) -> bool:
    """Whether graph evidence may crown the quote pack (all question types)."""
    if relevance < 0.35:
        return False
    if path_strength < 0.55:
        return False
    # Strong pack coverage with weak trail relevance → hybrid wins
    if pack_coverage >= 0.45 and relevance < 0.55:
        return False
    return relevance >= 0.45 and path_strength >= 0.6


def graph_quote_base(relevance: float, quote_confidence: float = 0.8) -> float:
    """Base score for injecting a graph quote into the hybrid candidate pool."""
    # Weak overlap → lexical KB can outrank; never a flat 0.9 crown
    conf = max(0.0, min(1.0, float(quote_confidence or 0.8)))
    rel = max(0.0, min(1.0, relevance))
    if rel < 0.2:
        return 0.28 + 0.1 * conf
    if rel < 0.45:
        return 0.4 + 0.25 * rel + 0.05 * conf
    return 0.55 + 0.4 * rel + 0.05 * conf


def is_org_roster_question(question: str) -> bool:
    """Who/list questions about leadership / executives / board (any company)."""
    q = question or ""
    ql = q.lower().strip()
    if not _ORG_ROSTER_SCOPE.search(ql):
        return False
    # Single-role asks are attributes, not full roster dumps
    # ("Who is … Chief People and Leadership Officer?")
    if re.search(
        r"\bwho\s+(?:is|was)\b.{0,80}\b("
        r"ceo|coo|cfo|cto|cmo|chro|cio|clo|chairman|chairwoman|chair|president|"
        r"chief\s+\w+(?:\s+(?:and|&)\s+\w+)*(?:\s+\w+){0,3}\s+officer"
        r")\b",
        ql,
    ):
        return False
    whoish = bool(
        re.search(
            r"\b(who|whom|which|names?|roster|members?|compose[sd]?|"
            r"on\s+the|list|tell\s+me\s+about)\b",
            ql,
        )
    )
    # Short prompts like "Leadership team?" / "What about executive team?"
    short = len(re.findall(r"[a-zA-Z]+", ql)) <= 7
    return whoish or short or ("?" in q)


def needs_team_scope_clarify(question: str) -> bool:
    """Bare 'who/team' with no org-leadership scope → ask which team."""
    ql = (question or "").lower().strip()
    if not ql:
        return False
    if _ORG_ROSTER_SCOPE.search(ql):
        return False
    if re.fullmatch(r"\s*(the\s+)?team\s*\??\s*", ql):
        return True
    if re.search(
        r"\bwho\b.{0,40}\bteam\b|\bteam\b.{0,40}\bwho\b|"
        r"\bwho all\b|\bmembers of (the |our )?team\b|"
        r"\bwho(?:'s| is| are) (on |in )?(the |our )?team\b",
        ql,
    ):
        return True
    return False


def roster_evidence_bonus(question: str, title: str, text: str) -> float:
    """Score delta for org-roster questions: prefer named officers, demote chrome/spotlights."""
    if not is_org_roster_question(question):
        return 0.0
    blob = f"{title or ''}\n{text or ''}"
    people = person_title_names(blob)
    bonus = 0.0
    n = len(people)
    if n >= 2:
        bonus += 12.0 + 2.0 * min(n, 8)
    elif n == 1:
        bonus += 6.0
    else:
        # Soft leadership words with no named officers → almost always nav/culture
        if re.search(r"\b(leadership|executive|board)\b", blob, re.I):
            bonus -= 7.0
    if _SPOTLIGHT_TITLE.search(title or "") and n < 2:
        bonus -= 8.0
    tl = (title or "").lower()
    if n and any(
        k in tl
        for k in (
            "named",
            "appoint",
            "executive",
            "board",
            "officer",
            "ceo",
            "press",
            "newsroom",
            "letter",
            "leadership",
        )
    ):
        bonus += 4.0
    return bonus


_OFFICER_WHO = re.compile(
    r"\bwho\s+(?:is|was)\b.{0,100}\b("
    r"ceo|coo|cfo|cto|cmo|chro|cio|clo|chairman|chairwoman|chair|president|"
    r"chief\s+\w+(?:\s+(?:and|&)\s+\w+)*(?:\s+\w+){0,3}\s+officer"
    r")\b",
    re.I,
)

_ROLE_IN_Q = {
    "ceo": re.compile(r"\b(ceo|chief\s+executive(?:\s+officer)?)\b", re.I),
    "cfo": re.compile(r"\b(cfo|chief\s+financial(?:\s+officer)?)\b", re.I),
    "cto": re.compile(r"\b(cto|chief\s+technology(?:\s+officer)?)\b", re.I),
    "coo": re.compile(r"\b(coo|chief\s+operating(?:\s+officer)?)\b", re.I),
}

_PAST_OFFICE = re.compile(
    r"\b(former|ex-|stepped\s+down|until\s+20\d\d|from\s+20\d\d\s+(?:to|until|through)\b|"
    r"was\s+the\s+c[efot]o|served\s+as\s+c[efot]o)\b",
    re.I,
)


def is_officer_attribute_question(question: str) -> bool:
    """Single-role who-is (CEO/CFO/CTO/Chief … Officer), not a full roster dump."""
    return bool(_OFFICER_WHO.search(question or ""))


def officer_role_evidence_bonus(question: str, title: str, text: str) -> float:
    """Prefer current org-chart pages over historical CEO letters / regional CTOs."""
    if not is_officer_attribute_question(question):
        return 0.0
    blob = f"{title or ''}\n{text or ''}"
    bl = blob.lower()
    tl = (title or "").lower()
    bonus = 0.0
    # Hub / org-chart pages that bind name → role
    if any(k in tl for k in ("/leaders", "_leaders", "leadership", "/profiles/leaders")):
        bonus += 10.0
    if re.search(r"\bserves\s+as\s+chief\b", bl):
        bonus += 12.0
    # Role asked appears next to a person-name pattern
    for key, rx in _ROLE_IN_Q.items():
        if not rx.search(question or ""):
            continue
        if key == "ceo" and re.search(
            r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b.{0,40}\bchief\s+executive|\bserves\s+as\s+chief\s+executive",
            blob,
        ):
            bonus += 8.0
        if key == "cfo" and re.search(
            r"\bserves\s+as\s+chief\s+financial|\bchief\s+financial\s+officer\b",
            bl,
        ):
            bonus += 8.0
        if key == "cto" and re.search(
            r"\bserves\s+as\s+chief\s+technology|\bchief\s+technology\s+officer\b",
            bl,
        ):
            bonus += 8.0
            # Regional CTOs are weaker than global org-chart
            if re.search(r"\b(americas|emea|europe|asia|region)\b.{0,40}\bcto\b|\bcto\b.{0,40}\b(americas|emea|europe|asia)\b", bl):
                bonus -= 10.0
    if _PAST_OFFICE.search(blob):
        bonus -= 14.0
    if re.search(r"\b(emerita|emeritus|i\s+became\s+cto|was\s+the\s+cto)\b", bl):
        bonus -= 12.0
    if any(k in tl for k in ("insights", "blog", "news", "letter", "social-change", "report")):
        bonus -= 8.0
    return bonus


# --- Narrative / fiction-friendly entity matching (domain-agnostic) ---

_NARRATIVE_STOP = frozenset(
    {
        "the",
        "and",
        "who",
        "what",
        "when",
        "where",
        "which",
        "with",
        "from",
        "into",
        "this",
        "that",
        "according",
        "about",
        "after",
        "before",
        "became",
        "become",
        "happened",
        "central",
        "friend",
        "helps",
        "land",
        "city",
        "book",
        "books",
        "novel",
        "story",
        "series",
        "document",
        "knowledge",
        "base",
    }
)

_WORK_TITLE_IN_Q = re.compile(
    r"\b(?:in|according\s+to|from|per)\s+"
    r"(?:the\s+)?([A-Z][\w'’\-]+(?:\s+(?:of|the|and|in|a|an|to|&)?\s*[A-Z][\w'’\-]+){0,8})",
)


def name_match_variants(name: str) -> list[str]:
    """Expand hyphen/apostrophe proper names for matching (e.g. A-B ↔ AB, Cap'n ↔ Captain)."""
    raw = (name or "").strip()
    if len(raw) < 2:
        return []
    out: list[str] = [raw]
    collapsed = re.sub(r"['’\-]+", "", raw)
    if collapsed and collapsed.lower() != raw.lower():
        out.append(collapsed)
    spaced = re.sub(r"[\-]+", " ", raw)
    if spaced and spaced.lower() not in {x.lower() for x in out}:
        out.append(spaced)
    # Cap'n → Captain (common narrative shortening)
    if re.search(r"\bcap['’]?n\b", raw, re.I):
        out.append(re.sub(r"\bcap['’]?n\b", "Captain", raw, flags=re.I))
    return normalize_terms(out)


def extract_proper_nouns(question: str) -> list[str]:
    """Capitalized person/place-like tokens from the question (not a brand lexicon)."""
    q = question or ""
    found: list[str] = []
    # Hyphenated / apostrophe / multi-word capitalized names from the question
    for m in re.finditer(
        r"\b([A-Z][A-Za-z]*['’][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?|"
        r"[A-Z][A-Za-z]+(?:-[A-Z][A-Za-z]+)+|"
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b",
        q,
    ):
        name = m.group(1).strip()
        parts = [p for p in re.split(r"[\s\-]+", name) if p]
        if all(p.lower() in _NARRATIVE_STOP for p in parts):
            continue
        if name.lower() in _NARRATIVE_STOP:
            continue
        found.append(name)
    # Single unusual capitals mid-sentence after "who is/are"
    for m in re.finditer(
        r"\b(?:who\s+(?:is|are|was|were)|named|called)\s+([A-Z][\w'’\-]{2,40})\b",
        q,
    ):
        found.append(m.group(1))
    return normalize_terms(found)


def extract_work_title_hints(question: str) -> list[str]:
    """Book/doc titles referenced in the question (e.g. 'In The …', 'According to …')."""
    q = question or ""
    hints: list[str] = []
    for m in _WORK_TITLE_IN_Q.finditer(q):
        title = re.sub(r"\s+", " ", m.group(1)).strip(" ?.,;:")
        if len(title) >= 6:
            hints.append(title)
    for m in re.finditer(r"[“\"]([^”\"]{6,80})[”\"]", q):
        hints.append(m.group(1).strip())
    return normalize_terms(hints)


def narrative_search_terms(question: str) -> list[str]:
    """Extra lexical terms for narrative/character questions (variants included)."""
    out: list[str] = []
    for name in extract_proper_nouns(question):
        out.extend(name_match_variants(name))
    for hint in extract_work_title_hints(question):
        out.append(hint)
        # Also add distinctive tokens from the work title
        for tok in re.findall(r"[A-Za-z][A-Za-z'’\-]{3,}", hint):
            if tok.lower() not in _NARRATIVE_STOP:
                out.append(tok)
    return normalize_terms(out)


def narrative_entity_bonus(question: str, title: str, text: str) -> float:
    """Score delta when question entities / work titles appear in the passage."""
    q = question or ""
    if not q.strip():
        return 0.0
    # Skip when this is clearly an org-officer ask — roster/officer bonuses own that
    if is_officer_attribute_question(q) or is_org_roster_question(q):
        return 0.0
    blob = f"{title or ''}\n{text or ''}"
    bl = blob.lower()
    tl = (title or "").lower()
    bonus = 0.0

    nouns = extract_proper_nouns(q)
    hit_names = 0
    for name in nouns:
        variants = name_match_variants(name)
        if any(v.lower() in bl for v in variants):
            hit_names += 1
            bonus += 6.0
            # Stronger when the entity is near definitional phrasing
            for v in variants:
                if re.search(
                    rf"\b{re.escape(v)}\b.{{0,60}}\b("
                    r"is|was|are|were|named|called|known\s+as|became|who)\b|"
                    rf"\b(is|was|are|were|named|called)\b.{{0,40}}\b{re.escape(v)}\b",
                    blob,
                    re.I,
                ):
                    bonus += 4.0
                    break
    if hit_names >= 2:
        bonus += 5.0

    for hint in extract_work_title_hints(q):
        ht = hint.lower()
        # Document title overlap with referenced work
        hint_toks = [
            t
            for t in re.findall(r"[a-z0-9]{4,}", ht)
            if t not in _NARRATIVE_STOP
        ]
        if hint_toks:
            overlap = sum(1 for t in hint_toks if t in tl)
            if overlap >= max(2, len(hint_toks) // 2):
                bonus += 10.0
            elif overlap >= 1 and any(t in bl[:800] for t in hint_toks):
                bonus += 4.0
        if ht in bl or ht in tl:
            bonus += 6.0

    # Who/what-is questions with at least one entity hit are high-value
    if hit_names and re.search(r"\b(who|what)\s+(is|are|was|were|happened)\b", q, re.I):
        bonus += 3.0
    return bonus
