from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# AcquiredFile is owned by knowledge/ — re-export for ingest agents & shims
from app.knowledge.contracts import AcquiredFile as AcquiredFile  # noqa: F401


class ConnectInput(BaseModel):
    files: list[AcquiredFile] = Field(default_factory=list)
    sample: bool = False


class ConnectOutput(BaseModel):
    files: list[AcquiredFile]
    acquired_count: int


class FingerprintInput(BaseModel):
    files: list[AcquiredFile]


class FingerprintedFile(BaseModel):
    source_id: str
    filename: str
    mime: str | None = None
    content: bytes = Field(repr=False)
    binary_hash: str
    byte_size: int
    appears_at: str | None = None
    storage_path: str | None = None


class FingerprintOutput(BaseModel):
    files: list[FingerprintedFile]


class ParsedFile(BaseModel):
    source_id: str
    filename: str
    mime: str | None = None
    text: str
    binary_hash: str
    text_hash: str
    byte_size: int
    appears_at: str | None = None
    structure: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ParseInput(BaseModel):
    files: list[FingerprintedFile]


class ParseOutput(BaseModel):
    files: list[ParsedFile]


class CleanStackDecision(BaseModel):
    source_id: str
    filename: str
    decision: Literal["keep", "skip_exact", "skip_near", "review"]
    reason: str
    canonical_key: str | None = None
    similarity: float | None = None
    appears_at: str | None = None


class CleanStackInput(BaseModel):
    files: list[ParsedFile]


class CleanStackOutput(BaseModel):
    keepers: list[ParsedFile]
    decisions: list[CleanStackDecision]
    report: dict[str, Any]


class ChunkRecord(BaseModel):
    id: str | None = None
    canonical_document_id: str
    document_title: str
    ordinal: int
    text: str
    loc: dict[str, Any] = Field(default_factory=dict)
    char_start: int = 0
    char_end: int = 0
    token_estimate: int = 0


class ChunkInput(BaseModel):
    keepers: list[ParsedFile]
    decisions: list[CleanStackDecision] = Field(default_factory=list)


class ChunkOutput(BaseModel):
    canonical_document_ids: list[str]
    chunks: list[ChunkRecord]
    source_links: list[dict[str, Any]] = Field(default_factory=list)


class WeaverInput(BaseModel):
    chunks: list[ChunkRecord]
    canonical_document_ids: list[str] = Field(default_factory=list)


class WeaverOutput(BaseModel):
    nodes_created: int
    edges_created: int
    evidence_bound_edges: int
    skipped_unsupported_relations: int
    domain_label: str | None = None
    domain_entity_types: list[str] = Field(default_factory=list)
    domain_relation_types: list[str] = Field(default_factory=list)


class EmbedInput(BaseModel):
    chunks: list[ChunkRecord]


class EmbedOutput(BaseModel):
    embedded_count: int
    tokens_embedded: int
    skipped: int = 0


class HealthInput(BaseModel):
    cleanstack_report: dict[str, Any] = Field(default_factory=dict)
    nodes_created: int = 0
    edges_created: int = 0
    evidence_bound_edges: int = 0
    embedded_count: int = 0


class HealthOutput(BaseModel):
    score: float
    components: dict[str, Any]
