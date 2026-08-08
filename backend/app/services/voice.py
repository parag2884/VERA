"""Rewrite grounded answers into the selected agent voice without inventing facts."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

Tone = Literal["professional", "friendly", "concise", "formal", "executive"]
Verbosity = Literal["short", "balanced", "detailed"]

TONE_HINTS = {
    "professional": "Clear, neutral, business-ready phrasing.",
    "friendly": "Warm and approachable, still precise.",
    "concise": "Tight wording; cut filler; keep only essential facts.",
    "formal": "Policy / legal register; measured and precise.",
    "executive": "Decision-ready brief; lead with the takeaway.",
}

VERBOSITY_HINTS = {
    "short": "2-3 sentences max.",
    "balanced": "A short paragraph or a few bullets.",
    "detailed": "Fuller explanation; still only from the source answer.",
}


async def apply_agent_voice(
    llm: Any | None,
    answer: str,
    *,
    tone: str = "professional",
    verbosity: str = "balanced",
) -> str:
    text = (answer or "").strip()
    if not text:
        return text
    tone_key: Tone = tone if tone in TONE_HINTS else "professional"  # type: ignore[assignment]
    verb_key: Verbosity = verbosity if verbosity in VERBOSITY_HINTS else "balanced"  # type: ignore[assignment]

    if tone_key == "professional" and verb_key == "balanced":
        return text

    if llm is not None:
        try:
            raw = await llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite the answer for voice only. "
                            "Do NOT add facts, names, numbers, or claims missing from the source. "
                            "Keep citations/quotes if present. "
                            f"Tone: {TONE_HINTS[tone_key]} "
                            f"Length: {VERBOSITY_HINTS[verb_key]} "
                            'Return JSON {"answer": string}.'
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
            )
            parsed = json.loads(raw)
            rewritten = (parsed.get("answer") or "").strip()
            if rewritten:
                return rewritten
        except Exception:  # noqa: BLE001
            pass

    return _heuristic_voice(text, tone_key, verb_key)


def _heuristic_voice(text: str, tone: Tone, verbosity: Verbosity) -> str:
    out = text
    if tone == "friendly" and not out.lower().startswith(("here's", "here is", "sure")):
        out = f"Here’s what I can confirm from your sources: {out}"
    elif tone == "formal":
        out = out.replace("Don't", "Do not").replace("can't", "cannot")
        if not out.startswith("Based on"):
            out = f"Based on the connected evidence: {out}"
    elif tone == "executive":
        lines = out.split("\n")
        first = lines[0]
        rest = "\n".join(lines[1:]).strip()
        out = f"Takeaway: {first}" + (f"\n{rest}" if rest else "")
    elif tone == "concise":
        # Keep first sentence / bullet block
        parts = re.split(r"(?<=[.!?])\s+", out)
        out = " ".join(parts[:2]).strip() if parts else out

    if verbosity == "short":
        parts = re.split(r"(?<=[.!?])\s+", out)
        out = " ".join(parts[:2]).strip()
    elif verbosity == "detailed" and "Supporting quote" not in out and "“" not in out:
        out = f"{out}\n\n(Ask for the Trust Trail or citations if you need the underlying proof.)"
    return out
