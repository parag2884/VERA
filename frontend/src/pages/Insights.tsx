import { useEffect, useState, type ReactElement } from "react";
import TrustPyramid from "../components/TrustPyramid";
import CleanStackImpact, { CleanStackReport } from "../components/CleanStackImpact";
import { api } from "../api/client";
import { useWorkspace } from "../state";
import OperateBoard from "../operate/OperateBoard";

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
  const [kos, setKos] = useState<Awaited<ReturnType<typeof api.knowledgeOs>> | null>(null);
  const [debtDriver, setDebtDriver] = useState<string | null>(null);
  const [csReport, setCsReport] = useState<CleanStackReport | null>(null);
  const [pane, setPane] = useState<"act" | "debt" | "quality" | "govern" | "lab">("act");
  const [internals, setInternals] = useState(false);

  useEffect(() => {
    (async () => {
      const status = await api.status();
      setPipelineAgents(status.agents);
      try {
        const ws = workspaceId || (await ensureWorkspace());
        const h = await api.health(ws);
        setScore(h.score);
        setComponents(h.components || {});
        try {
          setKos(await api.knowledgeOs(ws));
        } catch {
          setKos(null);
        }
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
      <div className="page-kicker">Operate</div>
      <h2 className="section-title">Operate</h2>
      <p className="section-sub">
        Outcomes for this agent. The graph is an implementation detail — open Internals only when
        investigating. Care observes and maintains; people govern.
      </p>

      <div className="map-agent-bar panel">
        <div className="map-agent-bar-head">
          <div>
            <div className="nav-label">Agent</div>
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
              <span className="map-agent-chip-meta">
                {a.published ? "live" : a.disabled ? "off" : "draft"}
              </span>
            </button>
          ))}
        </div>
      </div>

      {kos && (
        <div style={{ marginBottom: "1.15rem" }}>
          <OperateBoard
            operate={kos.ops?.operate}
            connectCta={kos.ops?.care?.cta === "connect"}
            onInternals={() => {
              setInternals(true);
              setPane("act");
            }}
          />
        </div>
      )}

      {kos && (
        <details
          className="panel"
          style={{ marginBottom: "1.15rem" }}
          open={internals}
          onToggle={(e) => setInternals((e.target as HTMLDetailsElement).open)}
        >
          <summary className="care-internals-summary">
            Internals — Observe, Maintain, Govern (not the daily view)
          </summary>
          {kos.ops?.principle?.rule ? (
            <p className="muted" style={{ fontSize: "0.82rem", margin: "0.65rem 0 0" }}>
              {kos.ops.principle.rule}
            </p>
          ) : null}
          <div className="panel-head" style={{ marginTop: "0.85rem" }}>
            <div>
              <h3>KnowledgeOps</h3>
              <p>{kos.ops?.explain}</p>
            </div>
          </div>

          <div className="bento-table-wrap kos-scorecard">
            <table className="agent-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Now</th>
                  <th>Before</th>
                  <th>Target</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Risk</td>
                  <td>{kos.proof?.after?.risk ?? kos.debt?.risk?.level ?? "—"}</td>
                  <td>{kos.proof?.before?.risk ?? "—"}</td>
                  <td>Low</td>
                  <td>{kos.debt?.risk?.level === "Low" ? "ok" : "watch"}</td>
                </tr>
                <tr>
                  <td>Debt</td>
                  <td>{kos.debt?.score ?? "—"}%</td>
                  <td>{kos.proof?.before?.debt ?? "—"}%</td>
                  <td>≤ {kos.ops?.goals?.debt?.target ?? 10}%</td>
                  <td>
                    {(kos.ops?.goals?.debt?.gap ?? 0) <= 0 ? "ok" : `gap ${kos.ops?.goals?.debt?.gap}`}
                  </td>
                </tr>
                <tr>
                  <td>Coverage</td>
                  <td>{kos.debt?.coverage_pct ?? kos.coverage.overall_pct}%</td>
                  <td>{kos.proof?.before?.coverage ?? "—"}%</td>
                  <td>≥ {kos.ops?.goals?.coverage?.target ?? 90}%</td>
                  <td>
                    {(kos.ops?.goals?.coverage?.gap ?? 0) <= 0
                      ? "ok"
                      : `gap ${kos.ops?.goals?.coverage?.gap}`}
                  </td>
                </tr>
                <tr>
                  <td>Trust</td>
                  <td>{kos.debt?.trust_pct ?? "—"}%</td>
                  <td>{kos.proof?.before?.trust ?? "—"}%</td>
                  <td>—</td>
                  <td>{kos.ops?.sla?.passing ? "pass" : "miss"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <nav className="kos-panes" aria-label="Insights sections">
            {(
              [
                ["act", "Playbook"],
                ["debt", "Observe"],
                ["quality", "Quality"],
                ["govern", "Govern"],
                ["lab", "Maintain"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`chip ${pane === id ? "active" : ""}`}
                onClick={() => setPane(id)}
              >
                {label}
              </button>
            ))}
          </nav>

          {pane === "act" && (
            <div className="kos-pane">
              <div className="nav-label">Improvement loop</div>
              <p className="muted" style={{ fontSize: "0.82rem" }}>
                Debt {kos.debt?.playbook?.current_debt ?? kos.debt?.score}% → expected{" "}
                {kos.debt?.playbook?.expected_debt_after_fix ?? "—"}% if these are done. Not auto-applied.
              </p>
              <div className="bento-table-wrap">
                <table className="agent-table">
                  <thead>
                    <tr>
                      <th className="idx">#</th>
                      <th>Action</th>
                      <th className="num">Expected debt</th>
                      <th className="actions"> </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(kos.debt?.playbook?.actions || []).map((a) => (
                      <tr key={a.step}>
                        <td className="idx">{a.step}</td>
                        <td className="primary">{a.do}</td>
                        <td className="num">{a.expected_debt_after_this}%</td>
                        <td className="actions">
                          {a.driver ? (
                            <button
                              type="button"
                              className="chip"
                              onClick={() => {
                                void (async () => {
                                  const ws = workspaceId || (await ensureWorkspace());
                                  await api.completeKnowledgeAction(ws, a.driver as string);
                                  setKos(await api.knowledgeOs(ws));
                                })();
                              }}
                            >
                              Mark done
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                    {!kos.debt?.playbook?.actions?.length && (
                      <tr>
                        <td colSpan={4} className="muted">
                          No open actions
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {(kos.learning?.drafts_open || 0) > 0 && (
                <div className="kos-drafts" style={{ marginTop: "1rem" }}>
                  <div className="nav-label">Draft goldens</div>
                  <div className="bento-table-wrap">
                    <table className="agent-table">
                      <thead>
                        <tr>
                          <th>Question</th>
                          <th className="actions"> </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(kos.learning?.drafts || []).map((d) => (
                          <tr key={d.id}>
                            <td className="primary">{d.question}</td>
                            <td className="actions">
                              <button
                                type="button"
                                className="chip"
                                onClick={() => {
                                  void (async () => {
                                    const ws = workspaceId || (await ensureWorkspace());
                                    await api.acceptDraft(ws, d.id);
                                    setKos(await api.knowledgeOs(ws));
                                  })();
                                }}
                              >
                                Accept
                              </button>
                              <button
                                type="button"
                                className="chip"
                                onClick={() => {
                                  void (async () => {
                                    const ws = workspaceId || (await ensureWorkspace());
                                    await api.rejectDraft(ws, d.id);
                                    setKos(await api.knowledgeOs(ws));
                                  })();
                                }}
                              >
                                Reject
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {pane === "debt" && (
            <div className="kos-pane">
              <div className="bento-table-wrap">
                <table className="agent-table">
                  <thead>
                    <tr>
                      <th>Driver</th>
                      <th className="num">Points</th>
                      <th>What to do</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(kos.debt?.drivers || []).map((d) => (
                      <tr
                        key={d.id}
                        className={debtDriver === d.id ? "kos-row-active" : ""}
                        onClick={() => setDebtDriver(debtDriver === d.id ? null : d.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>{d.label}</td>
                        <td className="num">{d.points}%</td>
                        <td>{d.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {debtDriver ? (
                <DebtDrilldown
                  driver={debtDriver}
                  action={kos.debt?.drivers.find((d) => d.id === debtDriver)?.action}
                  items={kos.debt?.drilldown}
                />
              ) : (
                <p className="muted" style={{ fontSize: "0.82rem" }}>
                  Click a driver row to list the edges, topics, or sources behind it.
                </p>
              )}
              <div className="nav-label" style={{ marginTop: "1rem" }}>
                Coverage by section
              </div>
              <div className="bento-table-wrap">
                <table className="agent-table">
                  <thead>
                    <tr>
                      <th>Section</th>
                      <th className="num">Coverage</th>
                      <th>Linked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(kos.coverage.domains || []).map((d) => (
                      <tr key={d.section}>
                        <td>{d.section}</td>
                        <td className="num">{d.coverage_pct}%</td>
                        <td>
                          {d.linked_pages}/{d.pages} pages · {d.entities} entities
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {pane === "quality" && kos.ops && (
            <OpsTables
              ops={kos.ops}
              workspaceId={workspaceId}
              ensureWorkspace={ensureWorkspace}
              onRefresh={async (ws) => setKos(await api.knowledgeOs(ws))}
            />
          )}

          {pane === "govern" && (
            <div className="kos-pane">
              <p className="muted" style={{ fontSize: "0.82rem" }}>
                Learning <strong>{kos.governance?.learning_mode}</strong>
                {kos.governance?.slos?.asks
                  ? ` · ${kos.governance.slos.asks} asks · refuse ${(
                      (kos.governance.slos.refusal_rate || 0) * 100
                    ).toFixed(0)}%`
                  : ""}
                . Rollback restores weights and path stats only.
              </p>
              <div className="bento-table-wrap">
                <table className="agent-table">
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>Diff vs previous</th>
                      <th className="actions"> </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(kos.governance?.versions || []).slice(0, 8).map((v) => (
                      <tr key={v.id}>
                        <td>
                          {v.label}
                          <div className="muted">{v.status}</div>
                        </td>
                        <td>{v.vs_previous?.summary || "—"}</td>
                        <td className="actions">
                          <button
                            type="button"
                            className="chip"
                            onClick={() => {
                              void (async () => {
                                const ws = workspaceId || (await ensureWorkspace());
                                await api.promoteGraph(ws, v.id);
                                setKos(await api.knowledgeOs(ws));
                              })();
                            }}
                          >
                            Promote
                          </button>
                          <button
                            type="button"
                            className="chip"
                            onClick={() => {
                              void (async () => {
                                const ws = workspaceId || (await ensureWorkspace());
                                await api.rollbackGraph(ws, v.id);
                                setKos(await api.knowledgeOs(ws));
                              })();
                            }}
                          >
                            Rollback
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(kos.ops?.feed || []).length ? (
                <>
                  <div className="nav-label" style={{ marginTop: "1rem" }}>
                    Change feed
                  </div>
                  <div className="bento-table-wrap">
                    <table className="agent-table">
                      <thead>
                        <tr>
                          <th>Kind</th>
                          <th>Title</th>
                          <th>Detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(kos.ops?.feed || []).slice(0, 8).map((f, i) => (
                          <tr key={i}>
                            <td>{f.kind}</td>
                            <td>{f.title}</td>
                            <td>{f.detail}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
            </div>
          )}

          {pane === "lab" && (
            <div className="kos-pane">
              {csReport ? (
                <CleanStackImpact
                  report={csReport}
                  impact={{
                    graph_nodes: counts.nodes,
                    evidence_bound_edges: counts.edges,
                    health_score: score ?? undefined,
                    embedded_count: cs.keepers,
                  }}
                />
              ) : (
                <p className="muted">No CleanStack report yet — run Connect with duplicates to see impact.</p>
              )}
              {demoMode && <div className="demo-banner">Demo mode: Mock provider active</div>}
              <TrustPyramid />
              <details style={{ marginTop: "1rem" }}>
                <summary className="muted">Raw health JSON</summary>
                <pre className="mono kos-json">{JSON.stringify(components, null, 2)}</pre>
              </details>
              <div className="agent-list" style={{ marginTop: "0.75rem" }}>
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
          )}
        </details>
      )}
    </div>
  );
}

type DebtDrill = NonNullable<
  NonNullable<Awaited<ReturnType<typeof api.knowledgeOs>>["debt"]>["drilldown"]
>;

type KosOps = NonNullable<Awaited<ReturnType<typeof api.knowledgeOs>>["ops"]>;

function OpsTables({
  ops,
  workspaceId,
  onRefresh,
  ensureWorkspace,
}: {
  ops: KosOps;
  workspaceId: string | null;
  onRefresh: (ws: string) => Promise<void>;
  ensureWorkspace: () => Promise<string>;
}) {
  const eq = ops.evidence_quality;
  return (
    <div className="kos-pane">
      {ops.sla ? (
        <div className="bento-table-wrap">
          <table className="agent-table">
            <thead>
              <tr>
                <th>SLA</th>
                <th>Current</th>
                <th>Target</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(ops.sla.checks || []).map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td>
                  <td>{c.current}</td>
                  <td>{c.target}</td>
                  <td>{c.ok ? "ok" : "miss"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {eq ? (
        <div className="bento-table-wrap" style={{ marginTop: "0.85rem" }}>
          <table className="agent-table">
            <thead>
              <tr>
                <th>Evidence quality</th>
                <th className="num">Score</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Overall</td>
                <td className="num">{eq.score}</td>
              </tr>
              <tr>
                <td>Coverage</td>
                <td className="num">{eq.coverage}</td>
              </tr>
              <tr>
                <td>Authority</td>
                <td className="num">{eq.authority}</td>
              </tr>
              <tr>
                <td>Freshness</td>
                <td className="num">{eq.freshness}</td>
              </tr>
              <tr>
                <td>Consistency</td>
                <td className="num">{eq.consistency}</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}
      {(ops.recommendations || []).length ? (
        <div className="bento-table-wrap" style={{ marginTop: "0.85rem" }}>
          <table className="agent-table">
            <thead>
              <tr>
                <th>Gap</th>
                <th>Suggested</th>
                <th className="num">Coverage +</th>
                <th>Criticality</th>
              </tr>
            </thead>
            <tbody>
              {(ops.recommendations || []).slice(0, 8).map((r) => (
                <tr key={String(r.section)}>
                  <td>{r.kind}</td>
                  <td>{r.suggested}</td>
                  <td className="num">{r.expected_coverage_gain ?? "—"}%</td>
                  <td>{r.criticality}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {(ops.sources || []).length ? (
        <div className="bento-table-wrap" style={{ marginTop: "0.85rem" }}>
          <table className="agent-table">
            <thead>
              <tr>
                <th>Source</th>
                <th className="num">Trust</th>
                <th>Owner</th>
                <th>Age</th>
                <th className="actions"> </th>
              </tr>
            </thead>
            <tbody>
              {(ops.sources || []).slice(0, 10).map((s) => (
                <tr key={s.id}>
                  <td>{s.title}</td>
                  <td className="num">{s.trust_pct}%</td>
                  <td>{s.owner}</td>
                  <td>
                    {s.age_days != null ? `${s.age_days}d` : "—"}
                    {s.freshness === "stale" ? " stale" : ""}
                  </td>
                  <td className="actions">
                    {s.id ? (
                      <button
                        type="button"
                        className="chip"
                        onClick={() => {
                          void (async () => {
                            const ws = workspaceId || (await ensureWorkspace());
                            await api.reviewKnowledgeSource(ws, s.id as string, s.owner || "Knowledge");
                            await onRefresh(ws);
                          })();
                        }}
                      >
                        Mark reviewed
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function DebtDrilldown({
  driver,
  action,
  items,
}: {
  driver: string;
  action?: string;
  items?: DebtDrill;
}) {
  const empty = <li className="muted">Nothing in this bucket yet</li>;
  let rows: ReactElement[] = [];
  if (driver === "weak_edges") {
    rows = (items?.weak_edges || []).map((e, i) => (
      <li key={e.id || i}>
        <strong>
          {e.from} → {e.to}
        </strong>
        {e.success_rate != null
          ? ` · Success rate: ${e.success_rate}%`
          : " · no Ask traffic yet"}
        {e.weight != null ? ` · weight ${e.weight}` : ""}
      </li>
    ));
  } else if (driver === "topics" || driver === "coverage") {
    rows = (items?.topics || []).map((t) => (
      <li key={String(t.section)}>
        <strong>{t.section}</strong>
        {` · coverage ${t.coverage_pct}%`}
        {t.unlinked_pages ? ` · ${t.unlinked_pages} unlinked pages` : ""}
        {t.expected_coverage_gain
          ? ` · expected coverage gain +${t.expected_coverage_gain}%`
          : ""}
      </li>
    ));
  } else if (driver === "trust") {
    rows = (items?.trust || []).map((s, i) => (
      <li key={i}>
        <strong>{s.title}</strong>
        {s.trust_pct != null ? ` · trust ${s.trust_pct}%` : ""}
        {s.reason ? ` · ${s.reason}` : ""}
      </li>
    ));
  } else if (driver === "conflicts") {
    rows = (items?.conflicts || []).map((c, i) => (
      <li key={i}>
        <strong>{c.entity}</strong>
        {c.detail ? ` · ${c.detail}` : ""}
      </li>
    ));
  } else if (driver === "unanswered") {
    rows = (items?.unanswered || []).map((q, i) => (
      <li key={q.id || i}>
        {(q.question || "").slice(0, 140)}
        {q.fail_kind ? ` · ${q.fail_kind}` : ""}
      </li>
    ));
  }
  return (
    <div className="kos-debt-drill">
      {action ? <p className="muted">{action}</p> : null}
      <ul>{rows.length ? rows : empty}</ul>
    </div>
  );
}
