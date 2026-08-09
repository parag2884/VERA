from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    mode: str  # azure | mock

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
