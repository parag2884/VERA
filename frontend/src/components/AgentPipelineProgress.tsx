type Event = {
  agent_id?: string;
  stage?: string;
  message?: string;
  progress?: number;
  level?: string;
};

const INGEST_STAGES = [
  { id: "connect", label: "Connect", short: "Connect" },
  { id: "fingerprint", label: "Fingerprint", short: "Print" },
  { id: "parse", label: "Parse", short: "Parse" },
  { id: "cleanstack", label: "CleanStack", short: "Clean" },
  { id: "chunk", label: "Chunk", short: "Chunk" },
  { id: "graph_weaver", label: "Graph Weaver", short: "Weave" },
  { id: "embed", label: "Embed keepers", short: "Embed" },
  { id: "index_health", label: "Health score", short: "Health" },
];

export default function AgentPipelineProgress({
  events = [],
  progress = 0,
  status,
  statusText,
  compact = false,
}: {
  events?: Event[];
  progress?: number;
  status?: string;
  statusText?: string | null;
  compact?: boolean;
}) {
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
  const pct = Math.round(progress * 100);

  if (compact) {
    return (
      <div className="pipe-compact">
        <div className="pipe-compact-meta">
          <span>
            {pct}%{status ? ` · ${status}` : ""}
          </span>
          {(statusText || lastMsg) && <span className="pipe-compact-msg">{statusText || lastMsg}</span>}
        </div>
        <div className="pipe-compact-bar" aria-hidden>
          <i style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
        </div>
        <div className="pipe-compact-steps" role="list">
          {INGEST_STAGES.map((s) => {
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
      <div className="muted" style={{ marginBottom: "0.45rem", fontSize: "0.85rem" }}>
        Progress · {pct}%
        {status ? ` · ${status}` : ""}
      </div>
      {(statusText || lastMsg) && (
        <div style={{ fontSize: "0.82rem", marginBottom: "0.65rem", color: "var(--navy)" }}>
          {statusText || lastMsg}
        </div>
      )}
      {INGEST_STAGES.map((s) => {
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
