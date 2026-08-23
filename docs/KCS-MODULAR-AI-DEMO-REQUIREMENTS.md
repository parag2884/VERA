# KCS Modular AI Demo Framework — Requirements (Simple)

**Source:** KCS Data and AI — Internal AI and Demo Plans  
**Audience:** Product / eng — understand the ask, decide what VERA should pick up  
**Status:** Captured requirements + VERA value-add view

---

## 1. What this plan is asking for (plain English)

KCS wants a **demo kit**, not one fixed product.

Think of Lego blocks for AI demos:

- Swap the **logo / branding** for each client
- Swap the **sample data** for each industry
- Turn **features on/off** based on what the client cares about (chat, dashboards, content writing, automation, etc.)

**Goal:** In a sales or discovery meeting, show something that *feels* like it could live in the client’s world — without building a full custom product every time.

---

## 2. Business case (simple)

| Today | With this framework |
|-------|---------------------|
| Hard to show “what AI could look like for you” quickly | Mix modules to match the client’s ambition |
| Generic demos feel fake | Industry sample data + client branding feel real |
| Clients only see the chat box | Also show how the system is built (orchestration, data access, monitoring) |
| Every demo is a one-off | Reuse the same agents, UIs, and data stores |

**Success looks like:** faster demos, more relevant demos, clearer story of *how* KCS builds AI — not only *what* the chatbot says.

---

## 3. Suggested tech stack (from the plan)

- **Azure AI Foundry** — host / govern agents and models  
- **Microsoft Fabric / SQL / similar** — structured sample data  
- **Azure Blob Storage** — files and artifacts  
- **Azure AI Search** — vector / unstructured retrieval  
- **Power BI** — dashboards  
- **LangGraph / Semantic Kernel** — agent orchestration  
- **Graph DB (e.g. Cosmos Graph)** — GraphRAG / knowledge graphs (called out as future / harder with dummy data)  
- **LLMOps** — Foundry tooling and/or LangSmith for traces and metrics  

---

## 4. Functional requirements (modules)

Each module below is **optional in a given demo**. Modularity is a hard requirement: clients should not be forced to see everything.

### 4.1 UI / user portal

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| UI-1 | User portal to submit prompts / requests | A place people talk to the AI |
| UI-2 | Swappable client branding (logos, theme) | Change logo so it looks like *their* product |
| UI-3 | Chat-style prompting | Classic chatbot experience |
| UI-4 | Dummy AI performance dashboards in UI | Show metrics screens, even if data is sample |
| UI-5 | Optional Teams-style entry point | Demo “AI inside Teams” via a dummy Teams → API path |

### 4.2 Prompt ingestion (middleware)

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| PI-1 | Sanitize / gate prompts before orchestration | Safety and hygiene layer between UI and agents |
| PI-2 | May be shown as architecture diagram only | Clients may not see this live; still document it |

### 4.3 Orchestration / agentic infrastructure

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| OR-1 | Receive prompt, pick / validate use case | Router that decides *what kind of job* this is |
| OR-2 | Optional human-in-the-loop for use-case validation | Person confirms before the system proceeds |
| OR-3 | Consistent agent structure (state, description, prompts, routing rules) | Same pattern every agent — good for governance demos |
| OR-4 | Diagrams of how modules assemble | Show architecture even when code is not shown |
| OR-5 | Host on VMs (LangGraph) and/or cloud (Foundry) | Flexible hosting story |

### 4.4 AI-accessible data stores

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| DS-1 | Vector store for docs (Azure AI Search) + industry sample docs | “Ask your documents” demos |
| DS-2 | Structured DBs with sample data (Fabric, SQL, etc.) | “Ask your tables / warehouse” demos |
| DS-3 | Graph DB for knowledge graph / GraphRAG | Relationship-aware retrieval (noted as harder; future) |
| DS-4 | Blob storage for artifacts | Store files, generated docs, outputs |

### 4.5 AI data access agents

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| DA-1 | Agents that interpret “what data is needed” and fetch it | Dedicated retrieve-from-repo skills |
| DA-2 | Separate agents per industry and/or data type | Banking vs healthcare vs general docs, etc. |

### 4.6 AI fact-checking agents

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| FC-1 | Check retrieved data for accuracy and relevance to the prompt | Guard against wrong or off-topic use of data |
| FC-2 | Showcase as an architectural safeguard vs hallucination | Clients see *trust*, not only *answers* |

### 4.7 AI module repository (internal + governance story)

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| MR-1 | Central place for reusable agents/modules | Don’t rebuild the same agent every demo |
| MR-2 | Show via CI/CD, container registry, and/or Foundry agent registry | “We govern how AI is built and shipped” |

### 4.8 Response assembly and editing

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| RA-1 | Multi-step create → edit → finalize artifacts | Useful when AI *writes* something, not only retrieves |
| RA-2 | Recommended pattern: planner/writer + fact/tech editor + relevance editor/publisher (or 4-way split) | Division of labor between agents |
| RA-3 | Optional human-in-the-loop before publish | Person signs off on the final artifact |
| RA-4 | Skip this path for simple Q&A retrieval | Don’t overbuild chat answers |

### 4.9 LLMOps / monitoring

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| OPS-1 | Log messages and internal reasoning chains | See what the AI did |
| OPS-2 | Performance monitoring (latency, tokens, quality signals) | Prove the system is operable |
| OPS-3 | Platform tools and/or LangSmith-style tracing | Choose Foundry-native or separate ops stack |

### 4.10 Development and performance dashboards

| ID | Requirement | Simple meaning |
|----|-------------|----------------|
| DB-1 | Dashboards for latency, tokens, satisfaction, accuracy, etc. | Visual ops / product health |
| DB-2 | Optionally reshape into general analytics for the client story | Same telemetry → client-facing analytics narrative |

---

## 5. Non-functional / demo constraints

1. **Modular by default** — enable only the modules the client wants to see.  
2. **Branding swappable** — logos and light UI theming without a rebuild.  
3. **Industry sample data** — enough realism to feel familiar; not production data.  
4. **Some capabilities are diagram-only** — prompt middleware, deep orchestration, governance.  
5. **Not every module needs a live UI** — architecture slides are acceptable when UI cannot show the idea well.

---

## 6. Value-add for VERA — what is worth picking

VERA already covers a strong slice of this plan: ingest → knowledge map / hybrid ask → evidence (“prove it”) → fleet → deploy/embed. The question is what from *this* KCS demo plan would make VERA more useful as a **client demo machine** and as a **product**.

### Pick now (high value, fits VERA)

| Idea from plan | Why it helps VERA |
|----------------|-------------------|
| **Client branding swap in Studio / embed** | Demos feel “theirs” in minutes; big sales impact for little architecture change |
| **Industry / client sample corpora packs** | Same VERA engine + different data = many demos (you already have PlayReady / Oz / Thoughtworks as proof) |
| **Mix-and-match “demo packs”** (turn modules on/off) | Match client ambition: retrieval-only vs map+evidence vs deploy/embed |
| **Fact-check / evidence as a first-class story** | Plan calls this out explicitly; VERA already has it — package it as the KCS differentiator vs “chat only” |
| **Simple LLMOps view** (latency, refusals, evidence rate, accuracy) | Turns VERA from a cool chat into a governable AI product story |
| **Human-in-the-loop on publish / high-risk answers** | Enterprise comfort; aligns with “refuse when weak” + optional human sign-off |

### Pick next (medium value)

| Idea from plan | Why / caveat |
|----------------|--------------|
| **Performance / ops dashboard in Studio** | Strong for technically minded clients; don’t fake vanity metrics |
| **Teams (or Slack) entry → same Ask API** | Common enterprise ask; a thin connector is enough for demos |
| **Agent standards card** (state, description, prompts, routing) | Good for architecture slides + Studio “how agents are governed” |
| **Module registry / publish pipeline story** | You already have deploy/embed; add a clearer “approved agent catalog” narrative |
| **Planner → writer → editor path** | Only when demo is *content creation*; keep it off for pure evidence Q&A so VERA stays sharp |

### Deprioritize for VERA (lower unique value or already covered)

| Idea from plan | Why lower priority for us |
|----------------|---------------------------|
| Building GraphRAG “from scratch” as future work | VERA already has graph + hybrid retrieval; invest in *accuracy and demo packs*, not a second graph stack |
| Separate fact-check *product* beside VERA | Evidence/refuse is already core; don’t fork a parallel agent product |
| Full Fabric + Power BI + Redshift matrix for every demo | Heavy; use only when the *client story* is analytics/warehouse — otherwise blob + docs + VERA graph is enough |
| Showing deep prompt-sanitization UI | Keep as architecture note; clients care about outcomes and trust |

### One-line recommendation

**Use VERA as the modular demo core:** branding + industry data packs + evidence/trust story + light ops dashboard + optional Teams/embed. Skip rebuilding the whole KCS stack; fill the gaps that make demos feel client-specific and enterprise-ready.

---

## 7. Suggested VERA backlog (if we align to this plan)

1. **Demo branding kit** — logo, accent color, product name on Studio + embed widget  
2. **Corpus packs** — one-click load of industry sample sets with canned “wow” questions  
3. **Demo mode presets** — Retrieval / Evidence+Map / Deploy+Embed feature toggles  
4. **Trust ops strip** — accuracy, refuse rate, evidence coverage, latency (real numbers where possible)  
5. **HITL publish** — optional approve step before embed goes live or before high-stakes answers  
6. **Collab connector (demo)** — Teams bot → existing Ask API  

---

## 8. Open questions for KCS / product

1. Is the primary buyer story **sales demos**, **delivery accelerators**, or both?  
2. Which industries get sample packs first?  
3. Must demos run on **Foundry-only**, or is current VERA hosting acceptable for internal demos?  
4. How much **live architecture** vs **slides** do clients expect in a 30–45 minute session?
