export type CleanStackReport = {
  total_files?: number;
  keepers?: number;
  skipped?: number;
  exact_duplicates?: number;
  near_duplicates?: number;
  embeddings_before?: number;
  embeddings_after?: number;
  embeddings_avoided?: number;
  tokens_before?: number;
  tokens_after?: number;
  tokens_avoided?: number;
  reduction_pct?: number;
  estimated_usd_avoided?: number;
  near_dupe_threshold?: number;
  tokenizer?: string;
  token_accounting?: string;
  token_reduction_pct?: number;
  headline?: string;
  why_it_helps?: string[];
  parameters?: Record<string, string>;
  pricing_note?: string;
  decisions?: Array<{
    filename?: string;
    decision?: string;
    reason?: string;
    similarity?: number;
  }>;
  groups?: Array<{ members?: Array<{ filename?: string; decision?: string }> }>;
};

type ImpactExtras = {
  graph_nodes?: number;
  graph_edges?: number;
  evidence_bound_edges?: number;
  embedded_count?: number;
  health_score?: number;
};

const DECISION_LABEL: Record<string, string> = {
  keep: "Keeper — embedded & woven",
  skip_exact: "Exact duplicate — not embedded",
  skip_near: "Near duplicate — not embedded",
};

export default function CleanStackImpact({
  report,
  impact,
}: {
  report: CleanStackReport;
  impact?: ImpactExtras | null;
}) {
  const total = report.total_files ?? 0;
  const keepers = report.keepers ?? 0;
  const avoided = report.embeddings_avoided ?? 0;
  const pct = report.reduction_pct ?? (total ? Math.round((100 * avoided) / total) : 0);
  const decisions = report.decisions || [];

  return (
    <div className="cs-impact">
      <div className="cs-banner">
        <div className="cs-banner-kicker">Show-stopper · CleanStack</div>
        <h3>{report.headline || "Clean before you embed"}</h3>
        <p>
          Fingerprint → exact dedupe → near-dedupe → <strong>embed keepers only</strong>.
          This is the cost + quality gate before the knowledge graph is woven.
        </p>
      </div>

      <div className="cs-metrics">
        <div className="cs-metric">
          <span className="cs-metric-label">Files in</span>
          <strong>{total}</strong>
        </div>
        <div className="cs-metric accent">
          <span className="cs-metric-label">Keepers out</span>
          <strong>{keepers}</strong>
        </div>
        <div className="cs-metric">
          <span className="cs-metric-label">Embeds avoided</span>
          <strong>{avoided}</strong>
        </div>
        <div className="cs-metric">
          <span className="cs-metric-label">Reduction</span>
          <strong>{pct}%</strong>
        </div>
      </div>

      <div className="cs-before-after">
        <div>
          <div className="cs-ba-label">Before CleanStack</div>
          <div className="cs-ba-row">
            <span>Files to embed</span>
            <b>{report.embeddings_before ?? total}</b>
          </div>
          <div className="cs-ba-row">
            <span>Tokens (tiktoken)</span>
            <b>{(report.tokens_before ?? 0).toLocaleString()}</b>
          </div>
        </div>
        <div className="cs-ba-arrow" aria-hidden>
          →
        </div>
        <div>
          <div className="cs-ba-label">After CleanStack</div>
          <div className="cs-ba-row">
            <span>Files embedded</span>
            <b>{report.embeddings_after ?? keepers}</b>
          </div>
          <div className="cs-ba-row">
            <span>Tokens (tiktoken)</span>
            <b>{(report.tokens_after ?? 0).toLocaleString()}</b>
          </div>
        </div>
      </div>
      <p className="muted" style={{ fontSize: "0.78rem", margin: 0 }}>
        Token counts use{" "}
        <strong>{report.tokenizer || "tiktoken cl100k_base"}</strong>
        {report.token_accounting === "tiktoken"
          ? " — measured, not char÷4 guesses."
          : "."}
        {report.token_reduction_pct != null
          ? ` Token reduction: ${report.token_reduction_pct}%.`
          : ""}
      </p>

      <div className="cs-split">
        <div>
          <h4>How it helped this run</h4>
          <ul className="cs-why">
            {(report.why_it_helps || []).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <div className="cs-pill-row">
            <span className="pill">Exact dupes · {report.exact_duplicates ?? 0}</span>
            <span className="pill">
              Near dupes · {report.near_duplicates ?? 0}
              {report.near_dupe_threshold != null
                ? ` (≥ ${report.near_dupe_threshold})`
                : ""}
            </span>
            <span className="pill">
              Tokens avoided · {(report.tokens_avoided ?? 0).toLocaleString()}
            </span>
            {report.estimated_usd_avoided != null && (
              <span className="pill live">
                ${Number(report.estimated_usd_avoided).toFixed(4)} at configured $/1M
              </span>
            )}
          </div>
        </div>
        <div>
          <h4>Parameters (auditable)</h4>
          <dl className="cs-params">
            {Object.entries(report.parameters || {}).map(([k, v]) => (
              <div key={k}>
                <dt>{k.replace(/_/g, " ")}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {impact && (
        <div className="cs-downstream">
          <h4>What happened next (show-stoppers)</h4>
          <div className="cs-pill-row">
            <span className="pill">Graph nodes · {impact.graph_nodes ?? "—"}</span>
            <span className="pill">Edges · {impact.graph_edges ?? "—"}</span>
            <span className="pill live">
              Evidence-bound · {impact.evidence_bound_edges ?? "—"}
            </span>
            <span className="pill">Embedded · {impact.embedded_count ?? "—"}</span>
            <span className="pill">Health · {impact.health_score ?? "—"}</span>
          </div>
          <p className="muted" style={{ fontSize: "0.82rem", margin: "0.55rem 0 0" }}>
            No evidence-bearing edge = no answer-bearing edge. CleanStack keeps noise out so
            Trust Trails stay provable.
          </p>
        </div>
      )}

      {decisions.length > 0 && (
        <div className="cs-decisions">
          <h4>Per-file decisions</h4>
          <div className="cs-decision-list">
            {decisions.map((d, i) => (
              <div
                key={`${d.filename}-${i}`}
                className={`cs-decision ${d.decision === "keep" ? "keep" : "skip"}`}
              >
                <div>
                  <strong>{d.filename || "file"}</strong>
                  <div className="muted" style={{ fontSize: "0.78rem" }}>
                    {DECISION_LABEL[d.decision || ""] || d.decision}
                    {d.similarity != null ? ` · sim ${d.similarity.toFixed(2)}` : ""}
                  </div>
                </div>
                <span className="cs-decision-tag">{d.decision}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {report.pricing_note && (
        <p className="muted" style={{ fontSize: "0.78rem", marginTop: "0.85rem" }}>
          {report.pricing_note}
        </p>
      )}
    </div>
  );
}
