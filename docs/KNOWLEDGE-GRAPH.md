# Knowledge Graph in VERA

> VERA doesn’t search for answers first. It walks the knowledge, builds a Trust Trail, and proves every claim with evidence.

**Invariant:** `No evidence-bearing edge = no answer-bearing edge`

This document explains what the knowledge graph (KG) is, how VERA uses it, and **why it is a lasting advantage over a regular vector database alone**.

---

## 1. What the knowledge graph is

The KG is a typed, workspace-scoped network of:

| Element | Meaning |
|---------|---------|
| **Nodes** | Entities — products, policies, people, systems, concepts, documents, chunks |
| **Edges** | Relations — `REQUIRES`, `OWNED_BY`, `SUPERSEDES`, `DEFINED_IN`, `MENTIONS`, … |
| **Edge evidence** | Quote spans that justify an edge (document + offset / text) |
| **Edge class** | `asserted_fact` (answer-bearing) vs documentary structure |

Vectors (Chroma) still exist for similarity search. They are **secondary**. The graph is the primary structure for *how facts relate* and *whether a claim is allowed*.

```
Documents ──Weaver──▶  Nodes + Edges + Evidence
                              │
                              ▼
Ask: resolve entities → multi-hop walk → Trust Trail → quote fill → judge
```

---

## 2. How the graph is built

Pipeline step: **Weaver** (`backend/app/agents/ingest/weaver.py`)

```
Connect → Parse → CleanStack → Chunk → Weaver → Embed
```

Weaver does three complementary jobs:

1. **Documentary structure** — Document → Chunk → `MENTIONS` / `DEFINED_IN` so every entity stays anchored to source text.
2. **Asserted facts** — LLM + rules extract relations that can support answers (`REQUIRES`, ownership, supersession, …), **only when a real evidence span exists**.
3. **Identity hygiene** — structural normalize + optional domain-profile aliases + soft linking (with version guards) so “SL 3000” and “SL3000” collapse without inventing product dictionaries in code.

Domain vocabulary comes from **documents and agent domain profile**, not hardcoded MFA/VPN/PlayReady tables in the engine.

---

## 3. How Ask uses the graph

```
Guard → Route → Resolve → Graph Retrieve → Quote Fill → Evidence Judge
```

1. **Resolve** — map question mentions to graph nodes (disambiguate versions / candidates).
2. **Graph retrieve** — walk up to `VERA_GRAPH_HOPS` along evidence-bound edges; prefer shorter paths.
3. **Trust Trail** — the path of nodes/edges that justify the answer.
4. **Quote fill** — attach evidence quotes (and hybrid KB packs when the trail is thin).
5. **Judge** — answer, clarify, or refuse from evidence — not from model memory.

Studio **Maps** visualizes the same structure: asserted edges, documentary links, neighborhoods, Fit viewport.

---

## 4. Vector DB alone vs knowledge graph

A **regular vector database** stores chunk embeddings and returns “nearest neighbors” to a query. That is excellent for *semantic recall*. It is weak at *structured truth*.

| Dimension | Vector DB alone | VERA knowledge graph (+ vectors) |
|-----------|-----------------|----------------------------------|
| Unit of retrieval | Similar text chunks | Entities, typed relations, evidence spans |
| Multi-hop reasoning | Prompt hopes the LLM stitches chunks | Explicit walk: A → B → C with edge types |
| Provenance | “These chunks looked similar” | Edge → quote → document (Trust Trail) |
| Refusal / clarify | Soft — model may hallucinate glue | Hard invariant — no evidence edge ⇒ no answer edge |
| Identity | Same concept may appear as many near-dupe chunks | Canonical nodes + aliases + version guards |
| “Does X require Y?” | Similarity may miss the rule sentence | Direct `REQUIRES` (or path) with quote |
| “Who owns X?” | May retrieve unrelated bios | `OWNED_BY` (or domain equivalent) trail |
| Supersession / version | Easy to mix v1 and v2 | Graph can encode `SUPERSEDES` and versioned nodes |
| Audit / compliance | Hard to show *why* | Trail + citations designed for review |
| Maps / exploration | Usually none | First-class Knowledge Map |
| Drift over time | Re-embed; structure still implicit | Re-weave; structure stays queryable |

### Failure mode of “vectors only”

Classic RAG:

1. Embed question  
2. Top‑k similar chunks  
3. Stuff into prompt  
4. Hope the model doesn’t invent a link

That works for FAQ-style prose. It fails when the answer is a **relation across documents**, when **versions collide**, or when you must **prove** the answer — not just sound plausible.

---

## 5. Benefits of the knowledge graph (now)

1. **Evidence-bound answers** — every asserted edge carries quote evidence; the judge can refuse.
2. **Trust Trail** — users and auditors see the path, not a black-box retrieval dump.
3. **Multi-hop questions** — “policy → control → owner” without relying on one magic chunk.
4. **Clarify instead of guess** — ambiguous entities surface options instead of a wrong merge.
5. **Maps as a product surface** — stakeholders explore structure, not only chat.
6. **Domain-dynamic weave** — new corpora shape the graph; the engine stays generic.
7. **Hybrid when needed** — broad “what is…?” still uses lexical/vector packs (`hybrid_kb`) so UX doesn’t die when no short trail exists.

---

## 6. Benefits later (strategic — why KG wins over time)

These compound as the corpus and product mature. A pure vector store does not unlock them cleanly.

### 6.1 Compounding structure

Every ingest adds **nodes and edges**, not only more anonymous chunks.  
Later questions reuse earlier structure. The KB becomes a **shared memory of facts**, not a larger bag of embeddings.

### 6.2 Cross-document consistency

Vectors retrieve local similarity. The graph can encode:

- one product node mentioned in 40 PDFs  
- one policy that supersedes another  
- one owner linked from multiple runbooks  

That is how you answer portfolio questions (“where is X required?”) without N separate RAG calls and N conflicting summaries.

### 6.3 Change impact & supersession

When a document updates, you can deactivate or supersede edges and re-weave. Downstream Ask sees **which fact is current**. Vector-only systems usually bury old and new text in the same similarity soup.

### 6.4 Safer agents & publish surfaces

Published embed agents (`/api/public/chat`) inherit the same invariant. As you monetize embeds, **refuse/clarify** is a product feature — not a bug. Vector RAG that always “answers” is a liability in regulated or contractual domains (PlayReady, security policy, HR).

### 6.5 Explainability as a moat

Buyers increasingly ask: *Show me why.*  
Trust Trails, Maps, and edge evidence are demos you cannot fake with cosine similarity alone. That becomes sales and compliance collateral.

### 6.6 Evaluation & quality loops

You can score:

- % questions answered via `graph_primary`  
- trail length / hop quality  
- evidence coverage per asserted edge  
- orphan entity rate  

Those metrics drive Weaver improvements. Vector RAG evals stay stuck at “answer looks good.”

### 6.7 Future capabilities that need a graph

| Capability | Needs graph? | Why vectors alone struggle |
|------------|--------------|----------------------------|
| Impact analysis (“what depends on X?”) | Yes | No dependency edges |
| Policy diff / supersession UI | Yes | No typed version links |
| Entity-centric memory across sessions | Yes | Chunks aren’t stable identities |
| Constrained tool use (act only on trail) | Yes | No machine-checkable path |
| Human curation (confirm/reject edges) | Yes | Nothing to curate but text |
| Multi-agent shared world model | Yes | Each agent re-embeds the same soup |

VERA’s hybrid design means you **keep** vector search for recall and overview — you just stop treating it as the source of truth.

---

## 7. Recommended posture: hybrid with graph first

| Mode chip | Role |
|-----------|------|
| `graph_primary` | Preferred — trail led the answer |
| `hybrid_graph_kb` | Trail + document gap-fill |
| `hybrid_kb` | Overview / thin trail — vector + lexical still useful |
| clarify / refuse | Integrity over fluency |

**Do not** replace the graph with “better embeddings.”  
**Do** use vectors to fill quotes and answer broad questions when the weave has no short asserted path.

Config preference: `VERA_RETRIEVAL_MODE=graph_primary`  
See also: chatbot note in `Vera_PlayReady_Chatbot/docs/RETRIEVAL.md`.

---

## 8. Mental model (one picture)

```
Vector DB:   "Which paragraphs sound like the question?"
Knowledge graph: "Which proven relations answer the question — and show the quotes?"
```

| If you only need… | Vectors may be enough |
|--------------------|------------------------|
| Semantic search over a wiki | Often yes |
| Chat that must prove requirements, ownership, versions | No — you need a KG |
| Audit trail, Maps, publishable refuse/clarify | No — you need a KG |

VERA is built for the second and third rows.

---

## 9. Key code pointers

| Concern | Path |
|---------|------|
| Weave / evidence edges | `backend/app/agents/ingest/weaver.py` |
| Identity normalize | `backend/app/identity.py` |
| Graph storage / evidence | `backend/app/stores/sql.py` |
| Multi-hop retrieve | `backend/app/agents/ask/graph_retrieve.py` |
| Hybrid evidence pack | `backend/app/agents/ask/retrieve.py` |
| Knowledge Map UI | `frontend/src/pages/KnowledgeMap.tsx` |

Related docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [CONFIGURATION.md](CONFIGURATION.md)
