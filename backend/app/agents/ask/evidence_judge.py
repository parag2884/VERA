from __future__ import annotations

from app.agents.ask.contracts import EvidenceJudgeInput, EvidenceJudgeOutput, QuoteHit
from app.agents.ask.grounded_answer import gpt_answer_from_quotes
from app.agents.ask.overview import is_document_overview
from app.agents.ask.people import extract_query_names
from app.agents.ask.retrieve import coverage_ratio, required_terms
from app.agents.base import AgentContext, AgentResult
from app.config import get_settings
from app.schemas import TrustScore


class EvidenceSufficiencyJudgeAgent:
    """Final gate: GPT answers from quotes when evidence is sufficient."""

    id = "evidence_sufficiency_judge"
    display_name = "Evidence Sufficiency Judge"
    input_model = EvidenceJudgeInput
    output_model = EvidenceJudgeOutput

    async def run(
        self, ctx: AgentContext, payload: EvidenceJudgeInput
    ) -> AgentResult[EvidenceJudgeOutput]:
        settings = get_settings()
        reason_codes = list(payload.reason_codes)

        if payload.decision_hint == "clarify" or payload.clarify_options:
            score = TrustScore(
                overall=0.35,
                entity_resolution=payload.entity_resolution_score,
                path_strength=payload.path_strength,
                evidence_coverage=0.0,
                source_quality=0.5,
                conflict_penalty=0.0,
                recency_penalty=0.0,
            )
            ctx.emit(self.id, "judge.clarify", "Ambiguous — asking for clarification", progress=1.0)
            return AgentResult(
                ok=True,
                data=EvidenceJudgeOutput(
                    decision="clarify",
                    clarification_prompt=payload.clarification_prompt
                    or "Your question is ambiguous against the knowledge graph. Please clarify.",
                    clarify_options=payload.clarify_options,
                    reason_codes=reason_codes or ["ENTITY_AMBIGUOUS"],
                    trust_score=score,
                    retrieval_mode="clarify",
                ),
            )

        if payload.intent in {"blocked", "secret"} or "SECRET_OR_SENSITIVE_REQUEST" in reason_codes:
            ctx.emit(self.id, "judge.refuse", "Refusing sensitive/unsupported request", progress=1.0)
            return AgentResult(
                ok=True,
                data=EvidenceJudgeOutput(
                    decision="refuse",
                    answer="I can’t help with secrets or personal data requests. "
                    "I only answer from the connected knowledge base.",
                    reason_codes=reason_codes or ["SECRET_OR_SENSITIVE_REQUEST"],
                    trust_score=TrustScore(overall=0.0),
                    retrieval_mode="refuse",
                ),
            )

        quotes = list(payload.quotes)
        trail = payload.best_trail
        best_quote_score = max((q.score for q in quotes), default=0.0)
        overview_mode = payload.retrieval_mode == "document_overview" or (
            is_document_overview(payload.question) and bool(quotes)
        )
        name_mode = payload.retrieval_mode == "name_lookup"
        fuzzy_mode = payload.retrieval_mode == "broader_fuzzy"

        entity_score = payload.entity_resolution_score
        path_score = payload.path_strength
        evidence_coverage = min(1.0, len(quotes) / 2.0) if quotes else 0.0
        source_quality = 0.85 if quotes else 0.2
        conflict_penalty = 0.15 if (trail and trail.conflict) else 0.0

        if quotes:
            entity_score = max(entity_score, 0.55)
            path_score = max(path_score, 0.5)
            evidence_coverage = max(evidence_coverage, min(1.0, 0.35 * len(quotes)))
        if fuzzy_mode or overview_mode or name_mode:
            reason_codes = [
                c
                for c in reason_codes
                if c
                not in {
                    "ENTITY_NOT_RESOLVED",
                    "NO_SEED_ENTITIES",
                    "NO_EVIDENCE_BOUND_PATH",
                }
            ]

        overall = max(
            0.0,
            min(
                1.0,
                0.25 * entity_score
                + 0.30 * path_score
                + 0.30 * evidence_coverage
                + 0.15 * source_quality
                - conflict_penalty,
            ),
        )
        trust = TrustScore(
            overall=round(overall, 3),
            entity_resolution=round(entity_score, 3),
            path_strength=round(path_score, 3),
            evidence_coverage=round(evidence_coverage, 3),
            source_quality=round(source_quality, 3),
            conflict_penalty=round(conflict_penalty, 3),
            recency_penalty=0.0,
        )

        if not quotes:
            if "NAME_NOT_FOUND_IN_SOURCES" in reason_codes:
                names = extract_query_names(payload.question)
                who = ", ".join(names) if names else "that name"
                refuse_msg = (
                    f"I checked connected sources and found no candidate or resume "
                    f"mentioning {who}."
                )
            else:
                reason_codes.append("NO_QUOTE_EVIDENCE")
                reason_codes.append("UNSUPPORTED_BY_EVIDENCE")
                refuse_msg = (
                    "I couldn’t find knowledge-base passages for that question. "
                    "Connect more sources, or ask with terms that appear in your documents."
                )
            ctx.emit(self.id, "judge.refuse", "No quotes — refuse", progress=1.0)
            return AgentResult(
                ok=True,
                data=EvidenceJudgeOutput(
                    decision="refuse",
                    answer=refuse_msg,
                    reason_codes=reason_codes,
                    trust_score=trust,
                    trust_trail=trail.hops if trail else [],
                    retrieval_mode=payload.retrieval_mode,
                ),
            )

        trail_summary = None
        if trail and trail.hops:
            trail_summary = " → ".join(
                f"{h.from_name} {h.rel.replace('_', ' ').lower()} {h.to_name}"
                for h in trail.hops
            )

        cov = coverage_ratio(quotes, required_terms(payload.question))
        # GPT writes the answer from retrieved evidence (core of KB Q&A)
        ctx.emit(
            self.id,
            "judge.gpt",
            f"GPT composing grounded answer (coverage={cov:.0%})…",
            progress=0.9,
        )
        gpt = await gpt_answer_from_quotes(
            ctx,
            payload.question,
            quotes,
            trail_summary=trail_summary,
            coverage=cov,
        )

        if not gpt.get("sufficient"):
            # Last resort: if pack clearly covers the question, answer from quotes
            if cov >= 0.5 and quotes:
                claim_fallback = (quotes[0].quote or "").strip()
                if len(quotes) > 1 and quotes[1].quote:
                    claim_fallback = f"{claim_fallback} {quotes[1].quote[:220]}".strip()
                gpt = {
                    "sufficient": True,
                    "answer": claim_fallback,
                    "reason": "coverage_override",
                    "coverage": cov,
                }
            else:
                reason_codes.append("GPT_INSUFFICIENT_EVIDENCE")
                reason_codes.append("UNSUPPORTED_BY_EVIDENCE")
                refuse_msg = (
                    (gpt.get("answer") or gpt.get("reason") or "").strip()
                    or "The retrieved sources don’t contain enough evidence to answer that."
                )
                ctx.emit(self.id, "judge.refuse", "GPT: insufficient evidence", progress=1.0)
                return AgentResult(
                    ok=True,
                    data=EvidenceJudgeOutput(
                        decision="refuse",
                        answer=refuse_msg,
                        reason_codes=reason_codes,
                        trust_score=trust,
                        trust_trail=trail.hops if trail else [],
                        retrieval_mode=payload.retrieval_mode,
                    ),
                )

        claim_text = str(gpt.get("answer") or "").strip()
        # Name-lookup polish when GPT is terse
        if name_mode and len(claim_text) < 40:
            claim_text = _synthesize_name_answer(payload.question, quotes)

        trust.overall = round(max(trust.overall, 0.7 if best_quote_score >= 0.7 else trust.overall), 3)
        claim = {
            "claim_id": "claim-1",
            "claim_text": (claim_text.split(". ")[0] + ".") if claim_text else claim_text,
            "support_status": "supported",
            "trust_score": trust.overall,
        }
        citations = []
        for q in quotes[:5]:
            citations.append(
                {
                    "claim_id": "claim-1",
                    "document": q.document_title,
                    "locator": q.locator,
                    "quote": q.quote,
                    "chunk_id": q.chunk_id,
                    "edge_id": q.edge_id,
                }
            )

        if conflict_penalty > 0:
            reason_codes.append("CONFLICT_OR_SUPERSEDE_PRESENT")
        reason_codes.append("GPT_GROUNDED_ANSWER")

        mode = "document_overview" if overview_mode else payload.retrieval_mode
        ctx.emit(self.id, "judge.answer", "GPT grounded answer", progress=1.0)
        return AgentResult(
            ok=True,
            data=EvidenceJudgeOutput(
                decision="answer",
                answer=claim_text,
                reason_codes=reason_codes,
                trust_score=trust,
                trust_trail=trail.hops if trail else [],
                claims=[claim],
                citations=citations,
                retrieval_mode=mode,
            ),
            metrics={"overall": trust.overall, "gpt": 1},
        )


def _synthesize_name_answer(question: str, quotes: list[QuoteHit]) -> str:
    names = extract_query_names(question)
    parts: list[str] = []
    for q in quotes[:3]:
        hit_name = next(
            (n for n in names if n.lower() in (q.quote + " " + q.document_title).lower()),
            None,
        )
        label = hit_name or (names[0] if names else "that candidate")
        parts.append(f"Yes — {label} appears in the connected knowledge. “{q.quote}”")
    return " ".join(parts) if parts else "Insufficient evidence."
