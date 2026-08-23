from __future__ import annotations

from app.agents.ask.contracts import EvidenceJudgeInput, EvidenceJudgeOutput, QuoteHit
from app.agents.ask.evidence_contract import (
    contract_coverage,
    contract_satisfied,
    detect_evidence_contract,
    prune_supporting_quotes,
    refuse_message_for_contract,
)
from app.agents.ask.grounded_answer import (
    gpt_answer_from_quotes,
    is_unsupported_by_evidence_answer,
)
from app.agents.ask.overview import is_document_overview
from app.agents.ask.people import extract_query_names
from app.agents.ask.retrieve import coverage_ratio, required_terms
from app.agents.base import AgentContext, AgentResult
from app.config import get_settings
from app.schemas import TrustScore
from app.services.passage_signals import compute_passage_signals


class EvidenceSufficiencyJudgeAgent:
    """Final gate: GPT answers from quotes when evidence contracts are met."""

    id = "evidence_sufficiency_judge"
    display_name = "Evidence Sufficiency Judge"
    input_model = EvidenceJudgeInput
    output_model = EvidenceJudgeOutput

    async def run(
        self, ctx: AgentContext, payload: EvidenceJudgeInput
    ) -> AgentResult[EvidenceJudgeOutput]:
        settings = get_settings()
        reason_codes = list(payload.reason_codes)
        contract = payload.evidence_contract or detect_evidence_contract(payload.question)

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

        overview_mode = payload.retrieval_mode == "document_overview" or (
            is_document_overview(payload.question) and bool(payload.quotes)
        )
        name_mode = payload.retrieval_mode == "name_lookup"
        fuzzy_mode = payload.retrieval_mode == "broader_fuzzy"

        # Prune unrelated padding before any trust / GPT / citation work
        quotes = list(payload.quotes)
        if quotes and not overview_mode and not name_mode:
            quotes = prune_supporting_quotes(
                contract, quotes, payload.question, min_support=0.38, max_keep=5
            )

        trail = payload.best_trail
        best_quote_score = max((q.score for q in quotes), default=0.0)

        entity_score = payload.entity_resolution_score
        path_score = payload.path_strength
        conflict_penalty = 0.15 if (trail and trail.conflict) else 0.0

        # Real TrustScore components from passage signals + contract fit
        source_quality = _source_quality_from_quotes(quotes)
        evidence_coverage = contract_coverage(contract, quotes, payload.question)
        recency_penalty = _recency_penalty(quotes)

        if quotes:
            entity_score = max(entity_score, 0.55)
            path_score = max(path_score, 0.5)
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
                0.20 * entity_score
                + 0.20 * path_score
                + 0.35 * evidence_coverage
                + 0.25 * source_quality
                - conflict_penalty
                - recency_penalty,
            ),
        )
        trust = TrustScore(
            overall=round(overall, 3),
            entity_resolution=round(entity_score, 3),
            path_strength=round(path_score, 3),
            evidence_coverage=round(evidence_coverage, 3),
            source_quality=round(source_quality, 3),
            conflict_penalty=round(conflict_penalty, 3),
            recency_penalty=round(recency_penalty, 3),
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

        # Strict evidence-contract gate (before GPT)
        satisfied, contract_reason = contract_satisfied(
            contract, quotes, question=payload.question
        )
        if not satisfied and not overview_mode and not name_mode:
            reason_codes.append(contract_reason)
            reason_codes.append("UNSUPPORTED_BY_EVIDENCE")
            ctx.emit(
                self.id,
                "judge.refuse",
                f"Contract unmet: {contract.shape}/{contract_reason}",
                progress=1.0,
            )
            return AgentResult(
                ok=True,
                data=EvidenceJudgeOutput(
                    decision="refuse",
                    answer=refuse_message_for_contract(contract, contract_reason),
                    reason_codes=reason_codes,
                    trust_score=trust,
                    trust_trail=[],
                    claims=[],
                    citations=[],
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
        ctx.emit(
            self.id,
            "judge.gpt",
            f"GPT composing grounded answer (contract={contract.shape}, coverage={cov:.0%})…",
            progress=0.9,
        )
        gpt = await gpt_answer_from_quotes(
            ctx,
            payload.question,
            quotes,
            trail_summary=trail_summary,
            coverage=cov,
        )

        gpt_answer = str(gpt.get("answer") or "").strip()
        unsupported_prose = is_unsupported_by_evidence_answer(gpt_answer)

        if not gpt.get("sufficient") or unsupported_prose:
            # Never dump quotes when contract is strict or model says KB can't answer
            strict_shapes = {"list_people", "compare", "how_to", "attribute"}
            allow_coverage_override = (
                contract.shape not in strict_shapes
                and not unsupported_prose
                and cov >= 0.5
                and quotes
                and satisfied
                and not is_unsupported_by_evidence_answer((quotes[0].quote or "")[:400])
            )
            if allow_coverage_override:
                claim_fallback = (quotes[0].quote or "").strip()
                if len(quotes) > 1 and quotes[1].quote:
                    claim_fallback = f"{claim_fallback} {quotes[1].quote[:220]}".strip()
                if is_unsupported_by_evidence_answer(claim_fallback):
                    gpt = {
                        "sufficient": False,
                        "answer": gpt_answer,
                        "reason": "unsupported_after_coverage_check",
                        "coverage": cov,
                    }
                else:
                    gpt = {
                        "sufficient": True,
                        "answer": claim_fallback,
                        "reason": "coverage_override",
                        "coverage": cov,
                    }
                    gpt_answer = claim_fallback
                    unsupported_prose = False

            if not gpt.get("sufficient") or unsupported_prose:
                reason_codes.append("GPT_INSUFFICIENT_EVIDENCE")
                reason_codes.append("UNSUPPORTED_BY_EVIDENCE")
                refuse_msg = (
                    gpt_answer
                    or (gpt.get("reason") or "").strip()
                    or "The retrieved sources don’t contain enough evidence to answer that."
                )
                if unsupported_prose or len(refuse_msg) > 600:
                    refuse_msg = (
                        "I couldn’t find that in the connected knowledge base. "
                        "Ask about topics covered by your uploaded or crawled sources."
                    )
                ctx.emit(self.id, "judge.refuse", "GPT: insufficient evidence", progress=1.0)
                return AgentResult(
                    ok=True,
                    data=EvidenceJudgeOutput(
                        decision="refuse",
                        answer=refuse_msg,
                        reason_codes=reason_codes,
                        trust_score=trust,
                        trust_trail=[],
                        claims=[],
                        citations=[],
                        retrieval_mode=payload.retrieval_mode,
                    ),
                )

        claim_text = str(gpt.get("answer") or "").strip()
        if name_mode and len(claim_text) < 40:
            claim_text = _synthesize_name_answer(payload.question, quotes)

        if await _should_verify(ctx, trust.overall):
            verified = await _verify_answer(ctx, payload.question, claim_text, quotes)
            if not verified:
                reason_codes.append("VERIFIER_REJECT")
                reason_codes.append("UNSUPPORTED_BY_EVIDENCE")
                ctx.emit(self.id, "judge.refuse", "Verifier rejected groundedness", progress=1.0)
                return AgentResult(
                    ok=True,
                    data=EvidenceJudgeOutput(
                        decision="refuse",
                        answer=(
                            "The retrieved evidence does not clearly support a reliable answer. "
                            "Connect a more specific source, or rephrase using terms from your documents."
                        ),
                        reason_codes=reason_codes,
                        trust_score=trust,
                        trust_trail=trail.hops if trail else [],
                        retrieval_mode=payload.retrieval_mode,
                    ),
                )

        # Refresh coverage after successful answer
        trust.evidence_coverage = round(
            max(trust.evidence_coverage, contract_coverage(contract, quotes, payload.question)),
            3,
        )
        trust.overall = round(
            max(trust.overall, 0.7 if best_quote_score >= 0.7 and trust.evidence_coverage >= 0.45 else trust.overall),
            3,
        )
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
        if "CONTRACT_OK" not in reason_codes and satisfied:
            reason_codes.append("CONTRACT_OK")

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
            metrics={
                "overall": trust.overall,
                "gpt": 1,
                "contract": contract.shape,
                "source_quality": trust.source_quality,
            },
        )


async def _should_verify(ctx: AgentContext, overall: float) -> bool:
    if overall < 0.55:
        return True
    label = str((ctx.config or {}).get("domain_label") or "").lower()
    return any(
        k in label
        for k in ("health", "bank", "insur", "legal", "pharma", "financ", "bfsi", "clinic")
    )


async def _verify_answer(
    ctx: AgentContext, question: str, answer: str, quotes: list[QuoteHit]
) -> bool:
    """Independent check: does quoted evidence support the answer? Fail-open if no LLM."""
    if ctx.llm is None or not answer.strip() or not quotes:
        return True
    blob = "\n---\n".join((q.quote or "")[:500] for q in quotes[:4])
    try:
        raw = await ctx.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You verify groundedness. Return JSON {supported: boolean}. "
                        "supported=true only if the quotes contain the answer's key facts. "
                        "Do not use outside knowledge."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\nAnswer: {answer[:1200]}\nQuotes:\n{blob[:4000]}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        import json

        parsed = json.loads(raw or "{}")
        return bool(parsed.get("supported", True))
    except Exception:  # noqa: BLE001
        return True


def _source_quality_from_quotes(quotes: list[QuoteHit]) -> float:
    if not quotes:
        return 0.2
    from app.knowledge.sources.web.site_graph import trust_weight

    scores: list[float] = []
    for q in quotes[:5]:
        sig = compute_passage_signals(q.document_title or "", q.quote or "")
        prose = float(sig.get("prose_score") or 0.0)
        chrome = float(sig.get("chrome_score") or 0.0)
        reliability = trust_weight(q.document_title or "")
        scores.append(
            max(
                0.0,
                min(
                    1.0,
                    0.45 * prose + 0.25 * (1.0 - chrome) + 0.30 * reliability,
                ),
            )
        )
    return sum(scores) / len(scores)


def _recency_penalty(quotes: list[QuoteHit]) -> float:
    """Mild penalty when cited pack only has old years and newer years exist in titles."""
    import re

    years: list[int] = []
    for q in quotes[:5]:
        years.extend(int(y) for y in re.findall(r"\b(20\d{2})\b", f"{q.document_title} {q.quote}"))
    if not years:
        return 0.0
    newest = max(years)
    oldest = min(years)
    if newest - oldest >= 6 and newest < 2022:
        return 0.08
    return 0.0


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
