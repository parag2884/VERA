from __future__ import annotations

from typing import Any

from app.agents.ask.entity_resolve import EntityResolveAgent
from app.agents.ask.evidence_judge import EvidenceSufficiencyJudgeAgent
from app.agents.ask.graph_retrieve import GraphRetrieveAgent
from app.agents.ask.guard import PolicySecretGuardAgent
from app.agents.ask.quote_fill import QuoteFillAgent
from app.agents.ask.route import RouteAgent
from app.agents.ask.contracts import (
    EntityResolveInput,
    EvidenceJudgeInput,
    GraphRetrieveInput,
    GuardInput,
    QuoteFillInput,
    RouteInput,
)
from app.agents.ingest.chunk import ChunkAgent
from app.agents.ingest.cleanstack import CleanStackAgent
from app.agents.ingest.connect import ConnectAgent
from app.agents.ingest.contracts import (
    ChunkInput,
    CleanStackInput,
    ConnectInput,
    EmbedInput,
    FingerprintInput,
    HealthInput,
    ParseInput,
    WeaverInput,
)
from app.agents.ingest.embed import EmbedAgent
from app.agents.ingest.fingerprint import FingerprintAgent
from app.agents.ingest.health import IndexHealthAgent
from app.agents.ingest.parse import ParseAgent
from app.agents.ingest.weaver import GraphWeaverAgent
from app.agents.orchestrator import PipelineDefinition, PipelineOrchestrator, PipelineStage
from app.agents.registry import AgentRegistry
from app.config import get_settings
from app.services.providers.factory import get_llm_provider
from app.stores.vector import VectorStore


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in [
        ConnectAgent(),
        FingerprintAgent(),
        ParseAgent(),
        CleanStackAgent(),
        ChunkAgent(),
        GraphWeaverAgent(),
        EmbedAgent(),
        IndexHealthAgent(),
        PolicySecretGuardAgent(),
        RouteAgent(),
        EntityResolveAgent(),
        GraphRetrieveAgent(),
        QuoteFillAgent(),
        EvidenceSufficiencyJudgeAgent(),
    ]:
        registry.register(agent)
    return registry


def build_orchestrator(registry: AgentRegistry) -> PipelineOrchestrator:
    orch = PipelineOrchestrator(registry)

    orch.register_pipeline(
        PipelineDefinition(
            id="ingest_pipeline",
            display_name="Ingest Pipeline (Connect -> CleanStack -> Weave -> Embed)",
            stages=[
                PipelineStage(
                    id="connect",
                    agent_id="connect",
                    description="Acquire source descriptors and bytes",
                    input_builder=lambda ctx, bag: ConnectInput.model_validate(bag),
                ),
                PipelineStage(
                    id="fingerprint",
                    agent_id="fingerprint",
                    description="Exact binary hash and source identity",
                    input_builder=lambda ctx, bag: FingerprintInput(files=bag["files"]),
                ),
                PipelineStage(
                    id="parse",
                    agent_id="parse",
                    description="Extract canonical text and structure",
                    input_builder=lambda ctx, bag: ParseInput(files=bag["files"]),
                    output_merger=lambda bag, out: {**out, "parsed_files": out["files"]},
                ),
                PipelineStage(
                    id="cleanstack",
                    agent_id="cleanstack",
                    description="Exact and near-duplicate decisions",
                    input_builder=lambda ctx, bag: CleanStackInput(files=bag["files"]),
                    output_merger=lambda bag, out: {
                        **out,
                        "cleanstack_report": out["report"],
                    },
                ),
                PipelineStage(
                    id="chunk",
                    agent_id="chunk",
                    description="Chunk canonical keepers with provenance",
                    input_builder=lambda ctx, bag: ChunkInput(
                        keepers=bag["keepers"], decisions=bag.get("decisions") or []
                    ),
                ),
                PipelineStage(
                    id="graph_weaver",
                    agent_id="graph_weaver",
                    description="Weave evidence-bound knowledge graph",
                    input_builder=lambda ctx, bag: WeaverInput(
                        chunks=bag["chunks"],
                        canonical_document_ids=bag.get("canonical_document_ids") or [],
                    ),
                ),
                PipelineStage(
                    id="embed",
                    agent_id="embed",
                    description="Embed keeper chunks (quotes store)",
                    input_builder=lambda ctx, bag: EmbedInput(chunks=bag["chunks"]),
                ),
                PipelineStage(
                    id="index_health",
                    agent_id="index_health",
                    description="Compute Knowledge Health Score",
                    input_builder=lambda ctx, bag: HealthInput(
                        cleanstack_report=bag.get("cleanstack_report") or {},
                        nodes_created=bag.get("nodes_created") or 0,
                        edges_created=bag.get("edges_created") or 0,
                        evidence_bound_edges=bag.get("evidence_bound_edges") or 0,
                        embedded_count=bag.get("embedded_count") or 0,
                    ),
                ),
            ],
        )
    )

    def _after_guard(bag: dict[str, Any]) -> dict[str, Any] | None:
        if bag.get("blocked"):
            return {
                "decision": "refuse",
                "answer": (
                    "I can’t help with secrets or personal data requests. "
                    "I only answer from the connected knowledge base."
                ),
                "reason_codes": bag.get("reason_codes") or ["SECRET_OR_SENSITIVE_REQUEST"],
                "retrieval_mode": "refuse",
                "trust_score": {"overall": 0.0},
                "trust_trail": [],
                "claims": [],
                "citations": [],
            }
        return None

    def _after_resolve(bag: dict[str, Any]) -> dict[str, Any] | None:
        # Comparisons must reach quote_fill / hybrid — do not early-exit on clarify
        sides = bag.get("compare_sides") or []
        if bag.get("comparison") or len(sides) >= 2:
            return None
        if bag.get("resolved_clearly") is False and bag.get("clarify_options"):
            return {
                "decision": "clarify",
                "clarification_prompt": bag.get("clarification_prompt"),
                "clarify_options": bag.get("clarify_options") or [],
                "reason_codes": bag.get("reason_codes") or ["ENTITY_AMBIGUOUS"],
                "retrieval_mode": "clarify",
                "trust_score": {
                    "overall": 0.35,
                    "entity_resolution": 0.4,
                    "path_strength": 0.0,
                    "evidence_coverage": 0.0,
                    "source_quality": 0.5,
                    "conflict_penalty": 0.0,
                    "recency_penalty": 0.0,
                },
                "trust_trail": [],
                "claims": [],
                "citations": [],
            }
        return None

    def _after_graph(bag: dict[str, Any]) -> dict[str, Any] | None:
        # Only early-exit to refuse when structural and not viable and not fuzzy
        if (
            not bag.get("viable_evidence_bound_trail")
            and bag.get("intent") != "fuzzy"
        ):
            # Still continue to quote_fill? Plan says: No → Fuzzy? → else refuse.
            # So for non-fuzzy, we can skip quote fill and refuse via judge by passing empty quotes.
            # Let pipeline continue into quote_fill which will no-op, then judge refuses.
            return None
        return None

    orch.register_pipeline(
        PipelineDefinition(
            id="ask_pipeline",
            display_name="Ask Pipeline (Resolve -> Walk -> Prove -> Judge)",
            stages=[
                PipelineStage(
                    id="guard",
                    agent_id="policy_secret_guard",
                    description="Policy and secret guard",
                    input_builder=lambda ctx, bag: GuardInput(question=bag["question"]),
                    early_exit=_after_guard,
                ),
                PipelineStage(
                    id="route",
                    agent_id="route",
                    description="Route structural vs fuzzy",
                    input_builder=lambda ctx, bag: RouteInput.model_validate(bag),
                    early_exit=lambda bag: _after_guard({**bag, "blocked": bag.get("intent") == "blocked"}),
                ),
                PipelineStage(
                    id="entity_resolve",
                    agent_id="entity_resolve",
                    description="Resolve entities against the graph",
                    input_builder=lambda ctx, bag: EntityResolveInput.model_validate(bag),
                    early_exit=_after_resolve,
                ),
                PipelineStage(
                    id="graph_retrieve",
                    agent_id="graph_retrieve",
                    description="Walk evidence-bound knowledge graph",
                    input_builder=lambda ctx, bag: GraphRetrieveInput.model_validate(bag),
                    early_exit=_after_graph,
                ),
                PipelineStage(
                    id="quote_fill",
                    agent_id="quote_fill",
                    description="Find quotes along the Trust Trail",
                    input_builder=lambda ctx, bag: QuoteFillInput.model_validate(bag),
                ),
                PipelineStage(
                    id="evidence_judge",
                    agent_id="evidence_sufficiency_judge",
                    description="Verify every claim — answer, clarify, or refuse",
                    input_builder=lambda ctx, bag: EvidenceJudgeInput(
                        question=bag["question"],
                        intent=bag.get("intent") or "structural",
                        quotes=bag.get("quotes") or [],
                        retrieval_mode=bag.get("retrieval_mode") or "graph_primary",
                        best_trail=bag.get("best_trail"),
                        reason_codes=bag.get("reason_codes") or [],
                        entity_resolution_score=bag.get("entity_resolution_score") or 0.0,
                        path_strength=(
                            (bag.get("best_trail") or {}).get("path_strength")
                            if isinstance(bag.get("best_trail"), dict)
                            else getattr(bag.get("best_trail"), "path_strength", 0.0)
                        )
                        or bag.get("path_strength")
                        or 0.0,
                        clarify_options=bag.get("clarify_options") or [],
                        clarification_prompt=bag.get("clarification_prompt"),
                    ),
                ),
            ],
        )
    )
    return orch


class AppRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.registry = build_registry()
        self.orchestrator = build_orchestrator(self.registry)
        self.vector_store = VectorStore()
        self.llm = get_llm_provider(self.settings)

    @property
    def demo_mode(self) -> bool:
        return self.settings.use_mock_llm or getattr(self.llm, "mode", "") == "mock"

    @property
    def provider_mode(self) -> str:
        return getattr(self.llm, "mode", "mock")


_runtime: AppRuntime | None = None


def get_runtime() -> AppRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AppRuntime()
    return _runtime
