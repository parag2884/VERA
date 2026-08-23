# Architecture

## Product shape

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Studio UI   │────▶│ FastAPI      │────▶│ SQLite graph DB │
│ :5173       │     │ :8080        │     │ + Chroma vectors│
└─────────────┘     └──────┬───────┘     └─────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Ingest DAG    Ask DAG     Public /embed
         (Weaver)   (graph-first)  (embed_key)
```

## Ingest pipeline

```
Connect → Fingerprint → Parse → CleanStack → Chunk → Weaver → Embed
```

- **Weaver** extracts entities/relations with LLM + structural rules.
- Entity identity uses **structural normalize** (`backend/app/identity.py`) — optional **domain profile aliases** from agent settings; no product-specific hardcodes in the engine.
- Edges include asserted facts plus documentary links (`DEFINED_IN`, `MENTIONS`).
- Soft entity linking merges near-duplicates with version guards.
- Demo seed data only applies to the **sample KB fingerprint**, not customer corpora.

Deep dive (KG model, Trust Trail, **why graph beats vector-only RAG**): [KNOWLEDGE-GRAPH.md](KNOWLEDGE-GRAPH.md).

Key files:

- `backend/app/agents/ingest/weaver.py`
- `backend/app/identity.py`
- `backend/app/stores/sql.py`

## Ask pipeline

```
Guard → Route → Resolve → Graph Retrieve → Quote Fill → Evidence Judge
```

Configured preference: `VERA_RETRIEVAL_MODE=graph_primary`.

| Actual mode (response chip) | When |
|----------------------------|------|
| `graph_primary` | Short evidence-bound trail answers the question |
| `hybrid_graph_kb` | Graph trail + KB quote gap-fill |
| `hybrid_kb` | Broad / overview; lexical+vector packs |
| `document_overview` | Document-centric overview |
| `name_lookup` | People / candidate resolution |

Broad “what is X?” often lands on `hybrid_kb`. Trail-shaped compliance questions prefer `graph_primary`. Hybrid-with-graph-first is the intended product posture.

Key files:

- `backend/app/agents/ask/graph_retrieve.py` — multi-hop walk (`VERA_GRAPH_HOPS`)
- `backend/app/agents/ask/quote_fill.py`, `retrieve.py`
- `backend/app/services/ask_chat.py`

## Knowledge Maps

Studio **Maps** loads workspace graph JSON and renders force layouts:

- Structure lens: asserted edges + `DEFINED_IN` + `MENTIONS`→document
- Degree-aware radii, collide force, Fit viewport
- Selection neighborhood focus

Key file: `frontend/src/pages/KnowledgeMap.tsx`

## Agents & publish

- Each agent owns a `workspace_id` (KB isolation).
- Publish generates / exposes `embed_key`.
- Public routes only serve **published** agents and enforce `allowed_origins`.

See [PUBLISHING.md](PUBLISHING.md) and [PUBLIC-API.md](PUBLIC-API.md).

## Knowledge OS

Workspace-scoped intelligence around the same graph (not a second KB):

- Coverage by site section / document family
- Numeric contradiction → `CONFLICTS_WITH`
- Human feedback on Ask (`POST /api/chat/feedback`)
- Production weak-answer mining
- Source reliability in quote ranking

`GET /api/workspaces/{id}/knowledge-os` · Insights panel.

Self-learning (same graph): edge weights and path win-rates from Ask/eval outcomes; draft goldens with human Accept/Reject; Section→Topic→Page on web ingest; `valid_from` on DEFINED_IN when a year is in the text; verifier on low-trust or regulated-looking domains; refuse suggests missing URLs/entities.

Governance (same workspace): graph **weight snapshots** before Trust Forge heal and after each eval gen; **Promote / Rollback** on Insights; **audit** of weight changes; **policy locks** (`lock_rel` / `lock_edge`); **learningMode** live | shadow | gated | off; SLO-ish refusal/trust from recent Ask; metric history. Rollback restores edge weights + path stats, not a full node-by-node clone. Learning never crosses `workspace_id`.

## Identity rule

Domain vocabulary (PlayReady, VPN, MFA, …) must come from **documents + agent domain profile**, never from hardcoded product dictionaries in retrieve/route paths.
