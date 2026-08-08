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
  const active = useMemo(
    () => agents.find((a) => a.id === agentId) || agents[0] || null,
    [agents, agentId]
  );
  const live = agents.filter((a) => a.readiness === "live").length;
  const ready = agents.filter((a) => a.readiness === "ready").length;

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
          <div className="bento-table">
            <div className="bento-row bento-row-head">
              <span>Agent</span>
              <span>Status</span>
              <span>Docs</span>
              <span>Nodes</span>
              <span>Asks</span>
              <span>Endpoint</span>
              <span>Actions</span>
            </div>
            {agents.map((a) => (
              <div key={a.id} className={`bento-row ${a.id === agentId ? "is-active" : ""}`}>
                <div className="bento-cell-agent">
                  <EditableText
                    as="strong"
                    value={a.name}
                    onSave={async (name) => {
                      await renameAgent(a.id, name, a.description);
                      await load();
                    }}
                  />
                  <EditableText
                    as="div"
                    className="bento-cell-desc"
                    value={a.description || "Add description…"}
                    onSave={async (description) => {
                      const desc = description === "Add description…" ? "" : description;
                      await renameAgent(a.id, a.name, desc);
                      await load();
                    }}
                  />
                </div>
                <span className={`ready-pill ${a.readiness}`}>{a.readiness}</span>
                <span className="bento-num">{a.counts.documents ?? 0}</span>
                <span className="bento-num">{a.counts.nodes ?? 0}</span>
                <span className="bento-num">{a.counts.asks ?? 0}</span>
                <div className="bento-cell-ep">
                  {a.published && a.endpoints.embed_url ? (
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => void copyText(`ep-${a.id}`, a.endpoints.embed_url || "")}
                    >
                      {copied === `ep-${a.id}` ? "Copied" : "Copy embed"}
                    </button>
                  ) : (
                    <span className="muted">Not published</span>
                  )}
                </div>
                <div className="bento-cell-actions">
                  <button
                    type="button"
                    className={`btn ${a.id === agentId ? "btn-accent" : "btn-ghost"}`}
                    onClick={() => void selectAgent(a.id)}
                  >
                    {a.id === agentId ? "Active" : "Use"}
                  </button>
                  <Link className="btn btn-ghost" to="/map" onClick={() => void selectAgent(a.id)}>
                    Map
                  </Link>
                  <Link className="btn btn-primary" to="/connect" onClick={() => void selectAgent(a.id)}>
                    Connect
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="bento-foot">
        <div>
          <h3>Ship path</h3>
          <p>
            <Link to="/connect">Connect</Link> → <Link to="/map">Map</Link> →{" "}
            <Link to="/agent">Publish</Link> → <Link to="/deploy">Embed</Link>
          </p>
        </div>
        <div>
          <h3>Plan · {dash?.plan_label || "Builder"}</h3>
          <p>
            Upgrade on <Link to="/deploy">Deploy</Link> when you sell site hooks.
          </p>
        </div>
        <div>
          <h3>Public surfaces</h3>
          <p>
            <code>/widget.js</code> · <code>/embed/&#123;key&#125;</code> ·{" "}
            <code>POST /api/public/chat</code>
          </p>
        </div>
      </section>
    </div>
  );
}
