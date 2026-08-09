type Event = {
  agent_id?: string;
  stage?: string;
  message?: string;
  progress?: number;
  level?: string;
  pages?: number;
  max_pages?: number;
};

const BASE_STAGES = [
  { id: "connect", label: "Connect", short: "Connect" },
  { id: "fingerprint", label: "Fingerprint", short: "Print" },
  { id: "parse", label: "Parse", short: "Parse" },
  { id: "cleanstack", label: "CleanStack", short: "Clean" },
  { id: "chunk", label: "Chunk", short: "Chunk" },
  { id: "graph_weaver", label: "Graph Weaver", short: "Weave" },
  { id: "embed", label: "Embed keepers", short: "Embed" },
  { id: "index_health", label: "Health score", short: "Health" },
];

const CRAWL_STAGE = { id: "crawl", label: "Crawl site", short: "Crawl" };

export default function AgentPipelineProgress({
  events = [],
  progress = 0,
  status,
  statusText,
  compact = false,
  agentName,
  jobType,
}: {
  events?: Event[];
  progress?: number;
  status?: string;
  statusText?: string | null;
  compact?: boolean;
  /** Active agent — shown so multi-agent studios know which KB is updating */
  agentName?: string | null;
  jobType?: string | null;
}) {
  const hasCrawl =
    jobType === "ingest_url" ||
    events.some((e) => e.agent_id === "crawl" || String(e.stage || "").includes("crawl"));
  const stages = hasCrawl ? [CRAWL_STAGE, ...BASE_STAGES] : BASE_STAGES;

  const failed =
    status === "failed" ||
    events.some((e) => String(e.stage || "").includes(".failed") || e.level === "error");
  const doneAgents = new Set(
    events
      .filter((e) => /\.done$/i.test(String(e.stage || "")) || String(e.stage || "").includes(".done"))
      .map((e) => e.agent_id)
      .filter(Boolean) as string[]
  );
  const stageDone = new Set(
    events
      .filter((e) => /\.done$/i.test(String(e.stage || "")))
      .map((e) => {
        const m = String(e.stage).match(/stage\.([^.]+)\.done/);
        return m?.[1] || e.agent_id;
      })
      .filter(Boolean) as string[]
  );

  let active: string | undefined;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    const st = String(e.stage || "");
    if (st.includes(".start") || st === "weaver.chunk") {
      const m = st.match(/stage\.([^.]+)\.start/);
      active = m?.[1] || e.agent_id;
      break;
    }
  }
  if (active === "graph_weaver" || active === "graph weaver") active = "graph_weaver";
  if (
    active === "graph_weaver" ||
    events.some((e) => e.agent_id === "graph_weaver" && e.stage === "weaver.chunk")
  ) {
    if (!stageDone.has("graph_weaver") && !doneAgents.has("graph_weaver")) active = "graph_weaver";
  }

  const lastMsg = [...events].reverse().find((e) => e.message)?.message;
  const crawlEv = [...events].reverse().find((e) => e.agent_id === "crawl");
  const pct = Math.round(Math.min(100, Math.max(0, progress * 100)));
  const scope = agentName ? `${agentName}` : null;
  const headline = scope
    ? `${scope} · ${pct}%${status ? ` · ${status}` : ""}`
    : `Progress · ${pct}%${status ? ` · ${status}` : ""}`;
  const detail = statusText || lastMsg;
  const crawlHint =
    crawlEv && typeof crawlEv.pages === "number" && typeof crawlEv.max_pages === "number"
      ? `${crawlEv.pages}/${crawlEv.max_pages} pages`
      : null;

  if (compact) {
    return (
      <div className="pipe-compact">
        <div className="pipe-compact-meta">
          <span>{headline}</span>
          {(detail || crawlHint) && (
            <span className="pipe-compact-msg">{detail || crawlHint}</span>
          )}
        </div>
        <div className="pipe-compact-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ width: `${pct}%` }} />
        </div>
        <div className="pipe-compact-steps" role="list">
          {stages.map((s) => {
            const done = stageDone.has(s.id) || doneAgents.has(s.id);
            const isActive = !failed && !done && active === s.id;
            return (
              <span
                key={s.id}
                role="listitem"
                title={s.label}
                className={`pipe-chip ${done ? "done" : ""} ${isActive ? "active" : ""} ${
                  s.id === "cleanstack" ? "gate" : ""
                }`}
              >
                {s.short}
              </span>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="agent-list">
      {scope && (
        <div className="pipe-agent-scope" title="Ingest updates this agent only">
          Updating <strong>{scope}</strong>
          <span className="muted"> — other agents stay isolated</span>
        </div>
      )}
      <div className="pipe-progress-head">
        <div className="muted" style={{ fontSize: "0.85rem" }}>
          {headline}
          {crawlHint ? ` · ${crawlHint}` : ""}
        </div>
        <div
          className="pipe-progress-bar"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Ingest progress"
        >
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
      {detail && (
        <div className="pipe-progress-msg" title={detail}>
          {detail}
        </div>
      )}
      {stages.map((s) => {
        const done = stageDone.has(s.id) || doneAgents.has(s.id);
        const isActive = !failed && !done && active === s.id;
        return (
          <div
            key={s.id}
            className={`agent-step ${done ? "done" : ""} ${isActive ? "active" : ""} ${
              s.id === "cleanstack" ? "gate" : ""
            } ${failed && isActive ? "failed" : ""}`}
          >
            <span>{s.label}</span>
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              {done ? "done" : failed && active === s.id ? "failed" : isActive ? "running" : "queued"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
