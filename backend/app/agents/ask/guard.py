"""Policy guard: secrets + company-inappropriate content."""

from __future__ import annotations

import re

from app.agents.ask.contracts import GuardInput, GuardOutput
from app.agents.ask.moderation import moderate_question
from app.agents.base import AgentContext, AgentResult

SECRET_PATTERNS = [
    r"\bpassword\b",
    r"\bapi[_ -]?key\b",
    r"\bsecret\b",
    r"\bssn\b",
    r"\bsocial security\b",
    r"\bprivate key\b",
    r"\bbearer token\b",
]


class PolicySecretGuardAgent:
    id = "policy_secret_guard"
    display_name = "Policy & Secret Guard"
    input_model = GuardInput
    output_model = GuardOutput

    async def run(self, ctx: AgentContext, payload: GuardInput) -> AgentResult[GuardOutput]:
        q = payload.question.strip()
        blocked = False
        codes: list[str] = []

        mod = moderate_question(q)
        if mod.blocked:
            blocked = True
            codes.append(mod.reason_code)
        else:
            for pat in SECRET_PATTERNS:
                if re.search(pat, q, re.I):
                    blocked = True
                    codes.append("SECRET_OR_SENSITIVE_REQUEST")
                    break

        ctx.emit(
            self.id,
            "guard.done",
            "Blocked inappropriate or sensitive request" if blocked else "Guard passed",
            progress=1.0,
        )
        return AgentResult(
            ok=True,
            data=GuardOutput(question=q, blocked=blocked, reason_codes=codes),
            metrics={"blocked": int(blocked), "codes": ",".join(codes)},
        )
