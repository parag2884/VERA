import type { TrustForgeGraphChanges, TrustForgeProgress } from "../api/client";

type Props = {
  graphChanges?: TrustForgeGraphChanges | null;
  nodeCount?: number | null;
  edgeCount?: number | null;
  progress?: TrustForgeProgress | null;
  live?: boolean;
};

export default function GraphChangeViz({
  graphChanges,
  nodeCount,
  edgeCount,
  progress,
  live,
}: Props) {
  const steps = graphChanges?.steps || [];
  const totals = graphChanges?.totals || { aliases_removed: 0, junk_persons_retyped: 0 };
  const healSteps = steps.filter((s) => (s.aliases_removed || 0) + (s.junk_persons_retyped || 0) > 0);
  const phase = progress?.phase || "";
  const healing = live && phase === "healing";
  const evaluating = live && phase === "evaluating";
  const modeClass = healing ? "is-healing" : evaluating ? "is-evaluating" : live ? "is-live" : "";

  return (
    <div className={`panel trust-forge-graph-panel ${modeClass}`}>
      <div className="panel-head">
        <div>
          <h3>Knowledge graph changes</h3>
          <p>
            {healing
              ? "Live: pruning aliases / retyping junk nodes on this pack…"
              : evaluating
                ? "Live: scoring answers against the current graph…"
                : "Hygiene edits on this pack’s graph while Trust Forge climbs."}
          </p>
        </div>
      </div>

      <div className="trust-forge-kg-stage">
        <svg viewBox="0 0 360 170" className="trust-forge-kg-svg">
          <defs>
            <marker id="tf-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="currentColor" opacity="0.35" />
            </marker>
          </defs>
          <circle cx="70" cy="55" r="18" className="kg-node main" />
          <circle cx="150" cy="42" r="12" className={`kg-node${evaluating ? " pulse" : ""}`} />
          <circle cx="205" cy="95" r="14" className={`kg-node${evaluating ? " pulse delay" : ""}`} />
          <circle cx="110" cy="118" r="11" className="kg-node" />
          <circle
            cx="265"
            cy="58"
            r="14"
            className={`kg-node heal${healing ? " active" : ""}`}
          />
          <circle
            cx="305"
            cy="112"
            r="11"
            className={`kg-node prune${healing ? " active" : ""}`}
          />
          <line x1="85" y1="58" x2="138" y2="47" className="kg-edge" markerEnd="url(#tf-arrow)" />
          <line x1="160" y1="50" x2="194" y2="88" className="kg-edge" />
          <line x1="80" y1="70" x2="102" y2="108" className="kg-edge" />
          <line x1="216" y1="90" x2="254" y2="65" className={`kg-edge${healing ? " hot" : ""}`} />
          <line
            x1="275"
            y1="70"
            x2="296"
            y2="102"
            className={`kg-edge prune-edge${healing ? " hot" : ""}`}
          />
          <text x="52" y="59" className="kg-label">entity</text>
          <text x="248" y="54" className="kg-label">retype</text>
          <text x="288" y="138" className="kg-label">alias−</text>
          {live && (
            <text x="16" y="162" className="kg-live-tag">
              {healing ? "HEALING GRAPH" : evaluating ? "READING GRAPH FOR ASK" : "FORGE LIVE"}
            </text>
          )}
        </svg>

        <div className="trust-forge-kg-stats">
          <div>
            <span className="label">Live graph</span>
            <strong className="mono">
              {nodeCount != null && nodeCount > 0
                ? `${nodeCount} nodes · ${edgeCount ?? 0} edges`
                : nodeCount === 0
                  ? "No nodes yet — ingest on Connect, then evaluate"
                  : "—"}
            </strong>
          </div>
          <div>
            <span className="label">Removed this run</span>
            <strong className={`mono ok${healing ? " tick" : ""}`}>
              {totals.aliases_removed} aliases
            </strong>
          </div>
          <div>
            <span className="label">Retyped this run</span>
            <strong className={`mono${healing ? " tick" : ""}`}>
              {totals.junk_persons_retyped} Person→Concept
            </strong>
          </div>
        </div>
      </div>

      {healSteps.length === 0 ? (
        <p className="muted trust-forge-kg-note">
          {evaluating
            ? "Generation 0 scores the current graph. Hygiene (alias prune) starts at generation 1."
            : "Generation 0 is a baseline score only. Later generations may prune aliases; they do not rebuild the graph."}
        </p>
      ) : (
        <ul className="trust-forge-kg-timeline">
          {healSteps.map((s) => (
            <li key={s.gen}>
              <span className="mono">Gen {s.gen}</span>
              <span>
                −{s.aliases_removed} aliases
                {s.junk_persons_retyped
                  ? ` · ${s.junk_persons_retyped} nodes retyped`
                  : ""}
                {s.entity_count != null ? ` · ${s.entity_count} entities now` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
