"""Respectful content moderation for company-inappropriate user input."""

from __future__ import annotations

import re
from dataclasses import dataclass

RESPECTFUL_FALLBACK = (
    "Thanks for your message. I'm happy to help with professional questions "
    "about this assistant's knowledge. "
    "I can't continue conversations that involve sexual, abusive, or inappropriate language. "
    "Please ask a respectful work-related question, and I'll gladly help."
)

SECRET_FALLBACK = (
    "I can't help with secrets, passwords, or personal data requests. "
    "I only answer from the connected knowledge base — please ask a professional question instead."
)


@dataclass(frozen=True)
class ModerationHit:
    blocked: bool
    reason_code: str
    message: str


# High-signal adult / sexual terms (whole word)
_SEXUAL_KEYWORDS = {
    "sex",
    "sexy",
    "sexier",
    "sexiest",
    "sexual",
    "sexually",
    "porn",
    "porno",
    "pornography",
    "xxx",
    "onlyfans",
    "hentai",
    "nude",
    "nudes",
    "naked",
    "boobs",
    "tits",
    "pussy",
    "vagina",
    "penis",
    "cock",
    "dick",
    "blowjob",
    "handjob",
    "cybersex",
    "orgasm",
    "erotic",
    "fetish",
    "horny",
    "nsfw",
    "babe",
    "babes",
    "bae",
    "slut",
    "whore",
    "hookup",
    "booty",
}

_SEXUAL_PATTERNS = [
    r"\b(have|want|do|need|lets?|let'?s)\s+(a\s+|some\s+|to\s+)?sex\b",
    r"\bsex\s+(with|chat|talk|please|now|tonight)\b",
    r"\b(fuck\s+me|send\s+(nudes|pics)|dick\s*pic)\b",
    r"\b(hot\s*stuff|make\s+love|sleep\s+with\s+me|kiss\s+me)\b",
    r"\b(date\s+me|marry\s+me|love\s+you\s+baby)\b",
    r"\b(how\s+are\s+you|hi|hello|hey)\b.+\b(sexy|hot|babe|baby|darling|sweetheart)\b",
    r"\b(sexy|hot|babe|baby|darling|sweetheart)\b.+\b(how\s+are\s+you|hi|hello|hey)\b",
    r"\b(are\s+you\s+single|wanna\s+hook\s*up|hook\s*up\s+tonight|netflix\s+and\s+chill)\b",
    r"\bmasturbat\w*\b",
]

_ABUSE_KEYWORDS = {
    "asshole",
    "bastard",
    "bitch",
    "bitches",
    "cunt",
    "motherfucker",
    "dipshit",
    "shithead",
    "dumbass",
    "jackass",
    "bullshit",
}

_ABUSE_PATTERNS = [
    r"\b(fuck\s+you|screw\s+you|damn\s+you)\b",
    r"\b(kill\s+yourself|kys)\b",
    r"\b(go\s+to\s+hell|piece\s+of\s+shit)\b",
    r"\bf+u+c+k+(?:ing|er|ed|off)?\b",
    r"\bs+h+i+t+(?:ty)?\b",
    r"\b(idiot|moron|retard(?:ed)?)\b",
]

_HATE_PATTERNS = [
    r"\b(nigg(?:er|a)|faggot|\bfag\b|tranny|kike|spic|chink|wetback)\b",
]

_THREAT_PATTERNS = [
    r"\b(i\s+will\s+(kill|hurt|rape)|rape\s+you|bomb\s+you)\b",
    r"\b(terrorist\s+attack|make\s+a\s+bomb)\b",
]


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[*._\-]+", " ", t)
    t = t.replace("0", "o").replace("1", "i").replace("3", "e").replace("@", "a")
    t = re.sub(r"\s+", " ", t)
    return t


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text))


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def moderate_question(question: str) -> ModerationHit:
    """Return a block decision for company-inappropriate content."""
    q = (question or "").strip()
    if not q:
        return ModerationHit(False, "", "")

    normalized = _normalize(q)
    tokens = _tokens(normalized)
    haystack = f"{q}\n{normalized}"

    if _match_any(haystack, _THREAT_PATTERNS):
        return ModerationHit(True, "INAPPROPRIATE_THREAT", RESPECTFUL_FALLBACK)
    if _match_any(haystack, _HATE_PATTERNS):
        return ModerationHit(True, "INAPPROPRIATE_HATE", RESPECTFUL_FALLBACK)

    if tokens & _SEXUAL_KEYWORDS or _match_any(haystack, _SEXUAL_PATTERNS):
        return ModerationHit(True, "INAPPROPRIATE_SEXUAL", RESPECTFUL_FALLBACK)

    if tokens & _ABUSE_KEYWORDS or _match_any(haystack, _ABUSE_PATTERNS):
        return ModerationHit(True, "INAPPROPRIATE_ABUSE", RESPECTFUL_FALLBACK)

    return ModerationHit(False, "", "")


def fallback_for_codes(reason_codes: list[str] | None) -> str | None:
    codes = reason_codes or []
    if any(c.startswith("INAPPROPRIATE_") for c in codes):
        return RESPECTFUL_FALLBACK
    if "SECRET_OR_SENSITIVE_REQUEST" in codes:
        return SECRET_FALLBACK
    return None
