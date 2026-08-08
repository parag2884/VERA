from __future__ import annotations

import logging
from typing import Any

from openai import AsyncAzureOpenAI

from app.config import Settings
from app.stores.vector import local_embed

logger = logging.getLogger(__name__)


class AzureOpenAIProvider:
    mode = "azure"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint.rstrip("/"),
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.settings.azure_openai_deployment,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        deployment = self.settings.azure_openai_embedding_deployment
        if not deployment:
            return local_embed(texts)
        try:
            response = await self.client.embeddings.create(model=deployment, input=texts)
            return [item.embedding for item in response.data]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding deployment failed, using local embed: %s", exc)
            return local_embed(texts)
