from __future__ import annotations

import re

from app.agents.ask.comparison import is_comparison_question
from app.agents.ask.contracts import RouteInput, RouteOutput
from app.agents.ask.overview import is_document_overview
from app.agents.ask.people import is_candidate_lookup
from app.agents.base import AgentContext, AgentResult


class RouteAgent:
    id = "route"
    display_name = "Route Agent"
    input_model = RouteInput
    output_model = RouteOutput

    async def run(self, ctx: AgentContext, payload: RouteInput) -> AgentResult[RouteOutput]:
        if payload.blocked:
            out = RouteOutput(
                question=payload.question,
                intent="blocked",
                reason_codes=list(payload.reason_codes),
            )
            return AgentResult(ok=True, data=out)

        # Default fuzzy (hybrid quotes). Structural when the question is graph-shaped.
        # Comparisons stay fuzzy so hybrid KB can answer even without asserted trails
        # (e.g. SL2000 vs SL3000 woven only as text, not as SecurityLevel nodes yet).
        q = payload.question.lower().strip()
        overview = is_document_overview(payload.question)
        candidate = is_candidate_lookup(payload.question)
        comparison = is_comparison_question(payload.question)
        intent = "fuzzy"
        structural = bool(
            re.search(
                r"\b("
                r"who owns|who (?:is )?responsible|"
                r"how (?:is|are|does|do) .+ related|"
                r"what(?:'s| is) the relationship between|"
                r"does .+ (?:require|depend|need)|"
                r"is .+ required|"
                r"must .+ (?:require|use|have)|"
                r"supersede|conflict(?:s|ing)? with|"
                r"depends on|governed by|part of|belongs to|"
                r"related to|applies to|defined as"
                r")\b",
                q,
            )
        )
        if structural and not overview and not candidate and not comparison:
            intent = "structural"

        if overview or candidate or comparison:
            intent = "fuzzy"

        ctx.emit(self.id, "route.done", f"Intent={intent}", progress=1.0)
        return AgentResult(
            ok=True,
            data=RouteOutput(question=payload.question, intent=intent, reason_codes=[]),
            metrics={
                "intent": intent,
                "overview": int(overview),
                "candidate": int(candidate),
                "comparison": int(comparison),
            },
        )
