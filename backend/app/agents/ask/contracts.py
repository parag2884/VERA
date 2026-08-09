from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.ask.evidence_contract import EvidenceContract
from app.schemas import ClarifyOption, TrustScore, TrustTrailHop


class GuardInput(BaseModel):
    question: str


class GuardOutput(BaseModel):
    question: str
    blocked: bool = False
    reason_codes: list[str] = Field(default_factory=list)


class RouteInput(BaseModel):
    question: str
    blocked: bool = False
    reason_codes: list[str] = Field(default_factory=list)


class RouteOutput(BaseModel):
    question: str
    intent: Literal["structural", "fuzzy", "secret", "blocked"] = "structural"
    reason_codes: list[str] = Field(default_factory=list)


class EntityResolveInput(BaseModel):
    question: str
    intent: str = "structural"
    reason_codes: list[str] = Field(default_factory=list)


class ResolvedEntity(BaseModel):
    query_term: str
    node_ids: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    ambiguous: bool = False


class EntityResolveOutput(BaseModel):
    question: str
    intent: str
    entities: list[ResolvedEntity] = Field(default_factory=list)
    resolved_clearly: bool = True
    reason_codes: list[str] = Field(default_factory=list)
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    clarification_prompt: str | None = None
    comparison: bool = False
    compare_sides: list[str] = Field(default_factory=list)


class GraphRetrieveInput(BaseModel):
    question: str
    intent: str
    entities: list[ResolvedEntity] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class RankedTrail(BaseModel):
    hops: list[TrustTrailHop] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    path_strength: float = 0.0
    conflict: bool = False


class GraphRetrieveOutput(BaseModel):
    question: str
    intent: str
    trails: list[RankedTrail] = Field(default_factory=list)
    best_trail: RankedTrail | None = None
    viable_evidence_bound_trail: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    entity_resolution_score: float = 0.0


class QuoteFillInput(BaseModel):
    question: str
    intent: str
    best_trail: RankedTrail | None = None
    viable_evidence_bound_trail: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    entity_resolution_score: float = 0.0
    evidence_contract: EvidenceContract | None = None


class QuoteHit(BaseModel):
    chunk_id: str
    document_title: str
    locator: str | None = None
    quote: str
    score: float
    edge_id: str | None = None


class QuoteFillOutput(BaseModel):
    question: str
    intent: str
    quotes: list[QuoteHit] = Field(default_factory=list)
    retrieval_mode: str = "graph_primary"
    best_trail: RankedTrail | None = None
    reason_codes: list[str] = Field(default_factory=list)
    entity_resolution_score: float = 0.0
    path_strength: float = 0.0
    evidence_contract: EvidenceContract | None = None


class EvidenceJudgeInput(BaseModel):
    question: str
    intent: str
    quotes: list[QuoteHit] = Field(default_factory=list)
    retrieval_mode: str = "graph_primary"
    best_trail: RankedTrail | None = None
    reason_codes: list[str] = Field(default_factory=list)
    entity_resolution_score: float = 0.0
    path_strength: float = 0.0
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    clarification_prompt: str | None = None
    decision_hint: Literal["answer", "clarify", "refuse"] | None = None
    evidence_contract: EvidenceContract | None = None


class EvidenceJudgeOutput(BaseModel):
    decision: Literal["answer", "clarify", "refuse"]
    answer: str | None = None
    clarification_prompt: str | None = None
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    trust_score: TrustScore = Field(default_factory=TrustScore)
    trust_trail: list[TrustTrailHop] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_mode: str = "graph_primary"
