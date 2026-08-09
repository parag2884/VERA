import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError, type StudioDashboard } from "../api/client";
import EditableText from "../components/EditableText";
import { useWorkspace } from "../state";

export default function Home() {
  const { selectAgent, createAgent, renameAgent, currentAgent, agentId } = useWorkspace();
  const [dash, setDash] = useState<StudioDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);

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
          <h1>Agent fleet</h1>
          <p>
            {agents.length} agents · {ready} ready · {live} live — click a name to rename
          </p>
        </div>
        <div className="bento-kpis">
          <div>
            <span>Agents</span>
            <strong>{t.agents ?? 0}</strong>
          </div>
          <div>
            <span>Live</span>
            <strong>{t.published ?? 0}</strong>
          </div>
          <div>
            <span>Docs</span>
            <strong>{t.documents ?? 0}</strong>
          </div>
          <div>
            <span>Nodes</span>
            <strong>{t.nodes ?? 0}</strong>
          </div>
          <div>
            <span>Asks</span>
            <strong>{t.asks ?? 0}</strong>
          </div>
        </div>
        <div className="bento-top-actions">
          <Link className="btn btn-accent" to="/deploy">
            Deploy
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
            <div className="spotlight-label">Active · ship next</div>
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
              <span>{active.counts.nodes ?? 0} nodes</span>
              <span>{active.counts.chunks ?? 0} chunks</span>
              <span>{active.counts.asks ?? 0} asks</span>
            </div>
          </div>
          <div className="spotlight-path">
            <Link to="/connect" onClick={() => void selectAgent(active.id)}>
              <em>01</em> Connect KB
            </Link>
            <Link to="/map" onClick={() => void selectAgent(active.id)}>
              <em>02</em> View map
            </Link>
            <Link to="/ask" onClick={() => void selectAgent(active.id)}>
              <em>03</em> Ask
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
            Each row = isolated graph + vector store
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
          <table className="agent-table has-endpoint">
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

      <section className="bento-intel" aria-label="VERA platform intelligence">
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
            <div>
              <span>Conflicts</span>
              <strong>{trust?.conflicts ?? 0}</strong>
            </div>
            <div>
              <span>Unsupported</span>
              <strong>{trust?.unsupported_claims ?? 0}</strong>
            </div>
          </div>
          <div className={`intel-status is-${trustStatus}`}>
            Status: {trustLabel}
          </div>
        </article>

        <article className="intel-card intel-findings">
          <div className="intel-kicker">AI Findings</div>
          <ul>
            {findings.map((f, i) => (
              <li key={i} className={`is-${f.kind}`}>
                <i aria-hidden>{f.kind === "warn" ? "!" : f.kind === "ok" ? "✓" : "·"}</i>
                <span>{f.text}</span>
              </li>
            ))}
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
    </div>
  );
}
