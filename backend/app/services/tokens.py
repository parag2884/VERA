"""Realistic token counting via tiktoken (OpenAI / Azure embedding-compatible)."""

from __future__ import annotations

from functools import lru_cache

# cl100k_base matches text-embedding-ada-002 / text-embedding-3-* family tokenization.
_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Return exact tokenizer token count for embed/cost accounting."""
    if not text:
        return 0
    try:
        return len(_encoding().encode(text))
    except Exception:  # noqa: BLE001
        # Extremely defensive fallback — should not hit in normal Docker builds
        return max(1, len(text) // 4)


def count_tokens_many(texts: list[str]) -> int:
    return sum(count_tokens(t) for t in texts)


def tokenizer_name() -> str:
    return _ENCODING_NAME
