"""Fast intent gate for Ask (target: negligible latency on normal questions).

Latency design (keep answers under ~5s end-to-end)
-------------------------------------------------
1) Lexical hard-block — microseconds (always on)
2) Clear greeting heuristic — microseconds (no GPT)
3) Clear knowledge heuristic — microseconds (no GPT)  ← most Ask traffic
4) GPT meaning classify — ONLY for ambiguous short messages, with hard timeout
5) On GPT timeout/error — fail-open to knowledge (or greeting if heuristic)

GPT is a safety assist for edge cases, not on the hot path for real KB questions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.agents.ask.greeting import is_greeting, warm_greeting_message
from app.agents.ask.moderation import (
    RESPECTFUL_FALLBACK,
    SECRET_FALLBACK,
    moderate_question,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

Intent = Literal["greeting", "inappropriate", "sensitive", "knowledge"]

# Keep prompt tiny — fewer tokens = faster classify
_SYSTEM = (
    "Classify USER MESSAGE meaning for a company knowledge assistant. "
    "Return JSON only: "
    '{"intent":"greeting|inappropriate|sensitive|knowledge","confidence":0-1,"category":"x","reason":"x"}. '
    "greeting=pure hello/how are you. "
    "inappropriate=sexual/flirty/abusive/hate/threat (even mixed with hi). "
    "sensitive=passwords/secrets/keys/ssn. "
    "knowledge=real informational question. "
    "Prefer inappropriate over greeting when flirty/sexual."
)

_KNOWLEDGE_HINT = re.compile(
    r"\b("
    r"what|why|when|where|which|who|whom|whose|"
    r"how\s+(?:do|does|did|can|could|would|should|is|are|was|were|to|much|many)|"
    r"explain|define|describe|compare|difference|summarize|overview|"
    r"tell\s+me|list|show|help\s+me\s+(?:with|understand)|"
    r"does|is\s+there|are\s+there|can\s+(?:i|we|you)|"
    r"policy|license|agreement|requirement|compliance|specification|standard"
    r")\b",
    re.I,
)


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    category: str
    confidence: float
    reason: str
    source: str  # lexical | llm | heuristic | skip_llm
    reply: str | None = None
    reason_code: str = ""
    retrieval_mode: str = ""


def _parse_intent(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def looks_like_knowledge(question: str) -> bool:
    """True when message clearly belongs on the KB path (skip GPT)."""
    q = (question or "").strip()
    if not q:
        return False
    if is_greeting(q):
        return False
    # Longer substantive messages are almost always knowledge
    if len(q) >= 100:
        return True
    words = re.findall(r"[A-Za-z0-9']+", q)
    if len(words) >= 8 and _KNOWLEDGE_HINT.search(q):
        return True
    if _KNOWLEDGE_HINT.search(q) and len(words) >= 3:
        return True
    return False


def needs_llm_disambiguation(question: str) -> bool:
    """Only spend GPT on short/ambiguous social-ish messages."""
    q = (question or "").strip()
    if not q or looks_like_knowledge(q) or is_greeting(q):
        return False
    # Short non-knowledge messages may hide flirty/abusive meaning
    if len(q) <= 120 and len(re.findall(r"[A-Za-z0-9']+", q)) <= 16:
        return True
    return False


async def classify_user_intent(
    llm: Any,
    question: str,
    *,
    agent_name: str | None = None,
) -> IntentDecision:
    """Defense-in-depth intent decision optimized for low latency."""
    q = (question or "").strip()
    settings = get_settings()

    # 1) Lexical hard block — always, instant
    hard = moderate_question(q)
    if hard.blocked:
        return IntentDecision(
            intent="inappropriate" if hard.reason_code.startswith("INAPPROPRIATE_") else "sensitive",
            category=hard.reason_code.lower(),
            confidence=1.0,
            reason="lexical_hard_block",
            source="lexical",
            reply=hard.message,
            reason_code=hard.reason_code,
            retrieval_mode="policy_refuse",
        )

    # 2) Clear greeting — instant, no GPT
    if is_greeting(q):
        return IntentDecision(
            intent="greeting",
            category="greeting",
            confidence=0.95,
            reason="heuristic_greeting",
            source="heuristic",
            reply=warm_greeting_message(agent_name),
            reason_code="greeting",
            retrieval_mode="greeting",
        )

    # 3) Clear knowledge — instant, no GPT (hot path)
    if looks_like_knowledge(q):
        return IntentDecision(
            intent="knowledge",
            category="knowledge",
            confidence=0.9,
            reason="heuristic_knowledge_skip_llm",
            source="skip_llm",
        )

    # 4) Ambiguous only — GPT with hard timeout
    llm_decision: IntentDecision | None = None
    use_llm = bool(settings.vera_intent_llm) and needs_llm_disambiguation(q) and llm is not None
    if use_llm:
        timeout_s = max(0.2, (settings.vera_intent_llm_timeout_ms or 900) / 1000.0)
        try:
            llm_decision = await asyncio.wait_for(
                _llm_classify(llm, q),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.info("Intent LLM timed out after %.0fms — continuing", timeout_s * 1000)
            llm_decision = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intent LLM failed: %s", exc)
            llm_decision = None

    if llm_decision and llm_decision.confidence >= 0.55:
        return _finalize(llm_decision, agent_name)

    if llm_decision:
        return _finalize(llm_decision, agent_name)

    # 5) Default: knowledge (fail-open for speed)
    return IntentDecision(
        intent="knowledge",
        category="knowledge",
        confidence=0.5,
        reason="default_knowledge_fast",
        source="heuristic",
    )


async def _llm_classify(llm: Any, question: str) -> IntentDecision | None:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": question[:500]},
    ]
    try:
        raw = await llm.chat(
            messages,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=80,
        )
    except TypeError:
        # Older provider stubs without max_tokens
        try:
            raw = await llm.chat(
                messages,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except Exception:
            raw = await llm.chat(messages, temperature=0.0)
    except Exception:
        raw = await llm.chat(messages, temperature=0.0, max_tokens=80)

    data = _parse_intent(raw)
    if not data:
        return None
    intent = str(data.get("intent") or "knowledge").lower().strip()
    if intent not in {"greeting", "inappropriate", "sensitive", "knowledge"}:
        intent = "knowledge"
    conf = max(0.0, min(1.0, float(data.get("confidence") or 0.5)))
    return IntentDecision(
        intent=intent,  # type: ignore[arg-type]
        category=str(data.get("category") or intent)[:64],
        confidence=conf,
        reason=str(data.get("reason") or "llm_classify")[:200],
        source="llm",
    )


def _finalize(decision: IntentDecision, agent_name: str | None) -> IntentDecision:
    if decision.intent == "greeting":
        return IntentDecision(
            intent="greeting",
            category=decision.category or "greeting",
            confidence=decision.confidence,
            reason=decision.reason,
            source=decision.source,
            reply=warm_greeting_message(agent_name),
            reason_code="greeting",
            retrieval_mode="greeting",
        )
    if decision.intent == "inappropriate":
        return IntentDecision(
            intent="inappropriate",
            category=decision.category or "inappropriate",
            confidence=decision.confidence,
            reason=decision.reason,
            source=decision.source,
            reply=RESPECTFUL_FALLBACK,
            reason_code="INAPPROPRIATE_SEMANTIC",
            retrieval_mode="policy_refuse",
        )
    if decision.intent == "sensitive":
        return IntentDecision(
            intent="sensitive",
            category=decision.category or "sensitive",
            confidence=decision.confidence,
            reason=decision.reason,
            source=decision.source,
            reply=SECRET_FALLBACK,
            reason_code="SECRET_OR_SENSITIVE_REQUEST",
            retrieval_mode="policy_refuse",
        )
    return IntentDecision(
        intent="knowledge",
        category=decision.category or "knowledge",
        confidence=decision.confidence,
        reason=decision.reason,
        source=decision.source,
    )
