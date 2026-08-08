from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.services.providers.azure_openai import AzureOpenAIProvider
from app.services.providers.mock import MockLLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider(settings: Settings | None = None) -> AzureOpenAIProvider | MockLLMProvider:
    settings = settings or get_settings()
    if settings.use_mock_llm:
        logger.info("Using mock LLM provider (demo mode)")
        return MockLLMProvider()
    try:
        return AzureOpenAIProvider(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Azure provider init failed, falling back to mock: %s", exc)
        return MockLLMProvider()
