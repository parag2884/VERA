const API = import.meta.env.VITE_API_URL || "";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export type Workspace = { id: string; name: string; created_at: string };

export type TrustForgeCaseDelta = {
  id: string;
  fail_kind?: string;
  was_fail_kind?: string;
};

export type TrustForgeDelta = {
  vs_gen?: boolean | null;
  fitness_before?: number | null;
  fitness_after?: number;
  fitness_delta?: number | null;
  newly_passed?: TrustForgeCaseDelta[];
  newly_failed?: TrustForgeCaseDelta[];
  still_failed?: TrustForgeCaseDelta[];
  heal?: Record<string, unknown>;
  summary?: string;
};

export type TrustForgeGeneration = {
  gen: number;
  fitness: number;
  passed: number;
  failed: number;
  total: number;
  hygiene_report?: Record<string, unknown>;
  fail_ids?: string[];
  case_results?: Array<{ id: string; pass: boolean; fail_kind?: string }>;
  delta?: TrustForgeDelta;
  created_at?: string;
};

export type TrustForgeCaseMatrix = {
  generations: number[];
  rows: Array<{
    id: string;
    trend: "improved" | "regressed" | "still_fail" | "still_pass" | "same" | string;
    cells: Array<{
      status: "pass" | "fail" | "unknown" | string;
      fail_kind?: string;
      decision?: string;
      answer_preview?: string;
    }>;
    question?: string;
    expected_answer?: string;
    got_answer?: string;
    decision?: string;
    fail_kind?: string;
    must_any?: string[];
    kb_quote_hint?: string;
    source?: string;
    notes?: string[];
  }>;
  summary?: {
    improved: number;
    regressed: number;
    still_fail: number;
    total: number;
  };
};

export type TrustForgeGraphChanges = {
  steps: Array<{
    gen: number;
    aliases_removed: number;
    junk_persons_retyped: number;
    alias_count?: number | null;
    entity_count?: number | null;
    code_or_level_nodes?: number | null;
    had_heal?: boolean;
  }>;
  totals: {
    aliases_removed: number;
    junk_persons_retyped: number;
  };
};

export type TrustForgeProgress = {
  phase?: string;
  message?: string;
  generation?: number;
  max_generations?: number;
  case_index?: number;
  case_total?: number;
  case_id?: string;
  question?: string;
  expected_answer?: string;
  got_answer?: string;
  decision?: string;
  case_pass?: boolean;
  fail_kind?: string;
  passed_so_far?: number;
  failed_so_far?: number;
  fitness?: number;
  best_fitness?: number;
  threshold?: number;
  improvement?: TrustForgeDelta;
  log?: string[];
};

export type TrustForgeRun = {
  id: string;
  workspace_id: string;
  agent_id: string;
  suite_path: string;
  threshold: number;
  max_generations: number;
  stall_generations: number;
  status: "queued" | "running" | "completed" | "failed" | "stopped" | string;
  best_fitness: number;
  generation: number;
  stop_reason?: string | null;
  error?: string | null;
  progress?: TrustForgeProgress | null;
  latest_improvement?: TrustForgeDelta | null;
  case_matrix?: TrustForgeCaseMatrix | null;
  graph_changes?: TrustForgeGraphChanges | null;
  created_at: string;
  updated_at: string;
  generations?: TrustForgeGeneration[];
  fitness_curve?: number[];
};

export type AskReadiness = {
  status: "unknown" | "ready" | "needs_attention";
  pass_rate?: number | null;
  failing_patterns?: string[];
  passage?: Record<string, unknown>;
};

export type Agent = {
  id: string;
  workspace_id: string;
  workspace_name?: string;
  name: string;
  slug: string;
  description: string;
  settings: Record<string, unknown>;
  embed_key?: string | null;
  allowed_origins: string;
  published: boolean;
  disabled?: boolean;
  created_at: string;
  counts: {
    sources?: number;
    documents?: number;
    chunks?: number;
    nodes?: number;
    edges?: number;
    asks?: number;
  };
  ask_readiness?: AskReadiness | null;
};

export type AgentPublish = {
  id: string;
  name: string;
  published: boolean;
  embed_key: string;
  embed_snippet: string;
  embed_url: string;
  allowed_origins: string;
};

export type StudioDashboard = {
  plan: string;
  plan_label: string;
  api_base: string;
  widget_origin: string;
  totals: {
    agents?: number;
    published?: number;
    documents?: number;
    chunks?: number;
    nodes?: number;
    asks?: number;
  };
  agents: Array<{
    id: string;
    name: string;
    slug: string;
    description: string;
    workspace_id: string;
    published: boolean;
    disabled?: boolean;
    readiness: "draft" | "ready" | "live" | "disabled";
    ask_status?: "unknown" | "ready" | "needs_attention";
    ask_pass_rate?: number | null;
    ask_failing_patterns?: string[];
    embed_key?: string | null;
    counts: Record<string, number>;
    endpoints: {
      embed_url?: string | null;
      widget_snippet?: string | null;
      public_config_url?: string | null;
      public_chat_url: string;
      studio_ask_hint?: string;
    };
    monetize_hint: string;
  }>;
  pricing: Array<{
    id: string;
    name: string;
    price_label: string;
    blurb: string;
    features: string[];
    highlighted?: boolean;
  }>;
  revenue_model: string[];
  intelligence?: {
    trust: {
      grounded_pct: number;
      evidence_coverage_pct: number;
      unsupported_claims: number;
      conflicts: number;
      asks_sampled: number;
      status: "trusted" | "review" | "building";
    };
    findings: Array<{
      id?: string;
      kind: "ok" | "warn" | "info";
      text: string;
      drillable?: boolean;
    }>;
    graph: {
      health_score: number;
      most_connected: string;
      top_agent: string;
      top_agent_asks: number;
      concepts: number;
      relationships: number;
    };
  };
};

export type FindingProofKind =
  | "compliance"
  | "concepts"
  | "relationships"
  | "conflicts"
  | "unsupported";

export type FindingProofItem = {
  id: string;
  title: string;
  subtitle?: string;
  detail?: string;
  agent_name?: string;
  workspace_id?: string;
  meta?: Record<string, unknown>;
};

export type FindingProof = {
  kind: string;
  title: string;
  total: number;
  showing: number;
  items: FindingProofItem[];
  map_hint?: string;
};
export type Job = {
  id: string;
  workspace_id: string;
  type: string;
  status: string;
  progress: number;
  error?: string | null;
  result?: Record<string, unknown>;
  events?: Array<Record<string, unknown>>;
};

export type ChatResponse = {
  decision: "answer" | "clarify" | "refuse";
  answer?: string | null;
  clarification_prompt?: string | null;
  clarify_options?: Array<{ id: string; label: string; description?: string }>;
  reason_codes: string[];
  trust_score: {
    overall: number;
    entity_resolution: number;
    path_strength: number;
    evidence_coverage: number;
    source_quality: number;
    conflict_penalty: number;
    recency_penalty: number;
  };
  trust_trail: Array<{ from: string; rel: string; to: string; evidence_quote?: string }>;
  claims: Array<{ claim_id: string; claim_text: string; support_status: string; trust_score: number }>;
  citations: Array<{ document: string; locator?: string; quote: string }>;
  retrieval_mode: string;
  provider_mode: "azure" | "mock";
  demo_mode: boolean;
  session_id?: string;
  message_id?: string;
  events?: Array<Record<string, unknown>>;
  conflicts?: Array<{ entity?: string; values?: string[]; amounts?: number[] }>;
  reasoning_path?: string[];
  knowledge_gaps?: Array<{ kind?: string; title?: string; detail?: string }>;
};

type StreamHandlers = {
  onStatus?: (message: string) => void;
  onToken?: (text: string) => void;
};

async function consumeAskSse(res: Response, handlers: StreamHandlers = {}): Promise<ChatResponse> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (!res.body) throw new Error("Streaming not supported by this browser");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: ChatResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;
      let ev: { type?: string; message?: string; text?: string; response?: ChatResponse };
      try {
        ev = JSON.parse(raw);
      } catch {
        continue;
      }
      if (ev.type === "status" && ev.message) handlers.onStatus?.(ev.message);
      else if (ev.type === "token" && ev.text) handlers.onToken?.(ev.text);
      else if (ev.type === "done" && ev.response) finalResponse = ev.response;
      else if (ev.type === "error") throw new Error(ev.message || "Stream failed");
    }
  }

  if (!finalResponse) throw new Error("Stream ended without a response");
  return finalResponse;
}

export type GraphData = {
  nodes: Array<{ id: string; type: string; name: string; normalized_name: string }>;
  edges: Array<{
    id: string;
    src: string;
    dst: string;
    rel_type: string;
    edge_class: string;
    has_evidence: boolean;
  }>;
};

export function formatApiError(err: unknown, surface?: "ingest" | "forge"): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (parsed?.detail != null) {
      return typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    }
  } catch {
    /* not JSON */
  }
  if (/502\s*Bad Gateway/i.test(raw) || /<\/html>/i.test(raw)) {
    return "API temporarily unavailable (502). The backend may still be starting — wait a few seconds and retry.";
  }
  if (/504\s*Gateway Time-out/i.test(raw) || /504\s*Gateway Timeout/i.test(raw)) {
    return "Request timed out (504). Try again — large PDFs or Azure calls can take a minute.";
  }
  if (/500\s*Internal Server Error/i.test(raw) || /^Internal Server Error$/i.test(raw.trim())) {
    if (surface === "forge") {
      return "Evaluation did not start (server error). The graph was not rebuilt. Retry once; if it repeats, another run may still be marked active — Stop, then Start again.";
    }
    if (surface === "ingest") {
      return "Ingest hit an error. Wait for any running weave to finish, then retry.";
    }
    return "The API returned an error. Retry in a moment.";
  }
  if (/409\b/.test(raw) || /already running/i.test(raw)) {
    return raw.includes("Trust Forge")
      ? raw
      : "An ingest is already running for this agent. Wait for it to finish, then retry.";
  }
  if (raw.includes("<html")) {
    const m = raw.match(/<title>([^<]+)<\/title>/i) || raw.match(/>(\d{3}\s[^<]+)</);
    return m?.[1]?.trim() || "Request failed";
  }
  return raw;
}

export const api = {
  status: () => req<{ demo_mode: boolean; provider_mode: string; agents: Array<{ id: string; display_name: string }> }>("/api/status"),
  createWorkspace: (name = "Public Agent") =>
    req<Workspace>("/api/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  getWorkspace: (workspaceId: string) => req<Workspace>(`/api/workspaces/${workspaceId}`),
  purgeKnowledge: (workspaceId: string) =>
    req<{ ok: boolean; before?: Record<string, number>; after?: Record<string, number> }>(
      `/api/workspaces/${workspaceId}/purge`,
      { method: "POST" }
    ),
  startTrustForge: (
    workspaceId: string,
    body: {
      agent_id?: string;
      suite_path?: string;
      threshold?: number;
      max_generations?: number;
      stall_generations?: number;
    } = {}
  ) =>
    req<TrustForgeRun>(`/api/workspaces/${workspaceId}/trust-forge/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getTrustForgeRun: (workspaceId: string, runId: string) =>
    req<TrustForgeRun>(`/api/workspaces/${workspaceId}/trust-forge/runs/${runId}`),
  listTrustForgeRuns: (workspaceId: string) =>
    req<{ workspace_id: string; runs: TrustForgeRun[] }>(
      `/api/workspaces/${workspaceId}/trust-forge/runs`
    ),
  stopTrustForgeRun: (workspaceId: string, runId: string) =>
    req<TrustForgeRun>(`/api/workspaces/${workspaceId}/trust-forge/runs/${runId}/stop`, {
      method: "POST",
    }),
  loadSample: (workspaceId: string) => {
    const fd = new FormData();
    fd.append("workspace_id", workspaceId);
    return req<Job>("/api/sources/sample", { method: "POST", body: fd });
  },
  upload: (workspaceId: string, files: FileList) => {
    const fd = new FormData();
    fd.append("workspace_id", workspaceId);
    Array.from(files).forEach((f) => fd.append("files", f));
    return req<Job>("/api/sources/upload", { method: "POST", body: fd });
  },
  ingestUrl: (workspaceId: string, url: string, opts?: { max_pages?: number; max_depth?: number }) =>
    req<Job>("/api/sources/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        url,
        max_pages: opts?.max_pages,
        max_depth: opts?.max_depth,
      }),
    }),
  ingestSharePoint: (
    workspaceId: string,
    opts: { url?: string; demo?: boolean }
  ) =>
    req<Job>("/api/sources/sharepoint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        url: opts.url,
        demo: !!opts.demo,
      }),
    }),
  ingestBlob: (
    workspaceId: string,
    opts: { container: string; prefix?: string }
  ) =>
    req<Job>("/api/sources/blob", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        container: opts.container,
        prefix: opts.prefix,
      }),
    }),
  connectors: () =>
    req<{
      upload: Record<string, unknown>;
      website: Record<string, unknown>;
      sharepoint: { graph_configured: boolean; demo_available: boolean; state?: string };
      blob?: { state?: string; configured?: boolean; note?: string };
      catalog?: Array<{
        id: string;
        kind?: string;
        title: string;
        blurb: string;
        state?: string;
        configured?: boolean;
        setup_hint?: string;
        category?: string;
      }>;
    }>("/api/sources/connectors"),
  job: (workspaceId: string, jobId: string) =>
    req<Job>(`/api/sources/jobs/${workspaceId}/${jobId}`),
  chat: (
    workspaceId: string,
    question: string,
    sessionId?: string,
    opts?: { tone?: string; verbosity?: string }
  ) =>
    req<ChatResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        question,
        session_id: sessionId,
        tone: opts?.tone || "professional",
        verbosity: opts?.verbosity || "balanced",
      }),
    }),
  /**
   * Studio Ask SSE stream. Events: status | token | done | error.
   * Trust trail / citations arrive on `done.response`.
   */
  chatStream: async (
    workspaceId: string,
    question: string,
    sessionId: string | undefined,
    opts: {
      tone?: string;
      verbosity?: string;
      onStatus?: (message: string) => void;
      onToken?: (text: string) => void;
    } = {}
  ): Promise<ChatResponse> => {
    const res = await fetch(`${API}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        question,
        session_id: sessionId,
        tone: opts.tone || "professional",
        verbosity: opts.verbosity || "balanced",
      }),
    });
    return consumeAskSse(res, opts);
  },
  graph: (workspaceId: string) => req<GraphData>(`/api/graph?workspace_id=${workspaceId}`),
  health: (workspaceId: string) =>
    req<{ score: number; components: Record<string, unknown>; demo_mode: boolean }>(
      `/api/health/knowledge?workspace_id=${workspaceId}`
    ),
  knowledgeOs: (workspaceId: string) =>
    req<{
      fitness: number;
      coverage: {
        overall_pct: number;
        domains: Array<{
          section: string;
          pages: number;
          linked_pages: number;
          entities: number;
          coverage_pct: number;
        }>;
        gap_sections: string[];
      };
      conflicts: {
        graph_edges: number;
        count: number;
        detected: Array<{ entity?: string; values?: string[]; amounts?: number[] }>;
      };
      temporal: { supersedes_edges: number };
      source_reliability_avg: number;
      debt?: {
        score: number;
        status: string;
        coverage_pct: number;
        trust_pct: number;
        weak_edges: number;
        unanswered: number;
        risk?: { level?: string; score?: number; causes?: string[] };
        playbook?: {
          current_debt?: number;
          expected_debt_after_fix?: number;
          actions?: Array<{
            step?: number;
            driver?: string;
            cause?: string;
            do?: string;
            clears_points?: number;
            expected_debt_after_this?: number;
          }>;
        };
        drivers: Array<{
          id: string;
          label: string;
          points: number;
          pct?: number;
          action?: string;
        }>;
        drilldown?: {
          weak_edges?: Array<{
            id?: string;
            from?: string;
            to?: string;
            rel?: string;
            weight?: number;
            success_rate?: number | null;
            asks?: number;
          }>;
          topics?: Array<{
            section?: string;
            coverage_pct?: number;
            unlinked_pages?: number;
            expected_coverage_gain?: number;
          }>;
          trust?: Array<{ title?: string; trust_pct?: number; reason?: string }>;
          conflicts?: Array<{ entity?: string; detail?: string }>;
          unanswered?: Array<{
            id?: string | null;
            question?: string;
            fail_kind?: string;
          }>;
          coverage?: Array<{
            section?: string;
            coverage_pct?: number;
            expected_coverage_gain?: number;
          }>;
        };
      };
      proof?: {
        title?: string;
        has_history?: boolean;
        before?: {
          debt?: number | null;
          coverage?: number | null;
          trust?: number | null;
          risk?: string | null;
        };
        after?: {
          debt?: number | null;
          coverage?: number | null;
          trust?: number | null;
          risk?: string | null;
        };
        adoption?: {
          suggested?: number;
          completed?: number;
          rate?: number | null;
          by_driver?: Array<{ driver: string; actions_completed: number }>;
        };
        improvements?: string[];
        remaining?: string[];
      };
      ops?: {
        explain?: string;
        recommendations?: Array<{
          kind?: string;
          section?: string;
          suggested?: string;
          expected_coverage_gain?: number;
          criticality?: string;
          impact?: { pages?: number; apis?: number; applications?: number; teams?: number };
        }>;
        sources?: Array<{
          id?: string;
          title?: string;
          trust_pct?: number;
          owner?: string;
          reviewed_at?: string | null;
          age_days?: number | null;
          freshness?: string;
          criticality?: string;
        }>;
        sla?: {
          passing?: boolean;
          cta?: string;
          next?: string;
          failed_ids?: string[];
          checks?: Array<{
            id?: string;
            title?: string;
            ok?: boolean;
            current?: number;
            target?: string;
            next?: string;
            cta?: string;
          }>;
        };
        care?: {
          mode?: string;
          headline?: string;
          human?: boolean;
          cta?: string | null;
        };
        operate?: {
          status?: string;
          risk?: string;
          debt?: number;
          coverage?: number;
          trust?: number;
          quiet?: boolean;
          week?: { lines?: string[]; risk?: string; text?: string } | null;
          principle?: {
            rule?: string;
            observe?: { label?: string };
            maintain?: { label?: string };
            govern?: { label?: string };
          };
          changes?: string[];
          drift?: Array<{ metric?: string; from?: number; to?: number; note?: string }>;
          recommended?: Array<{
            title?: string;
            expected_debt_delta?: number | null;
            coverage_gain?: number;
            driver?: string;
            policy?: boolean;
          }>;
          hygiene?: Record<string, number>;
          sources?: { disappeared_count?: number; added_count?: number };
          guardrail?: string;
          actions_needed?: number;
          human_needed?: boolean;
          maintenance_window?: boolean;
          busy?: string | null;
        };
        hygiene?: Record<string, number>;
        principle?: {
          rule?: string;
          observe?: { label?: string; may?: string[] };
          maintain?: { label?: string; may?: string[] };
          govern?: { label?: string; may?: string[]; human_only?: boolean };
        };
        goals?: {
          debt?: { current?: number; target?: number; gap?: number };
          coverage?: { current?: number; target?: number; gap?: number };
        };
        evidence_quality?: {
          score?: number;
          coverage?: number;
          authority?: number;
          freshness?: number;
          consistency?: number;
        };
        simulation?: {
          if_playbook_done?: { debt?: number; debt_now?: number };
          if_top_gaps_linked?: { expected_coverage_gain?: number; sections?: string[] };
        };
        feed?: Array<{ at?: string; kind?: string; title?: string; detail?: string }>;
        attribution?: Array<{ source?: string; detail?: string }>;
        domains?: Array<{
          domain?: string;
          confidence?: number;
          criticality?: string;
        }>;
        impact_debt?: { high_impact?: number; low_impact?: number; total?: number };
        benchmarks?: Array<{ id?: string; name?: string; cases?: number; protected?: boolean }>;
        learning_efficiency?: { accepted_drafts?: number; fitness_delta?: number | null };
        scale?: { nodes?: number; edges?: number; documents?: number; snapshot_ms?: number };
        stability?: {
          improved?: number;
          degraded?: number;
          still_fail?: number;
          total?: number;
        } | null;
        roles?: Record<string, string>;
      };
      feedback: { up: number; down: number; total: number; accept_rate: number | null };
      production: {
        asks_sampled: number;
        frequent: Array<{ question: string; count: number }>;
        weak: Array<{ question: string; decision: string; trust: number }>;
      };
      learning?: {
        paths_tracked: number;
        drafts_open: number;
        drafts: Array<{
          id: string;
          question: string;
          fail_kind?: string;
          origin?: string;
          status?: string;
          source_url?: string | null;
        }>;
      };
      governance?: {
        learning_mode?: string;
        slos?: {
          asks?: number;
          refusal_rate?: number | null;
          answer_rate?: number | null;
          avg_trust?: number | null;
        };
        versions?: Array<{
          id: string;
          label: string;
          status: string;
          created_at: string;
          metrics?: Record<string, unknown>;
          vs_previous?: {
            summary?: string;
            vs_label?: string;
            coverage_delta?: number | null;
            debt_delta?: number | null;
            edges_strengthened?: number;
            edges_weakened?: number;
          } | null;
        }>;
        audit?: Array<{
          id?: string;
          entity_id?: string;
          field?: string;
          old_value?: string;
          new_value?: string;
          reason?: string;
          applied?: number;
          created_at?: string;
        }>;
        trends?: Array<Record<string, unknown>>;
        debt_trend?: {
          current?: number | null;
          prior?: number | null;
          delta?: number | null;
          label?: string;
          prior_at?: string | null;
          current_at?: string | null;
        };
        policies?: Array<{ kind?: string; target?: string; note?: string }>;
      };
    }>(`/api/workspaces/${workspaceId}/knowledge-os`),
  acceptDraft: (workspaceId: string, draftId: string, mustAny: string[] = []) =>
    req<{ ok: boolean }>(
      `/api/workspaces/${workspaceId}/knowledge-os/drafts/${draftId}/accept`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ must_any: mustAny }),
      }
    ),
  rejectDraft: (workspaceId: string, draftId: string) =>
    req<{ ok: boolean }>(
      `/api/workspaces/${workspaceId}/knowledge-os/drafts/${draftId}/reject`,
      { method: "POST" }
    ),
  snapshotGraph: (workspaceId: string) =>
    req<{ id: string; label: string; status: string }>(
      `/api/workspaces/${workspaceId}/knowledge-os/versions`,
      { method: "POST" }
    ),
  rollbackGraph: (workspaceId: string, versionId: string) =>
    req<{ ok: boolean }>(
      `/api/workspaces/${workspaceId}/knowledge-os/versions/${versionId}/rollback`,
      { method: "POST" }
    ),
  promoteGraph: (workspaceId: string, versionId: string) =>
    req<{ ok: boolean }>(
      `/api/workspaces/${workspaceId}/knowledge-os/versions/${versionId}/promote`,
      { method: "POST" }
    ),
  enrichKnowledgeOs: (workspaceId: string) =>
    req<Record<string, unknown>>(`/api/workspaces/${workspaceId}/knowledge-os/enrich`, {
      method: "POST",
    }),
  completeKnowledgeAction: (workspaceId: string, driver: string) =>
    req<{ ok: boolean; driver?: string }>(
      `/api/workspaces/${workspaceId}/knowledge-os/actions/complete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ driver }),
      }
    ),
  reviewKnowledgeSource: (
    workspaceId: string,
    documentId: string,
    owner: string,
    reviewer = ""
  ) =>
    req<{ ok: boolean }>(`/api/workspaces/${workspaceId}/knowledge-os/sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, owner, reviewer }),
    }),
  setKnowledgeGoals: (workspaceId: string, targetDebt: number, targetCoverage: number) =>
    req<{ target_debt: number; target_coverage: number }>(
      `/api/workspaces/${workspaceId}/knowledge-os/goals`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_debt: targetDebt, target_coverage: targetCoverage }),
      }
    ),
  knowledgeOsFleet: () =>
    req<{
      workspaces: Array<{
        agent_id?: string;
        name?: string;
        workspace_id?: string;
        risk?: string;
        debt?: number;
        coverage?: number;
        trust?: number;
        fitness?: number;
        refusal_rate?: number | null;
        sla_ok?: boolean;
        sla_miss?: string[];
      }>;
    }>("/api/knowledge-os/fleet"),
  chatFeedback: (
    workspaceId: string,
    messageId: string,
    rating: "up" | "down",
    note = ""
  ) =>
    req<{ ok: boolean; rating: string }>("/api/chat/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: workspaceId,
        message_id: messageId,
        rating,
        note,
      }),
    }),
  latestCleanStack: (workspaceId: string) =>
    req<{ ok: boolean; report: Record<string, unknown> | null }>(
      `/api/sources/cleanstack/${workspaceId}`
    ),
  dashboard: () => req<StudioDashboard>("/api/studio/dashboard"),
  findingProof: (kind: FindingProofKind | string, limit = 50) =>
    req<FindingProof>(`/api/studio/findings/${encodeURIComponent(kind)}?limit=${limit}`),
  listAgents: () => req<Agent[]>("/api/agents"),
  createAgent: (name: string, description = "") =>
    req<Agent>("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    }),
  getAgent: (agentId: string) => req<Agent>(`/api/agents/${agentId}`),
  runAskReadiness: (agentId: string) =>
    req<AskReadiness>(`/api/agents/${agentId}/ask-readiness`, { method: "POST" }),
  updateAgent: (
    agentId: string,
    patch: {
      name?: string;
      description?: string;
      settings?: Record<string, unknown>;
      allowed_origins?: string;
      published?: boolean;
      disabled?: boolean;
      rotate_embed_key?: boolean;
    }
  ) =>
    req<Agent>(`/api/agents/${agentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  disableAgent: (agentId: string) =>
    req<Agent>(`/api/agents/${agentId}/disable`, { method: "POST" }),
  enableAgent: (agentId: string) =>
    req<Agent>(`/api/agents/${agentId}/enable`, { method: "POST" }),
  deleteAgent: (agentId: string) =>
    req<{ ok: boolean }>(`/api/agents/${agentId}`, { method: "DELETE" }),
  publishAgent: (agentId: string) =>
    req<AgentPublish>(`/api/agents/${agentId}/publish`, { method: "POST" }),
  unpublishAgent: (agentId: string) =>
    req<Agent>(`/api/agents/${agentId}/unpublish`, { method: "POST" }),
  publicAgent: (embedKey: string) =>
    req<{
      name: string;
      greeting: string;
      placeholder: string;
      accent: string;
      show_trust_trail: boolean;
      show_citations: boolean;
      streaming?: boolean;
      published: boolean;
      disabled?: boolean;
      disabled_message?: string | null;
    }>(`/api/public/agents/${embedKey}`),
  publicChat: (embedKey: string, question: string, sessionId?: string) =>
    req<ChatResponse>("/api/public/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        embed_key: embedKey,
        question,
        session_id: sessionId,
      }),
    }),
  /** Published embed SSE stream. Events: status | token | done | error. */
  publicChatStream: async (
    embedKey: string,
    question: string,
    sessionId?: string,
    opts: StreamHandlers = {}
  ): Promise<ChatResponse> => {
    const res = await fetch(`${API}/api/public/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        embed_key: embedKey,
        question,
        session_id: sessionId,
      }),
    });
    return consumeAskSse(res, opts);
  },
};
