import { useMemo, useState } from "react";
import type { TrustForgeCaseMatrix } from "../api/client";

type Props = {
  matrix?: TrustForgeCaseMatrix | null;
  liveCaseId?: string | null;
};

export default function ImprovementMatrix({ matrix, liveCaseId }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "fail" | "improved">("all");

  const rows = useMemo(() => {
    const list = matrix?.rows || [];
    if (filter === "fail") {
      return list.filter((r) => r.trend === "still_fail" || r.trend === "regressed");
    }
    if (filter === "improved") {
      return list.filter((r) => r.trend === "improved");
    }
    return list;
  }, [matrix, filter]);

  if (!matrix || !matrix.rows?.length) {
    return (
      <div className="panel trust-forge-matrix-panel">
        <div className="panel-head">
          <div>
            <h3>Improvement matrix</h3>
            <p>
              Case × generation with question, expected answer, and what the agent returned.
            </p>
          </div>
        </div>
        <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
          {liveCaseId
            ? "Scoring cases now. This grid fills when generation 0 finishes. The knowledge map is unchanged."
            : "No scored cases yet. This grid is the golden-suite results — not whether a graph exists. Open Maps to see the graph."}
        </p>
      </div>
    );
  }

  const gens = matrix.generations || [];
  const summary = matrix.summary || { improved: 0, regressed: 0, still_fail: 0, total: 0 };
  const activeId = openId || liveCaseId || null;
  const active = matrix.rows.find((r) => r.id === activeId) || null;

  return (
    <div className="panel trust-forge-matrix-panel">
      <div className="panel-head">
        <div>
          <h3>Improvement matrix</h3>
          <p>
            Click a case to see the question, expected answer, and what VERA actually returned.
          </p>
        </div>
      </div>

      <div className="trust-forge-matrix-summary">
        <span className="chip ok">{summary.improved} improved</span>
        <span className="chip warn">{summary.regressed} regressed</span>
        <span className="chip">{summary.still_fail} still failing</span>
        <span className="chip muted">{summary.total} cases</span>
        <div className="trust-forge-matrix-filters">
          <button
            type="button"
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            type="button"
            className={filter === "fail" ? "active" : ""}
            onClick={() => setFilter("fail")}
          >
            Failing
          </button>
          <button
            type="button"
            className={filter === "improved" ? "active" : ""}
            onClick={() => setFilter("improved")}
          >
            Improved
          </button>
        </div>
      </div>

      <div className="trust-forge-matrix-grid">
        <div className="trust-forge-matrix-wrap">
          <table className="trust-forge-matrix">
            <thead>
              <tr>
                <th>Case</th>
                <th>Question</th>
                {gens.map((g) => (
                  <th key={g}>G{g}</th>
                ))}
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const q = (row.question || "").trim();
                const shortQ = q.length > 72 ? `${q.slice(0, 72)}…` : q;
                const selected = activeId === row.id;
                const live = liveCaseId === row.id;
                return (
                  <tr
                    key={row.id}
                    className={`trend-${row.trend}${selected ? " selected" : ""}${live ? " live" : ""}`}
                    onClick={() => setOpenId(row.id === openId ? null : row.id)}
                  >
                    <td className="mono case-id">{row.id}</td>
                    <td className="case-q" title={q}>
                      {shortQ || "—"}
                    </td>
                    {row.cells.map((cell, i) => (
                      <td
                        key={i}
                        className={`cell ${cell.status}`}
                        title={cell.fail_kind || cell.status}
                      >
                        {cell.status === "pass" ? "✓" : cell.status === "fail" ? "✗" : "·"}
                      </td>
                    ))}
                    <td className="trend-label">
                      {row.trend === "improved"
                        ? "↑ fixed"
                        : row.trend === "regressed"
                          ? "↓ worse"
                          : row.trend === "still_fail"
                            ? "still fail"
                            : row.trend === "still_pass"
                              ? "ok"
                              : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <aside className="trust-forge-case-detail">
          {active ? (
            <>
              <div className="nav-label">Case detail · {active.id}</div>
              <div className={`trust-forge-case-badge trend-${active.trend}`}>
                {active.trend === "still_fail"
                  ? "Still failing"
                  : active.trend === "improved"
                    ? "Improved"
                    : active.trend === "regressed"
                      ? "Regressed"
                      : active.trend === "still_pass"
                        ? "Passing"
                        : active.trend}
                {active.fail_kind ? ` · ${active.fail_kind}` : ""}
                {active.decision ? ` · decision=${active.decision}` : ""}
              </div>

              <div className="trust-forge-qa">
                <span className="label">Question</span>
                <p>{active.question || "—"}</p>
              </div>
              <div className="trust-forge-qa expected">
                <span className="label">Expected (golden)</span>
                <p>{active.expected_answer || "—"}</p>
              </div>
              <div className={`trust-forge-qa got ${active.got_answer ? "" : "empty"}`}>
                <span className="label">What we got (latest gen)</span>
                <p>{active.got_answer || "No answer preview stored yet — re-run Trust Forge to capture it."}</p>
              </div>
              {(active.must_any || []).length > 0 && (
                <div className="trust-forge-qa">
                  <span className="label">Must include (any)</span>
                  <p className="mono">{(active.must_any || []).join(" · ")}</p>
                </div>
              )}
              {active.kb_quote_hint ? (
                <div className="trust-forge-qa">
                  <span className="label">KB hint</span>
                  <p className="mono">{active.kb_quote_hint}</p>
                </div>
              ) : null}
              {active.source ? (
                <p className="mono muted" style={{ fontSize: "0.72rem", margin: "0.5rem 0 0" }}>
                  source: {active.source}
                </p>
              ) : null}
            </>
          ) : (
            <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
              Select a row to inspect question vs expected vs actual answer.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
