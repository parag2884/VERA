from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "kcs-hackathon2-gpt-4.1-mini"
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_embedding_deployment: str = ""

    vera_db: str = "./data/vera.db"
    vera_data_dir: str = "./data"
    vera_vector_backend: Literal["chroma", "none"] = "chroma"
    vera_chroma_dir: str = "./data/chroma"
    vera_retrieval_mode: Literal["graph_primary"] = "graph_primary"
    vera_graph_hops: int = 3
    vera_quote_top_k: int = 8
    vera_weaver_llm_chunks: int = 16
    vera_refuse_threshold: float = 0.35
    vera_near_dupe_threshold: float = 0.85
    vera_max_upload_files: int = 100
    vera_max_file_mb: int = 100
    # Public-site crawl: capture publicly reachable pages (not login-gated).
    vera_url_max_pages: int = 500
    vera_url_max_depth: int = 4
    vera_url_hard_max_pages: int = 2000
    # JS render for SPA / thin httpx shells (Playwright Chromium).
    vera_crawl_js_enabled: bool = True
    vera_crawl_js_timeout_ms: int = 20000
    vera_crawl_js_concurrency: int = 2
    vera_crawl_min_prose_chars: int = 400
    vera_ms_tenant_id: str = ""
    vera_ms_client_id: str = ""
    vera_ms_client_secret: str = ""
    # Azure Blob knowledge connector (optional)
    vera_azure_blob_connection_string: str = ""
    vera_azure_storage_account: str = ""
    vera_azure_storage_key: str = ""
    vera_embed_price_per_1m_tokens: float = 0.02
    vera_cors_origins: str = "http://localhost:5173,http://localhost:8080"
    vera_widget_public_origin: str = "http://localhost:8080"
    vera_public_require_origin: bool = False
    vera_public_rate_limit_per_min: int = 60
    vera_mock_llm: bool = False
    # Intent gate: GPT only for ambiguous short messages; hard timeout keeps Ask fast.
    vera_intent_llm: bool = True
    vera_intent_llm_timeout_ms: int = 900
    vera_log_level: str = "INFO"

    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "text/markdown",
            "application/zip",
            "application/x-zip-compressed",
        ]
    )

    @field_validator(
        "vera_mock_llm",
        "vera_public_require_origin",
        "vera_crawl_js_enabled",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.vera_cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        path = Path(self.vera_data_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        path = Path(self.vera_db)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_dir(self) -> Path:
        path = Path(self.vera_chroma_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def azure_configured(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def use_mock_llm(self) -> bool:
        return self.vera_mock_llm or not self.azure_configured

    @property
    def max_file_bytes(self) -> int:
        return self.vera_max_file_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
