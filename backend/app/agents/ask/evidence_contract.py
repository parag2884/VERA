"""Generic evidence contracts — question shape → what quotes must prove.

Domain-agnostic: no company/role word lists. Roster/team clarify folds into
`list_people`. Used by retrieve ranking and the strict evidence judge.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.ask.comparison import extract_compare_sides, is_comparison_question
from app.agents.ask.page_signals import (
    has_transformation_triad,
    service_support_hit,
)
from app.agents.ask.relevance import (
    boilerplate_penalty,
    is_org_roster_question,
    needs_team_scope_clarify,
    person_title_names,
    question_term_overlap,
    question_terms_from_text,
)
from app.schemas import ClarifyOption

EvidenceShape = Literal[
    "list_people",
    "attribute",
    "how_to",
    "compare",
    "define",
    "factoid",
    "open",
]


class EvidenceContract(BaseModel):
    shape: EvidenceShape = "open"
    needs_clarify: bool = False
    clarification_prompt: str | None = None
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    compare_sides: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


_HOW_TO = re.compile(
    r"\b(how\s+(do|can|to|does|should)|steps?\b|renew|process|procedure|"
    r"install|configure|set\s*up|enable)\b",
    re.I,
)
_DEFINE = re.compile(
    r"\b(what\s+is|what\s+are|what'?s|define|definition\s+of|meaning\s+of|"
    r"name\s+some|list\s+some|name\s+(?:the|a few)|what\s+capabilities|"
    r"what\s+services)\b",
    re.I,
)
_FACTOID = re.compile(
    r"\b(when|where|how\s+many|how\s+much|how\s+long|how\s+old|"
    r"which\s+year|what\s+date|located|address|office\s+in)\b",
    re.I,
)
_ATTRIBUTE = re.compile(
    r"\bwho\s+is\b|\bwho\s+was\b|\bwhat\s+is\s+.+\s+(title|role|position)\b|"
    r"\b(ceo|coo|cfo|cto|cmo|chro|chairman|president|chief\s+\w+(?:\s+\w+)?\s+officer)\s+of\b|"
    r"\bwho\s+(?:is\s+)?(?:the\s+)?"
    r"(ceo|coo|cfo|cto|cmo|chro|chairman|president|"
    r"chief\s+[\w]+(?:\s+(?:and\s+)?[\w]+){0,4}\s+officer)\b",
    re.I,
)
_SINGLE_ROLE_WHO = re.compile(
    r"\bwho\s+(?:is|was)\b.{0,80}\b("
    r"ceo|coo|cfo|cto|cmo|chro|cio|clo|chairman|chairwoman|chair|president|"
    r"chief\s+[\w]+(?:\s+(?:and\s+|&)\s+[\w]+)*(?:\s+[\w]+){0,3}\s+officer"
    r")\b",
    re.I,
)
_ACTIONABLE = re.compile(
    r"\b(must|should|require[sd]?|step\s*\d|first|then|next|click|select|"
    r"submit|enable|disable|configure|install|renew)\b",
    re.I,
)
_DEFINITIONAL = re.compile(
    r"\b(is\s+a|are\s+a|refers\s+to|means|defined\s+as|consists\s+of|"
    r"provides|represents)\b",
    re.I,
)
_CONCRETE = re.compile(
    r"("
    r"\b20\d{2}\b|"
    r"\b\d{1,3}(?:,\d{3})+\+?\b|"  # 10,000 / 10,000+
    r"\b\d+\+\b|"  # 30+
    r"\b\d{1,5}\s*(?:%|percent|pages?|people|employees?|thoughtworkers?|"
    r"offices?|countries?|years?|months?|decades?)\b|"
    r"\b\d+\s+(?:street|ave|road|blvd)\b"
    r")",
    re.I,
)


_OOD_HINT = re.compile(
    r"\b(weather|forecast|temperature|humidity|capital of|"
    r"stock price|lottery|sports score)\b",
    re.I,
)


def detect_evidence_contract(question: str) -> EvidenceContract:
    """Infer the evidence shape required to answer `question`."""
    q = (question or "").strip()
    if not q:
        return EvidenceContract(shape="open")

    # World-knowledge / OOD prompts stay open — judge refuses when KB is silent
    if _OOD_HINT.search(q):
        return EvidenceContract(shape="open", reason_codes=["LIKELY_OUT_OF_KB"])

    if needs_team_scope_clarify(q):
        return EvidenceContract(
            shape="list_people",
            needs_clarify=True,
            clarification_prompt=(
                "Which team do you mean? Executive leadership, the board, "
                "or a specific department team?"
            ),
            clarify_options=[
                ClarifyOption(
                    id="executive_leadership",
                    label="Executive leadership team",
                    description="C-suite / named company executives",
                ),
                ClarifyOption(
                    id="board_of_directors",
                    label="Board of directors",
                    description="Directors and board leadership",
                ),
                ClarifyOption(
                    id="specific_department",
                    label="A specific department team",
                    description="Name the department or function (e.g. sales, engineering)",
                ),
            ],
            reason_codes=["TEAM_SCOPE_AMBIGUOUS"],
        )

    if is_comparison_question(q):
        sides = extract_compare_sides(q)
        return EvidenceContract(
            shape="compare",
            compare_sides=sides,
            reason_codes=["CONTRACT_COMPARE"],
        )

    # Single-role who-is (CEO / Chief … Officer) before roster — even if Q says "Leadership"
    if _SINGLE_ROLE_WHO.search(q) or (
        _ATTRIBUTE.search(q) and not _DEFINE.search(q) and not is_org_roster_question(q)
    ):
        return EvidenceContract(shape="attribute", reason_codes=["CONTRACT_ATTRIBUTE"])

    if is_org_roster_question(q) and not _SINGLE_ROLE_WHO.search(q):
        return EvidenceContract(shape="list_people", reason_codes=["CONTRACT_LIST_PEOPLE"])

    # "Who is the CEO of X?" / bare "who is Joe"
    if re.search(r"^\s*who\s+is\b", q, re.I):
        return EvidenceContract(shape="attribute", reason_codes=["CONTRACT_ATTRIBUTE"])

    if _HOW_TO.search(q):
        return EvidenceContract(shape="how_to", reason_codes=["CONTRACT_HOW_TO"])

    if _DEFINE.search(q):
        return EvidenceContract(shape="define", reason_codes=["CONTRACT_DEFINE"])

    if _FACTOID.search(q):
        return EvidenceContract(shape="factoid", reason_codes=["CONTRACT_FACTOID"])

    return EvidenceContract(shape="open")


def _pack_blob(quotes: list) -> str:
    parts: list[str] = []
    for q in quotes or []:
        title = getattr(q, "document_title", None) or (q.get("document_title") if isinstance(q, dict) else "")
        quote = getattr(q, "quote", None) or (q.get("quote") if isinstance(q, dict) else "")
        parts.append(f"{title}\n{quote}")
    return "\n".join(parts)


def contract_fit_score(
    contract: EvidenceContract,
    title: str,
    text: str,
    *,
    question: str = "",
    signals: dict | None = None,
) -> float:
    """0..1 how well a passage satisfies the evidence contract."""
    blob = f"{title or ''}\n{text or ''}"
    sig = signals or {}
    chrome = float(sig.get("chrome_score") or 0.0)
    prose = float(sig.get("prose_score") or 0.0)
    if not prose and not chrome:
        # Fallback when chunk has no ingest signals
        pen = boilerplate_penalty(blob)
        chrome = min(1.0, pen / 1.5)
        prose = max(0.0, 1.0 - chrome)

    base = 0.35 * prose + 0.15 * (1.0 - chrome)
    shape = contract.shape

    if shape == "list_people":
        people = person_title_names(blob)
        if sig.get("has_person_role") and not people:
            people = ["_signal"]
        n = len(people)
        if n >= 2:
            return min(1.0, 0.55 + 0.15 * min(n, 4) + base)
        if n == 1:
            return min(1.0, 0.45 + base)
        return max(0.0, 0.08 * prose - 0.2 * chrome)

    if shape == "attribute":
        people = person_title_names(blob)
        terms = question_terms_from_text(question)
        ov = question_term_overlap(terms, blob)
        if people and ov >= 0.2:
            return min(1.0, 0.7 + base)
        if people or ov >= 0.45:
            return min(1.0, 0.5 + base)
        return max(0.0, ov * 0.5 + base * 0.3)

    if shape == "compare":
        sides = contract.compare_sides or extract_compare_sides(question)
        if len(sides) >= 2:
            low = blob.lower()
            hits = sum(1 for s in sides[:2] if s.lower() in low)
            return min(1.0, 0.25 * hits + 0.2 * prose + (0.35 if hits == 2 else 0.0))
        return base + 0.2 * question_term_overlap(question_terms_from_text(question), blob)

    if shape == "how_to":
        actions = len(_ACTIONABLE.findall(blob))
        return min(1.0, base + 0.12 * min(actions, 5) + 0.15 * question_term_overlap(
            question_terms_from_text(question), blob
        ))

    if shape == "define":
        has_def = bool(_DEFINITIONAL.search(blob))
        ov = question_term_overlap(question_terms_from_text(question), blob)
        return min(1.0, base + (0.35 if has_def else 0.0) + 0.3 * ov - 0.25 * chrome)

    if shape == "factoid":
        concrete = len(_CONCRETE.findall(blob))
        dated = bool(sig.get("has_dated_claim")) or bool(re.search(r"\b20\d{2}\b", blob))
        ql = (question or "").lower()
        # Prefer org-level metrics; demote personal tenure when asking org duration/size
        personal = bool(
            re.search(
                r"\b(my|his|her|their)\s+\d+\+?\s+years?\b|"
                r"\b\d+\+?\s+years?\s+of\s+(?:experience|career)\b",
                blob,
                re.I,
            )
        )
        org_metric = bool(
            re.search(
                r"\b(?:more\s+than|over|about|approximately)?\s*"
                r"\d{1,3}(?:,\d{3})+\+?\s+\w+|"
                r"\b\d+\+\s+years?\b|"
                r"\b\d+\s+offices?\b|"
                r"\b\d+\s+countries?\b",
                blob,
                re.I,
            )
        )
        org_q = bool(re.search(r"\b(how\s+many|how\s+long|offices?|countries?)\b", ql))
        bonus = 0.0
        if org_q and org_metric:
            bonus += 0.35
        if org_q and personal and not org_metric:
            bonus -= 0.25
        return min(
            1.0,
            base
            + 0.12 * min(concrete, 5)
            + (0.2 if dated else 0.0)
            + bonus
            + 0.25 * question_term_overlap(question_terms_from_text(question), blob),
        )

    # open
    ov = question_term_overlap(question_terms_from_text(question), blob)
    return min(1.0, base + 0.45 * ov)


def contract_satisfied(
    contract: EvidenceContract,
    quotes: list,
    *,
    question: str = "",
    min_fit: float = 0.42,
) -> tuple[bool, str]:
    """Whether the quote pack meets the contract. Returns (ok, reason_code)."""
    if contract.needs_clarify:
        return False, "TEAM_SCOPE_AMBIGUOUS"
    if not quotes:
        return False, "NO_QUOTE_EVIDENCE"

    blob = _pack_blob(quotes)
    shape = contract.shape

    if shape == "list_people":
        people = person_title_names(blob)
        if not people:
            return False, "CONTRACT_LIST_PEOPLE_UNMET"
        return True, "CONTRACT_OK"

    if shape == "attribute":
        people = person_title_names(blob)
        terms = question_terms_from_text(question)
        ov = question_term_overlap(terms, blob)
        # Attribute Qs need either a titled person or strong term overlap in prose
        if people or ov >= 0.35:
            if boilerplate_penalty(blob) >= 1.0 and not people:
                return False, "CONTRACT_ATTRIBUTE_UNMET"
            return True, "CONTRACT_OK"
        return False, "CONTRACT_ATTRIBUTE_UNMET"

    if shape == "compare":
        sides = contract.compare_sides or extract_compare_sides(question)
        if len(sides) >= 2:
            low = blob.lower()
            hits = sum(1 for s in sides[:2] if s.lower() in low)
            if hits < 2:
                return False, "CONTRACT_COMPARE_UNMET"
        return True, "CONTRACT_OK"

    if shape == "how_to":
        if not _ACTIONABLE.search(blob) and question_term_overlap(
            question_terms_from_text(question), blob
        ) < 0.35:
            return False, "CONTRACT_HOW_TO_UNMET"
        return True, "CONTRACT_OK"

    if shape == "define":
        if boilerplate_penalty(blob) >= 1.0:
            return False, "CONTRACT_DEFINE_UNMET"
        if question_term_overlap(question_terms_from_text(question), blob) < 0.2 and not _DEFINITIONAL.search(
            blob
        ):
            return False, "CONTRACT_DEFINE_UNMET"
        return True, "CONTRACT_OK"

    if shape == "factoid":
        if not _CONCRETE.search(blob) and not re.search(r"\b20\d{2}\b", blob):
            # Still OK if strong term overlap (office name etc.)
            if question_term_overlap(question_terms_from_text(question), blob) < 0.35:
                return False, "CONTRACT_FACTOID_UNMET"
        return True, "CONTRACT_OK"

    # open — require non-chrome pack with some overlap when terms exist
    terms = question_terms_from_text(question)
    if terms and question_term_overlap(terms, blob) < 0.15 and boilerplate_penalty(blob) >= 0.7:
        return False, "CONTRACT_OPEN_UNMET"
    # Soft check via average fit
    fits = [
        contract_fit_score(
            contract,
            getattr(q, "document_title", "") or "",
            getattr(q, "quote", "") or "",
            question=question,
        )
        for q in quotes[:4]
    ]
    if fits and max(fits) < min_fit * 0.6:
        return False, "CONTRACT_OPEN_UNMET"
    return True, "CONTRACT_OK"


def contract_coverage(contract: EvidenceContract, quotes: list, question: str = "") -> float:
    """0..1 contract satisfaction for TrustScore evidence_coverage."""
    ok, _ = contract_satisfied(contract, quotes, question=question)
    if not quotes:
        return 0.0
    fits = [
        contract_fit_score(
            contract,
            getattr(q, "document_title", "") or "",
            getattr(q, "quote", "") or "",
            question=question,
        )
        for q in quotes[:5]
    ]
    avg = sum(fits) / len(fits) if fits else 0.0
    return min(1.0, (0.55 if ok else 0.2) + 0.45 * avg)


_ANCHOR_LEAD_STOP = {
    "did",
    "does",
    "do",
    "is",
    "are",
    "was",
    "were",
    "what",
    "who",
    "how",
    "when",
    "where",
    "why",
    "which",
    "can",
    "could",
    "would",
    "should",
}


def question_anchor_phrases(question: str) -> list[str]:
    """Multi-word / distinctive anchors that a supporting quote should mention."""
    q = question or ""
    out: list[str] = []
    for m in re.finditer(r"[\"']([^\"']{3,80})[\"']", q):
        out.append(m.group(1).strip())
    # Title-case spans from the question (any domain)
    for m in re.finditer(r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){1,5})\b", q):
        parts = m.group(1).strip().split()
        while parts and parts[0].lower() in _ANCHOR_LEAD_STOP:
            parts.pop(0)
        if len(parts) >= 2:
            out.append(" ".join(parts))
        elif len(parts) == 1 and len(parts[0]) >= 4:
            out.append(parts[0])
    # Alphanumeric product codes / standards (ISO 27001, SL2000, …)
    for m in re.finditer(r"\b([A-Za-z]{1,8}\d{2,})\b", q):
        out.append(m.group(1))
    for m in re.finditer(r"\b([A-Z]{2,})\s*[- ]?\s*(\d{2,}(?:\.\d+)?)\b", q):
        out.append(f"{m.group(1)} {m.group(2)}")
        out.append(f"{m.group(1)}{m.group(2)}")
    # Deduplicate, longest first
    seen: set[str] = set()
    uniq: list[str] = []
    for p in sorted(out, key=len, reverse=True):
        k = p.lower()
        if k in seen or len(p) < 3:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def quote_support_score(
    contract: EvidenceContract,
    title: str,
    text: str,
    *,
    question: str,
) -> float:
    """How strongly a quote supports *this* question (0..1). Unrelated padding → ~0."""
    blob = f"{title or ''}\n{text or ''}"
    low = blob.lower()
    fit = contract_fit_score(contract, title, text, question=question)
    anchors = question_anchor_phrases(question)
    terms = question_terms_from_text(question)
    ov = question_term_overlap(terms, blob)
    ql = (question or "").lower()

    # Strong shape matches that must not be zeroed by missing Title-Case anchors
    if contract.shape == "define":
        if (
            "pathway" in ql or "transformation" in ql
        ) and has_transformation_triad(text or ""):
            return max(0.72, fit)
        # Service-shaped pages for what-is / offerings / capability-center asks
        if service_support_hit(title or "", text or "") and re.search(
            r"\b(capabilities|services|offerings?|solutions|capability|"
            r"what\s+is|what\s+are)\b",
            ql,
        ):
            return max(0.65, fit)

    if anchors:
        hit = any(a.lower() in low for a in anchors)
        if not hit:
            # Multi-word anchors: accept a distinctive tail ("Global Capability Centers")
            for a in anchors:
                parts = [p for p in a.split() if len(p) > 1]
                if len(parts) >= 2 and " ".join(parts[-2:]).lower() in low:
                    hit = True
                    break
                if len(parts) >= 3 and " ".join(parts[-3:]).lower() in low:
                    hit = True
                    break
        if not hit:
            # Service / product pages still count for define/open asks
            if service_support_hit(title or "", text or "") and contract.shape in {
                "define",
                "open",
                "factoid",
            }:
                return max(0.55, fit)
            # Soft words alone (development/center) must not keep padding docs
            if contract.shape in {"factoid", "define", "attribute", "open", "how_to"}:
                return 0.0
            # list_people / compare can survive on contract fit without every anchor
            return max(0.0, fit * 0.35)
        # Offerings asks: org-name alone is not support — need service-shaped evidence
        if contract.shape == "define" and re.search(
            r"\b(capabilities|services|offerings?|solutions)\b", ql
        ):
            if not service_support_hit(title or "", text or ""):
                return max(0.0, fit * 0.25)
        return min(1.0, 0.55 * fit + 0.45)

    # No anchors → require solid term overlap + contract fit
    if ov < 0.25 and fit < 0.45:
        return 0.0
    return min(1.0, 0.5 * fit + 0.5 * ov)


def prune_supporting_quotes(
    contract: EvidenceContract,
    quotes: list,
    question: str,
    *,
    min_support: float = 0.38,
    max_keep: int = 5,
) -> list:
    """Keep only quotes that actually support the question; drop citation padding."""
    if not quotes:
        return []
    ql = (question or "").lower()
    # Capability / offerings lists: keep service-page quotes even with softer overlap
    threshold = min_support
    if contract.shape == "define" and re.search(r"\b(capabilities|services|offer)\b", ql):
        threshold = min(min_support, 0.28)
    scored: list[tuple[float, object]] = []
    for q in quotes:
        title = getattr(q, "document_title", "") or ""
        text = getattr(q, "quote", "") or ""
        sc = quote_support_score(contract, title, text, question=question)
        scored.append((sc, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    kept = [q for sc, q in scored if sc >= threshold][:max_keep]
    if kept:
        return kept
    # Fallback: best single quote if weakly related; else empty (judge will refuse)
    if scored and scored[0][0] >= 0.18:
        return [scored[0][1]]
    return []


def refuse_message_for_contract(contract: EvidenceContract, reason: str) -> str:
    if reason == "CONTRACT_LIST_PEOPLE_UNMET":
        return (
            "Connected sources mention leadership in general terms but do not "
            "name the people on that team. Try asking about a specific role "
            "(for example, CEO), or connect a page that lists officers."
        )
    if reason == "CONTRACT_COMPARE_UNMET":
        return (
            "I couldn’t find sources that cover both sides of that comparison. "
            "Connect documents that mention each item, or ask about one side."
        )
    if reason == "CONTRACT_HOW_TO_UNMET":
        return (
            "I couldn’t find a process or steps for that in the connected knowledge base."
        )
    if reason in {
        "CONTRACT_ATTRIBUTE_UNMET",
        "CONTRACT_DEFINE_UNMET",
        "CONTRACT_FACTOID_UNMET",
        "CONTRACT_OPEN_UNMET",
    }:
        return (
            "I couldn’t find that in the connected knowledge base. "
            "Ask about topics covered by your uploaded or crawled sources."
        )
    return (
        "I couldn’t find knowledge-base passages for that question. "
        "Connect more sources, or ask with terms that appear in your documents."
    )
