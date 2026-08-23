import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useWorkspace } from "../state";
import TrustForgePanel from "../trust_forge/TrustForgePanel";
import ImprovementMatrix from "../trust_forge/ImprovementMatrix";
import GraphChangeViz from "../trust_forge/GraphChangeViz";
import type { TrustForgeRun } from "../api/client";

export default function TrustForgePage() {
  const {
    workspaceId,
    agents: fleet,
    agentId,
    currentAgent,
    selectAgent,
    ensureWorkspace,
  } = useWorkspace();
  const [run, setRun] = useState<TrustForgeRun | null>(null);
  const [nodeCount, setNodeCount] = useState<number | null>(null);
  const [edgeCount, setEdgeCount] = useState<number | null>(null);

  useEffect(() => {
    void ensureWorkspace().catch(() => undefined);
  }, [ensureWorkspace]);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    (async () => {
      try {
        const h = await api.health(workspaceId);
        const counts = (h.components?.counts || {}) as Record<string, number>;
        if (!cancelled) {
          setNodeCount(counts.nodes ?? null);
          setEdgeCount(counts.edges ?? null);
        }
      } catch {
        if (!cancelled) {
          setNodeCount(null);
          setEdgeCount(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, agentId, run?.generation, run?.status]);

  return (
    <div className="trust-forge-page">
      <div className="page-kicker">Operate</div>
      <h2 className="section-title">Evaluate</h2>
      <p className="section-sub">
        Score this agent against a locked golden suite. Heal adjusts the existing graph (weights,
        aliases, pins) — it does not recrawl or rebuild the knowledge base.
      </p>

      <div className="map-agent-bar panel">
        <div className="map-agent-bar-head">
          <div>
            <div className="nav-label">Workspace</div>
            <strong>{currentAgent?.name || "Select an agent"}</strong>
          </div>
          <Link className="btn" to="/map" style={{ textDecoration: "none" }}>
            Open knowledge map
          </Link>
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

      <div className="trust-forge-layout">
        <div className="trust-forge-layout-main">
          <TrustForgePanel
            workspaceId={workspaceId}
            agentId={agentId}
            agentName={currentAgent?.name}
            layout="page"
            onRunChange={setRun}
          />
        </div>
        <div className="trust-forge-layout-side">
          <GraphChangeViz
            graphChanges={run?.graph_changes}
            nodeCount={nodeCount}
            edgeCount={edgeCount}
            progress={run?.progress}
            live={run?.status === "queued" || run?.status === "running"}
          />
        </div>
      </div>

      <ImprovementMatrix
        matrix={run?.case_matrix}
        liveCaseId={run?.progress?.case_id || null}
      />
    </div>
  );
}
