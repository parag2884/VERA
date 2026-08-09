"""Detect social greetings and return a warm reply (no KB retrieval)."""

from __future__ import annotations

import re

# Only polite openers — no free-form trailing words (avoids "how are you sexy")
_GREETING_RE = re.compile(
    r"^\s*("
    r"hi|hello|hey|howdy|hola|namaste|yo|"
    r"good\s*(morning|afternoon|evening|day)|"
    r"greetings|"
    r"(hi|hello|hey)\s+(there|friend|folks|everyone|all|team)|"
    r"what'?s\s+up|"
    r"how\s+are\s+you(?:\s+doing)?|"
    r"how\s+do\s+you\s+do|"
    r"nice\s+to\s+(?:meet|see)\s+you"
    r")"
    r"[\s!?.…,]*$"
    ,
    re.I,
)


def is_greeting(question: str) -> bool:
    q = (question or "").strip()
    if not q or len(q) > 60:
        return False
    # Must not look like a real KB question
    if "?" in q and not re.search(r"^(how\s+are\s+you|what'?s\s+up)", q, re.I):
        return False
    if re.search(
        r"\b(what|why|when|where|which|who|explain|define|tell me about|how (?:do|does|can|is|are))\b",
        q,
        re.I,
    ) and not re.search(r"^how\s+are\s+you|^how\s+do\s+you\s+do", q, re.I):
        return False
    return bool(_GREETING_RE.match(q))


def warm_greeting_message(agent_name: str | None = None) -> str:
    name = (agent_name or "").strip() or "your VERA assistant"
    return (
        f"Hi there! I'm {name}. "
        "Nice to meet you - what can I help you with today?"
    )
