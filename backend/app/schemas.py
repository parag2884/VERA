from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Decision = Literal["answer", "clarify", "refuse"]
EdgeClass = Literal["documentary", "asserted_fact", "derived"]
ProviderMode = Literal["azure", "mock"]


class TrustScore(BaseModel):
    overall: float = 0.0
    entity_resolution: float = 0.0
    path_strength: float = 0.0
    evidence_coverage: float = 0.0
    source_quality: float = 0.0
    conflict_penalty: float = 0.0
    recency_penalty: float = 0.0


class TrustTrailHop(BaseModel):
    from_name: str = Field(alias="from")
    rel: str
    to_name: str = Field(alias="to")
    edge_id: str | None = None
    evidence_quote: str | None = None

    model_config = {"populate_by_name": True}


class ClaimOut(BaseModel):
    claim_id: str
    claim_text: str
    support_status: str
    trust_score: float = 0.0


class CitationOut(BaseModel):
    claim_id: str | None = None
    document: str
    locator: str | None = None
    quote: str
    chunk_id: str | None = None
    edge_id: str | None = None


class ClarifyOption(BaseModel):
    id: str
    label: str
    description: str | None = None


class ChatRequest(BaseModel):
    workspace_id: str
    question: str
    session_id: str | None = None
    assistant_id: str | None = None
    tone: Literal["professional", "friendly", "concise", "formal", "executive"] = "professional"
    verbosity: Literal["short", "balanced", "detailed"] = "balanced"


class ChatResponse(BaseModel):
    decision: Decision
    answer: str | None = None
    clarification_prompt: str | None = None
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    trust_score: TrustScore = Field(default_factory=TrustScore)
    trust_trail: list[TrustTrailHop] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    retrieval_mode: str = "graph_primary"
    provider_mode: ProviderMode = "azure"
    demo_mode: bool = False
    session_id: str | None = None
    message_id: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class WorkspaceCreate(BaseModel):
    name: str = "Public Agent"


class WorkspaceOut(BaseModel):
    id: str
    name: str
    created_at: str


class AgentCreate(BaseModel):
    name: str = "New Agent"
    description: str = ""


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    allowed_origins: str | None = None
    published: bool | None = None
    disabled: bool | None = None
    rotate_embed_key: bool = False


class AskReadinessOut(BaseModel):
    status: Literal["unknown", "ready", "needs_attention"] = "unknown"
    pass_rate: float | None = None
    failing_patterns: list[str] = Field(default_factory=list)
    passage: dict[str, Any] = Field(default_factory=dict)


class AgentOut(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str | None = None
    name: str
    slug: str
    description: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    embed_key: str | None = None
    allowed_origins: str = "*"
    published: bool = False
    disabled: bool = False
    created_at: str
    counts: dict[str, int] = Field(default_factory=dict)
    ask_readiness: AskReadinessOut | None = None


class AgentPublishOut(BaseModel):
    id: str
    name: str
    published: bool
    embed_key: str
    embed_snippet: str
    embed_url: str
    allowed_origins: str


class AgentEndpoints(BaseModel):
    embed_url: str | None = None
    widget_snippet: str | None = None
    public_config_url: str | None = None
    public_chat_url: str
    studio_ask_hint: str = "POST /api/chat with workspace_id"


class AgentFleetItem(BaseModel):
    id: str
    name: str
    slug: str
    description: str = ""
    workspace_id: str
    published: bool = False
    disabled: bool = False
    readiness: Literal["draft", "ready", "live", "disabled"] = "draft"
    ask_status: Literal["unknown", "ready", "needs_attention"] = "unknown"
    ask_pass_rate: float | None = None
    ask_failing_patterns: list[str] = Field(default_factory=list)
    embed_key: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    endpoints: AgentEndpoints
    monetize_hint: str = ""


class PricingTier(BaseModel):
    id: str
    name: str
    price_label: str
    blurb: str
    features: list[str] = Field(default_factory=list)
    highlighted: bool = False


class TrustCenter(BaseModel):
    grounded_pct: float = 0.0
    evidence_coverage_pct: float = 0.0
    unsupported_claims: int = 0
    conflicts: int = 0
    asks_sampled: int = 0
    status: Literal["trusted", "review", "building"] = "building"


class AiFinding(BaseModel):
    id: str = ""
    kind: Literal["ok", "warn", "info"] = "ok"
    text: str
    drillable: bool = False


class GraphInsights(BaseModel):
    health_score: float = 0.0
    most_connected: str = ""
    top_agent: str = ""
    top_agent_asks: int = 0
    concepts: int = 0
    relationships: int = 0


class FindingProofItem(BaseModel):
    id: str = ""
    title: str
    subtitle: str = ""
    detail: str = ""
    agent_name: str = ""
    workspace_id: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class FindingProofOut(BaseModel):
    kind: str
    title: str
    total: int = 0
    showing: int = 0
    items: list[FindingProofItem] = Field(default_factory=list)
    map_hint: str = "Open Maps to inspect these nodes and edges in context."


class PlatformIntelligence(BaseModel):
    trust: TrustCenter = Field(default_factory=TrustCenter)
    findings: list[AiFinding] = Field(default_factory=list)
    graph: GraphInsights = Field(default_factory=GraphInsights)


class StudioDashboard(BaseModel):
    plan: str = "builder"
    plan_label: str = "Builder"
    api_base: str
    widget_origin: str
    totals: dict[str, int] = Field(default_factory=dict)
    agents: list[AgentFleetItem] = Field(default_factory=list)
    pricing: list[PricingTier] = Field(default_factory=list)
    revenue_model: list[str] = Field(default_factory=list)
    intelligence: PlatformIntelligence = Field(default_factory=PlatformIntelligence)


class PublicChatRequest(BaseModel):
    embed_key: str
    question: str
    session_id: str | None = None


class PublicAgentConfig(BaseModel):
    name: str
    greeting: str
    placeholder: str
    accent: str
    show_trust_trail: bool = True
    show_citations: bool = True
    streaming: bool = True
    published: bool = True
    disabled: bool = False
    disabled_message: str | None = None


class JobOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    status: str
    progress: float
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class UrlIngestRequest(BaseModel):
    workspace_id: str
    url: str
    max_pages: int | None = None
    max_depth: int | None = None


class SharePointIngestRequest(BaseModel):
    workspace_id: str
    url: str | None = None
    demo: bool = False


class BlobIngestRequest(BaseModel):
    workspace_id: str
    container: str
    prefix: str | None = None


class GraphNodeOut(BaseModel):
    id: str
    type: str
    name: str
    normalized_name: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeOut(BaseModel):
    id: str
    src: str
    dst: str
    rel_type: str
    edge_class: str
    weight: float = 1.0
    status: str = "active"
    has_evidence: bool = False


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class HealthOut(BaseModel):
    score: float
    components: dict[str, Any]
    demo_mode: bool = False


class CleanStackReportOut(BaseModel):
    total_files: int
    keepers: int
    exact_duplicates: int
    near_duplicates: int
    embeddings_avoided: int
    tokens_avoided: int
    estimated_usd_avoided: float | None = None
    pricing_note: str | None = None
    groups: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class AgentInfo(BaseModel):
    id: str
    display_name: str


class StatusOut(BaseModel):
    version: str
    demo_mode: bool
    provider_mode: ProviderMode
    retrieval_mode: str
    agents: list[AgentInfo]
    pipelines: list[dict[str, str]]
