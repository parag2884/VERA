import { useEffect, useState } from "react";
import TrustPyramid from "../components/TrustPyramid";
import CleanStackImpact, { CleanStackReport } from "../components/CleanStackImpact";
import { api } from "../api/client";
import { useWorkspace } from "../state";

export default function Insights() {
  const {
    workspaceId,
    ensureWorkspace,
    demoMode,
    agents: fleet,
    agentId,
    currentAgent,
    selectAgent,
  } = useWorkspace();
  const [score, setScore] = useState<number | null>(null);
  const [components, setComponents] = useState<Record<string, unknown>>({});
  const [pipelineAgents, setPipelineAgents] = useState<Array<{ id: string; display_name: string }>>([]);
  const [csReport, setCsReport] = useState<CleanStackReport | null>(null);

  useEffect(() => {
    (async () => {
      const status = await api.status();
      setPipelineAgents(status.agents);
      try {
        const ws = workspaceId || (await ensureWorkspace());
        const h = await api.health(ws);
        setScore(h.score);
        setComponents(h.components || {});
        const cs = await api.latestCleanStack(ws);
        if (cs.ok && cs.report) setCsReport(cs.report as CleanStackReport);
        else setCsReport(null);
      } catch {
        setScore(0);
        setCsReport(null);
      }
    })();
  }, [workspaceId, agentId, ensureWorkspace]);

  const counts = (components.counts || {}) as Record<string, number>;
  const cs = (components.cleanstack || {}) as Record<string, number>;

  return (
    <div>
      <div className="page-kicker">Operations</div>
      <h2 className="section-title">Insights</h2>
      <p className="section-sub">
        Health and CleanStack for the selected agent only — switch agents to compare Public bot vs
        PlayReady (or any other pack).
      </p>

      <div className="map-agent-bar panel">
        <div className="map-agent-bar-head">
          <div>
            <div className="nav-label">Insights for agent</div>
            <strong>{currentAgent?.name || "Active agent"}</strong>
          </div>
        </div>
        <div className="map-agent-chips">
          {fleet.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`map-agent-chip ${a.id === agentId ? "active" : ""}`}
              onClick={() => void selectAgent(a.id)}
            >
              <span className="map-agent-chip-name">{a.name}</span>
              <span className="map-agent-chip-meta">{a.counts?.nodes ?? 0} nodes</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: "1.15rem" }}>
        <div className="metric-tile">
          <div className="label">Knowledge Health</div>
          <div className="value">{score ?? "—"}</div>
        </div>
        <div className="metric-tile">
          <div className="label">Graph nodes</div>
          <div className="value">{counts.nodes ?? "—"}</div>
        </div>
        <div className="metric-tile">
          <div className="label">Evidence edges</div>
          <div className="value">{counts.edges ?? "—"}</div>
        </div>
      </div>

      {csReport && (
        <div className="panel" style={{ marginBottom: "1.15rem", padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "1.25rem 1.3rem" }}>
            <CleanStackImpact
              report={csReport}
              impact={{
                graph_nodes: counts.nodes,
                evidence_bound_edges: counts.edges,
                health_score: score ?? undefined,
                embedded_count: cs.keepers,
              }}
            />
          </div>
        </div>
      )}

      {!csReport && (
        <div className="panel" style={{ marginBottom: "1.15rem" }}>
          <div className="panel-head">
            <div>
              <h3>CleanStack impact</h3>
              <p>Run Connect → Load sample KB (or upload duplicates) to see savings parameters.</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <div>
              <h3>Health components</h3>
              <p>Ingest, embed, evidence-bound ratio, connectivity, CleanStack hygiene.</p>
            </div>
          </div>
          {demoMode && (
            <div className="demo-banner" style={{ marginBottom: "0.85rem" }}>
              Demo mode: Mock provider active
            </div>
          )}
          <pre
            className="mono"
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "0.78rem",
              background: "var(--surface-2)",
              padding: "0.9rem",
              borderRadius: "12px",
              border: "1px solid var(--line)",
              margin: 0,
              maxHeight: 360,
              overflow: "auto",
            }}
          >
            {JSON.stringify(components, null, 2)}
          </pre>
        </div>

        <div className="stack">
          <div className="panel panel-soft">
            <div className="panel-head">
              <div>
                <h3>Trust Pyramid</h3>
                <p>Every layer above must be justified by the layer below.</p>
              </div>
            </div>
            <TrustPyramid />
          </div>

          <div className="panel">
            <div className="panel-head">
              <div>
                <h3>Pipeline modules</h3>
                <p>{pipelineAgents.length} ingest/ask stages in the runtime</p>
              </div>
            </div>
            <div className="agent-list">
              {pipelineAgents.map((a) => (
                <div className="agent-step" key={a.id}>
                  <span>{a.display_name}</span>
                  <span className="muted mono" style={{ fontSize: "0.75rem" }}>
                    {a.id}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
