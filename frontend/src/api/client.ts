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
  created_at: string;
  counts: {
    sources?: number;
    documents?: number;
    chunks?: number;
    nodes?: number;
    edges?: number;
    asks?: number;
  };
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
    readiness: "draft" | "ready" | "live";
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
  events?: Array<Record<string, unknown>>;
};

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

export function formatApiError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  if (/502\s*Bad Gateway/i.test(raw) || /<\/html>/i.test(raw)) {
    return "API temporarily unavailable (502). The backend may still be starting — wait a few seconds and retry.";
  }
  if (/504\s*Gateway Time-out/i.test(raw) || /504\s*Gateway Timeout/i.test(raw)) {
    return "Request timed out (504). Try again — large PDFs or Azure calls can take a minute.";
  }
  if (/500\s*Internal Server Error/i.test(raw) || /^Internal Server Error$/i.test(raw.trim())) {
    return "Server busy (often while weaving knowledge). Wait for the current ingest to finish, then retry.";
  }
  if (/409\b/.test(raw) || /already running/i.test(raw)) {
    try {
      const parsed = JSON.parse(raw) as { detail?: string };
      if (parsed?.detail) return parsed.detail;
    } catch {
      /* fall through */
    }
    return "An ingest is already running for this agent. Wait for it to finish, then retry.";
  }
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (parsed?.detail) return parsed.detail;
  } catch {
    /* not JSON */
  }
  // Strip accidental HTML dumps
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
  connectors: () =>
    req<{
      upload: Record<string, unknown>;
      website: Record<string, unknown>;
      sharepoint: { graph_configured: boolean; demo_available: boolean };
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
  graph: (workspaceId: string) => req<GraphData>(`/api/graph?workspace_id=${workspaceId}`),
  health: (workspaceId: string) =>
    req<{ score: number; components: Record<string, unknown>; demo_mode: boolean }>(
      `/api/health/knowledge?workspace_id=${workspaceId}`
    ),
  latestCleanStack: (workspaceId: string) =>
    req<{ ok: boolean; report: Record<string, unknown> | null }>(
      `/api/sources/cleanstack/${workspaceId}`
    ),
  dashboard: () => req<StudioDashboard>("/api/studio/dashboard"),
  listAgents: () => req<Agent[]>("/api/agents"),
  createAgent: (name: string, description = "") =>
    req<Agent>("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    }),
  getAgent: (agentId: string) => req<Agent>(`/api/agents/${agentId}`),
  updateAgent: (
    agentId: string,
    patch: {
      name?: string;
      description?: string;
      settings?: Record<string, unknown>;
      allowed_origins?: string;
      published?: boolean;
      rotate_embed_key?: boolean;
    }
  ) =>
    req<Agent>(`/api/agents/${agentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
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
      published: boolean;
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
};
