import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  formatApiError,
  type FindingProof,
  type FindingProofKind,
  type StudioDashboard,
} from "../api/client";
import EditableText from "../components/EditableText";
import { useWorkspace } from "../state";

const PROOF_KINDS = new Set<string>([
  "compliance",
  "concepts",
  "relationships",
  "conflicts",
  "unsupported",
]);

export default function Home() {
  const { selectAgent, createAgent, renameAgent, currentAgent, agentId } = useWorkspace();
  const [dash, setDash] = useState<StudioDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [proofKind, setProofKind] = useState<FindingProofKind | null>(null);
  const [proof, setProof] = useState<FindingProof | null>(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [proofErr, setProofErr] = useState<string | null>(null);

  async function load() {
    try {
      setDash(await api.dashboard());
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    }
  }

  useEffect(() => {
    void load();
  }, [currentAgent?.id, currentAgent?.name, currentAgent?.published, currentAgent?.description]);

  async function quickCreate() {
    const name = newName.trim() || "New agent";
    setBusy(true);
    try {
      await createAgent(name, "Dedicated knowledge graph for this domain");
      setNewName("");
      setShowCreate(false);
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyText(id: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 1400);
  }

  async function openProof(kind: string) {
    if (!PROOF_KINDS.has(kind)) return;
    const k = kind as FindingProofKind;
    setProofKind(k);
    setProof(null);
    setProofErr(null);
    setProofBusy(true);
    try {
      const limit = k === "concepts" || k === "relationships" ? 40 : 80;
      setProof(await api.findingProof(k, limit));
    } catch (e) {
      setProofErr(formatApiError(e));
    } finally {
      setProofBusy(false);
    }
  }

  function closeProof() {
    setProofKind(null);
    setProof(null);
    setProofErr(null);
    setProofBusy(false);
  }

  const t = dash?.totals || {};
  const agents = dash?.agents || [];
  const intel = dash?.intelligence;
  const trust = intel?.trust;
  const findings = intel?.findings || [];
  const graph = intel?.graph;
  const active = useMemo(
    () => agents.find((a) => a.id === agentId) || agents[0] || null,
    [agents, agentId]
  );

  const proofAgentLink = useMemo(() => {
    if (!proof?.items?.length) return active;
    const wid = proof.items.find((i) => i.workspace_id)?.workspace_id;
    if (!wid) return active;
    return agents.find((a) => a.workspace_id === wid) || active;
  }, [proof, agents, active]);
  const live = agents.filter((a) => a.readiness === "live").length;
  const ready = agents.filter((a) => a.readiness === "ready").length;
  const trustStatus = trust?.status || "building";
  const trustLabel =
    trustStatus === "trusted" ? "Trusted" : trustStatus === "review" ? "Needs review" : "Building";

  return (
    <div className="bento">
      <header className="bento-top">
        <div className="bento-top-copy">
          <div className="page-kicker">Studio</div>
          <h1>Knowledge operations</h1>
          <p>
            {live} live · {ready} ready · {agents.length} agents. Operate outcomes, not the graph.
          </p>
        </div>
        <div className="bento-kpis">
          <div>
            <span>Live</span>
            <strong>{t.published ?? 0}</strong>
          </div>
          <div>
            <span>Asks</span>
            <strong>{t.asks ?? 0}</strong>
          </div>
          <div>
            <span>Docs</span>
            <strong>{t.documents ?? 0}</strong>
          </div>
        </div>
        <div className="bento-top-actions">
            <Link className="btn btn-accent" to="/insights">
              Operate
            </Link>
          <button className="btn btn-primary" type="button" onClick={() => setShowCreate((v) => !v)}>
            New agent
          </button>
        </div>
      </header>

      {showCreate && (
        <div className="bento-create">
          <input
            autoFocus
            value={newName}
            placeholder="Agent name — PlayReady, Lawyer Firm, Public bot…"
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void quickCreate();
            }}
          />
          <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void quickCreate()}>
            Create
          </button>
        </div>
      )}

      {err && <div className="demo-banner">{err}</div>}

      {active && (
        <section className="bento-spotlight">
          <div className="spotlight-main">
            <div className="spotlight-label">Active agent</div>
            <EditableText
              as="h2"
              value={active.name}
              onSave={async (name) => {
                await renameAgent(active.id, name, active.description);
                await load();
              }}
            />
            <EditableText
              as="div"
              multiline
              maxLength={160}
              className="spotlight-desc"
              value={active.description || "Add what this agent knows…"}
              onSave={async (description) => {
                const desc = description === "Add what this agent knows…" ? "" : description;
                await renameAgent(active.id, active.name, desc);
                await load();
              }}
            />
            <div className="spotlight-meta">
              <span className={`ready-pill ${active.readiness}`}>{active.readiness}</span>
              {active.ask_status && active.ask_status !== "unknown" && (
                <span
                  className={`ready-pill ${active.ask_status === "ready" ? "ready" : "draft"}`}
                  title={
                    (active.ask_failing_patterns || []).length
                      ? `Ask issues: ${active.ask_failing_patterns?.join(", ")}`
                      : "Ask readiness suite"
                  }
                >
                  ask {active.ask_status === "ready" ? "ready" : "needs attention"}
                </span>
              )}
              <span>{active.counts.documents ?? 0} docs</span>
              <span>{active.counts.asks ?? 0} asks</span>
            </div>
          </div>
          <div className="spotlight-path">
            <Link to="/insights" onClick={() => void selectAgent(active.id)}>
              <em>01</em> Operate
            </Link>
            <Link to="/ask" onClick={() => void selectAgent(active.id)}>
              <em>02</em> Ask
            </Link>
            <Link to="/connect" onClick={() => void selectAgent(active.id)}>
              <em>03</em> Connect
            </Link>
            <Link to="/agent" onClick={() => void selectAgent(active.id)}>
              <em>04</em> {active.published ? "Manage" : "Publish"}
            </Link>
          </div>
          <div className="spotlight-hook">
            <div className="spotlight-label">Public hook</div>
            {active.published && active.endpoints.embed_url ? (
              <>
                <code>{active.endpoints.embed_url}</code>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => void copyText(active.id, active.endpoints.embed_url || "")}
                >
                  {copied === active.id ? "Copied" : "Copy embed URL"}
                </button>
              </>
            ) : (
              <>
                <p>{active.monetize_hint}</p>
                <Link className="btn btn-primary" to="/agent" onClick={() => void selectAgent(active.id)}>
                  Publish endpoints
                </Link>
              </>
            )}
          </div>
        </section>
      )}

      <section className="bento-table-wrap">
        <div className="bento-table-head">
          <h2>All agents</h2>
          <span>
          <span>Each agent is a governed knowledge pack</span>
          </span>
        </div>

        {!agents.length ? (
          <div className="dash-empty">
            <p>No agents yet — create PlayReady, Legal, or a Public bot.</p>
            <button className="btn btn-primary" type="button" onClick={() => setShowCreate(true)}>
              New agent
            </button>
          </div>
        ) : (
          <table className="agent-table has-endpoint col-2-status">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Status</th>
                <th className="num">Docs</th>
                <th className="num">Nodes</th>
                <th className="num">Asks</th>
                <th className="endpoint">Endpoint</th>
                <th className="actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => {
                const selected = a.id === agentId;
                return (
                  <tr
                    key={a.id}
                    className={selected ? "is-active" : ""}
                    onClick={() => {
                      if (!selected) void selectAgent(a.id);
                    }}
                  >
                    <td>
                      <div className="bento-cell-agent">
                        <div className="bento-cell-agent-title">
                          <EditableText
                            as="strong"
                            value={a.name}
                            onSave={async (name) => {
                              await renameAgent(a.id, name, a.description);
                              await load();
                            }}
                          />
                          {selected && <span className="studio-chip">In studio</span>}
                        </div>
                        <EditableText
                          as="div"
                          className="bento-cell-desc"
                          value={a.description || ""}
                          placeholder="Add description…"
                          maxLength={120}
                          onSave={async (description) => {
                            await renameAgent(a.id, a.name, description);
                            await load();
                          }}
                        />
                      </div>
                    </td>
                    <td>
                      <div className="bento-cell-status">
                        <span className={`ready-pill ${a.readiness}`}>
                          {a.readiness === "disabled"
                            ? "Disabled"
                            : a.readiness === "live"
                              ? "Live"
                              : a.readiness === "ready"
                                ? "Ready"
                                : a.readiness}
                        </span>
                        {a.ask_status && a.ask_status !== "unknown" && (
                          <span
                            className={`ready-pill ${a.ask_status === "ready" ? "ready" : "draft"}`}
                            title={
                              (a.ask_failing_patterns || []).join(", ") ||
                              "Ask readiness smoke check"
                            }
                          >
                            {a.ask_status === "ready" ? "Ask ok" : "Ask check"}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="num">{a.counts.documents ?? 0}</td>
                    <td className="num">{a.counts.nodes ?? 0}</td>
                    <td className="num">{a.counts.asks ?? 0}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {a.published && a.endpoints.embed_url ? (
                        <button
                          type="button"
                          className="linkish"
                          onClick={() => void copyText(`ep-${a.id}`, a.endpoints.embed_url || "")}
                        >
                          {copied === `ep-${a.id}` ? "Copied" : "Copy embed"}
                        </button>
                      ) : (
                        <span className="muted">Draft</span>
                      )}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <div className="agent-row-actions">
                        <Link
                          className="btn btn-primary"
                          to="/ask"
                          onClick={() => void selectAgent(a.id)}
                        >
                          Ask
                        </Link>
                        <Link
                          className="btn btn-ghost"
                          to="/connect"
                          onClick={() => void selectAgent(a.id)}
                        >
                          Connect
                        </Link>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <details className="panel" style={{ marginBottom: "1.15rem" }}>
        <summary className="care-internals-summary">
          Engineering internals (graph, findings) — not the daily operate view
        </summary>
      <section className="bento-intel" aria-label="Platform internals" style={{ marginTop: "0.85rem" }}>
        <article className={`intel-card intel-trust is-${trustStatus}`}>
          <div className="intel-kicker">Trust Center</div>
          <div className="intel-trust-grid">
            <div>
              <span>Grounded answers</span>
              <strong>{trust?.asks_sampled ? `${trust.grounded_pct}%` : "—"}</strong>
            </div>
            <div>
              <span>Evidence coverage</span>
              <strong>{`${trust?.evidence_coverage_pct ?? 0}%`}</strong>
            </div>
            <button
              type="button"
              className={`intel-metric-btn ${(trust?.conflicts ?? 0) > 0 ? "is-clickable" : ""}`}
              disabled={!trust?.conflicts}
              onClick={() => void openProof("conflicts")}
              title={trust?.conflicts ? "Prove conflicts" : undefined}
            >
              <span>Conflicts</span>
              <strong>{trust?.conflicts ?? 0}</strong>
            </button>
            <button
              type="button"
              className={`intel-metric-btn ${(trust?.unsupported_claims ?? 0) > 0 ? "is-clickable" : ""}`}
              disabled={!trust?.unsupported_claims}
              onClick={() => void openProof("unsupported")}
              title={trust?.unsupported_claims ? "Prove unsupported claims" : undefined}
            >
              <span>Unsupported</span>
              <strong>{trust?.unsupported_claims ?? 0}</strong>
            </button>
          </div>
          <div className={`intel-status is-${trustStatus}`}>
            Status: {trustLabel}
          </div>
        </article>

        <article className="intel-card intel-findings">
          <div className="intel-kicker">AI Findings</div>
          <ul>
            {findings.map((f, i) => {
              const drillable = Boolean(f.drillable && f.id && PROOF_KINDS.has(f.id));
              const body = (
                <>
                  <i aria-hidden>{f.kind === "warn" ? "!" : f.kind === "ok" ? "✓" : "·"}</i>
                  <span>
                    {f.text}
                    {drillable ? <em className="finding-prove">Prove it</em> : null}
                  </span>
                </>
              );
              return (
                <li key={f.id || i} className={`is-${f.kind}${drillable ? " is-drillable" : ""}`}>
                  {drillable ? (
                    <button type="button" className="finding-btn" onClick={() => void openProof(f.id!)}>
                      {body}
                    </button>
                  ) : (
                    body
                  )}
                </li>
              );
            })}
          </ul>
        </article>

        <article className="intel-card intel-graph">
          <div className="intel-kicker">Graph Insights</div>
          <div className="intel-graph-score">
            <strong>{graph?.health_score ? Math.round(graph.health_score) : "—"}</strong>
            <span>Knowledge health</span>
          </div>
          <dl>
            <div>
              <dt>Most connected</dt>
              <dd>{graph?.most_connected || "—"}</dd>
            </div>
            <div>
              <dt>Top agent</dt>
              <dd>
                {graph?.top_agent
                  ? `${graph.top_agent}${graph.top_agent_asks ? ` · ${graph.top_agent_asks} asks` : ""}`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Network</dt>
              <dd>
                {(graph?.concepts ?? 0).toLocaleString()} concepts ·{" "}
                {(graph?.relationships ?? 0).toLocaleString()} links
              </dd>
            </div>
          </dl>
          {active && (
            <Link className="intel-link" to="/map" onClick={() => void selectAgent(active.id)}>
              Open map →
            </Link>
          )}
        </article>
      </section>
      </details>

      {proofKind && (
        <div className="proof-drawer-root" role="presentation" onClick={closeProof}>
          <aside
            className="proof-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={proof?.title || "Finding proof"}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="proof-drawer-head">
              <div>
                <div className="intel-kicker">Prove it</div>
                <h2>{proof?.title || (proofBusy ? "Loading…" : "Finding")}</h2>
                {proof && (
                  <p className="muted">
                    Showing {proof.showing} of {proof.total}
                    {proof.map_hint ? ` · ${proof.map_hint}` : ""}
                  </p>
                )}
              </div>
              <button type="button" className="btn btn-ghost" onClick={closeProof}>
                Close
              </button>
            </header>

            {proofErr && <div className="banner error">{proofErr}</div>}
            {proofBusy && !proof && <p className="muted">Loading evidence…</p>}

            {proof && (
              <ol className="proof-list">
                {proof.items.map((item) => (
                  <li key={item.id}>
                    <div className="proof-item-title">{item.title}</div>
                    {(item.subtitle || item.agent_name) && (
                      <div className="proof-item-meta">
                        {[item.subtitle, item.agent_name].filter(Boolean).join(" · ")}
                      </div>
                    )}
                    {item.detail && <blockquote className="proof-quote">{item.detail}</blockquote>}
                  </li>
                ))}
                {!proof.items.length && (
                  <li className="muted">No rows for this finding yet.</li>
                )}
              </ol>
            )}

            <footer className="proof-drawer-foot">
              {proofAgentLink && (
                <>
                  <Link
                    className="btn btn-primary"
                    to="/map"
                    onClick={() => {
                      void selectAgent(proofAgentLink.id);
                      closeProof();
                    }}
                  >
                    Open Maps
                  </Link>
                  <Link
                    className="btn btn-ghost"
                    to="/ask"
                    onClick={() => {
                      void selectAgent(proofAgentLink.id);
                      closeProof();
                    }}
                  >
                    Ask
                  </Link>
                </>
              )}
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
}
