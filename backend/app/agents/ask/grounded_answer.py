"""GPT-grounded answering over retrieved quotes (Foundry-style, evidence-bound)."""

from __future__ import annotations

import json
import logging
import re

from app.agents.ask.contracts import QuoteHit
from app.agents.ask.retrieve import coverage_ratio, required_terms
from app.agents.base import AgentContext

logger = logging.getLogger(__name__)

_FORMAT_GUIDE = """
Formatting (required — make answers easy to scan, like a good Copilot reply):
- Use GitHub-flavored Markdown in the answer string.
- Start with a short lead sentence (1–2 lines) that directly answers the question.
- Use ## or ### headings for distinct sections when the answer has more than one idea
  (e.g. "## What it is", "## Key points", "## Comparison", "## How it works").
- Mix short prose with bullets or numbered steps — do NOT dump one long paragraph.
- Prefer bullets for lists of features, constraints, differences, or requirements.
- Prefer numbered lists for processes / sequences.
- Bold **key terms** on first use (product names, levels, acronyms).
- Optional callout for a plain-language takeaway:
  > **In simple terms:** …
- Keep answers tight: usually 1 short intro + 1 heading + 3–6 bullets, or
  a comparison table-style bullet list. Expand only when the question needs depth.
- Do NOT wrap the whole answer in a code fence.
""".strip()


async def gpt_answer_from_quotes(
    ctx: AgentContext,
    question: str,
    quotes: list[QuoteHit],
    *,
    trail_summary: str | None = None,
    coverage: float | None = None,
) -> dict[str, str | bool | float]:
    """
    GPT writes the answer from quotes. Prefer answering with available evidence.
    Returns {sufficient: bool, answer: str, reason: str, coverage: float}.
    """
    terms = required_terms(question)
    cov = coverage if coverage is not None else coverage_ratio(quotes, terms)

    if not quotes:
        return {
            "sufficient": False,
            "answer": "",
            "reason": "No source quotes retrieved from the knowledge base.",
            "coverage": 0.0,
        }

    pack = "\n\n".join(
        f"[{i + 1}] Document: {q.document_title}\nLocator: {q.locator or 'n/a'}\n"
        f"Quote: {q.quote}"
        for i, q in enumerate(quotes[:10])
    )
    trail_line = f"\nTrust Trail: {trail_summary}\n" if trail_summary else "\n"
    cov_line = f"\nEvidence coverage of key terms ({', '.join(terms[:6])}): {cov:.0%}\n"

    if ctx.llm is None:
        return {
            "sufficient": True,
            "answer": _strip_doc_mentions(quotes[0].quote, quotes),
            "reason": "llm_unavailable_fallback",
            "coverage": cov,
        }

    try:
        raw = await ctx.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are VERA's evidence-bound answerer for an enterprise knowledge base. "
                        "Use ONLY the provided source quotes (and Trust Trail if present). "
                        "\n\n"
                        "Decision rules:\n"
                        "1) If quotes contain ANY useful facts that address the question "
                        "(definitions, comparisons, steps, constraints), set sufficient=true "
                        "and answer fully from those facts. Partial answers are OK — say what "
                        "the sources support and what they do not.\n"
                        "2) For comparisons (e.g. SL2000 vs SL3000), synthesize differences "
                        "from all quotes even if they come from different documents. "
                        "Use a short intro plus a bullet list of differences "
                        "(one side vs the other).\n"
                        "3) For how-to / renew / process questions, extract the process from "
                        "subscription/license/renewal passages when present — use numbered steps.\n"
                        "4) For definition / \"what is\" questions: short definition paragraph, "
                        "then ## Key points with bullets.\n"
                        "5) Set sufficient=false ONLY when quotes are clearly unrelated "
                        "(wrong topic) or empty of answerable content.\n"
                        "6) Never invent facts from general world knowledge.\n"
                        "7) Do NOT mention document names, filenames, PDF titles, or "
                        "parenthetical source lists in the answer. Sources are shown "
                        "separately as citations.\n"
                        f"\n{_FORMAT_GUIDE}\n"
                        "Return JSON {sufficient: boolean, answer: string, reason: string}. "
                        "The answer field MUST contain Markdown (with real newlines), "
                        "not a single escaped paragraph."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}{trail_line}{cov_line}\n"
                        f"Source quotes:\n{pack}\n\n"
                        "Write a well-structured Markdown answer now."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        parsed = json.loads(raw)
        sufficient = bool(parsed.get("sufficient"))
        answer = _strip_doc_mentions((parsed.get("answer") or "").strip(), quotes)
        answer = _normalize_answer_markdown(answer)
        reason = (parsed.get("reason") or "").strip()

        # High lexical coverage → do not refuse if GPT produced an answer
        if answer and cov >= 0.45:
            sufficient = True
        # Soft repair when model answered but flagged false
        if answer and not sufficient and (
            cov >= 0.3
            or re.search(
                r"\b(according to|based on|the (document|source|quote)|from )\b",
                answer,
                re.I,
            )
        ):
            sufficient = True
        if sufficient and not answer:
            sufficient = False
            reason = reason or "Model returned empty answer."
        # Low coverage + refuse text → keep refuse
        if not answer and cov < 0.25:
            sufficient = False

        ctx.demo_mode = ctx.demo_mode or getattr(ctx.llm, "mode", "") == "mock"
        return {
            "sufficient": sufficient,
            "answer": answer,
            "reason": reason,
            "coverage": cov,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("gpt_answer_from_quotes failed: %s", exc)
        # If coverage is decent, still surface quotes rather than hard refuse
        if cov >= 0.4:
            return {
                "sufficient": True,
                "answer": _strip_doc_mentions(quotes[0].quote, quotes),
                "reason": f"llm_error_fallback:{exc}",
                "coverage": cov,
            }
        return {
            "sufficient": False,
            "answer": "",
            "reason": f"llm_error:{exc}",
            "coverage": cov,
        }


def _normalize_answer_markdown(answer: str) -> str:
    """Unescape literal \\n from JSON models and tidy markdown spacing."""
    text = (answer or "").strip()
    if not text:
        return text
    # Models sometimes return literal backslash-n inside the JSON string value
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    text = text.replace("\\t", "  ")
    # Collapse 3+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_doc_mentions(answer: str, quotes: list[QuoteHit]) -> str:
    """Remove leaked filenames / document titles from answer prose."""
    text = (answer or "").strip()
    if not text:
        return text

    # Trailing parenthetical source dump: (...pdf, ...pdf).
    text = re.sub(
        r"\s*\((?:[^()]+\.(?:pdf|docx?|pptx?|xlsx?|txt|md)"
        r"(?:\s*,\s*[^()]+)*)\)\s*\.?$",
        "",
        text,
        flags=re.I,
    ).strip()

    # "According to Foo.pdf," / "From Bar.docx:" openers
    text = re.sub(
        r"^(?:according to|based on|from|see|source)\s+"
        r"[\"']?[^\"'\n,]+\.(?:pdf|docx?|pptx?|xlsx?|txt|md)[\"']?\s*[:\-–,]?\s*",
        "",
        text,
        flags=re.I,
    ).strip()

    titles = []
    for q in quotes:
        t = (q.document_title or "").strip()
        if t and t.lower() not in {"document", "untitled"}:
            titles.append(t)
            # Also strip common upload prefixes like "Prod Normalised PDFs__"
            base = re.sub(r"^.*__", "", t)
            if base and base != t:
                titles.append(base)

    for title in sorted(set(titles), key=len, reverse=True):
        if len(title) < 6:
            continue
        escaped = re.escape(title)
        text = re.sub(rf"\s*\({escaped}\)", "", text, flags=re.I)
        text = re.sub(rf"\b{escaped}\b\s*[,;:]?\s*", "", text, flags=re.I)

    # Collapse horizontal whitespace only — preserve markdown newlines
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    text = re.sub(r"[^\S\n]+([.,;:])", r"\1", text)
    return text.strip(" ,;:-")
