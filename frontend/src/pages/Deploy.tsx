import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError, type StudioDashboard } from "../api/client";
import { useWorkspace } from "../state";

export default function Deploy() {
  const { selectAgent, refreshAgents, agentId } = useWorkspace();
  const [dash, setDash] = useState<StudioDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function load() {
    try {
      setDash(await api.dashboard());
      setErr(null);
    } catch (e) {
      // Fallback: still show agents if studio dashboard route is unreachable
      try {
        const agents = await api.listAgents();
        const origin = window.location.origin;
        setDash({
          plan: "builder",
          plan_label: "Builder",
          api_base: "/api",
          widget_origin: origin,
          totals: {
            agents: agents.length,
            published: agents.filter((a) => a.published).length,
            documents: agents.reduce((n, a) => n + (a.counts?.documents || 0), 0),
            nodes: agents.reduce((n, a) => n + (a.counts?.nodes || 0), 0),
            asks: agents.reduce((n, a) => n + (a.counts?.asks || 0), 0),
          },
          agents: agents.map((a) => ({
            id: a.id,
            name: a.name,
            slug: a.slug,
            description: a.description,
            workspace_id: a.workspace_id,
            published: a.published,
            readiness: a.published
              ? "live"
              : (a.counts?.documents || 0) > 0
                ? "ready"
                : "draft",
            embed_key: a.embed_key,
            counts: a.counts || {},
            endpoints: {
              embed_url: a.published && a.embed_key ? `${origin}/embed/${a.embed_key}` : null,
              widget_snippet:
                a.published && a.embed_key
                  ? `<script src="${origin}/widget.js" data-vera-key="${a.embed_key}" data-vera-origin="${origin}" async></script>`
                  : null,
              public_config_url:
                a.published && a.embed_key ? `/api/public/agents/${a.embed_key}` : null,
              public_chat_url: "/api/public/chat",
            },
            monetize_hint: a.published
              ? "Live — copy embed snippet below."
              : "Publish to unlock embed & public chat for this agent.",
          })),
          pricing: [],
          revenue_model: [],
        });
        setErr(null);
      } catch {
        setErr(formatApiError(e));
      }
    }
  }

  useEffect(() => {
    void load();
  }, [agentId]);

  async function publish(id: string) {
    setBusyId(id);
    try {
      await selectAgent(id);
      await api.publishAgent(id);
      await refreshAgents();
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  async function copy(id: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 1400);
  }

  return (
    <div className="deploy">
      <div className="builder-intro">
        <div className="page-kicker">Deploy & monetize</div>
        <h2 className="section-title">Dedicated endpoints for every agent</h2>
        <p className="section-sub">
          Each published agent gets an embeddable widget and a public chat API bound only to its
          knowledge graph — ready to sell as a site hook, partner integration, or domain pack.
        </p>
      </div>

      {err && <div className="demo-banner">{err}</div>}

      <section className="pricing-grid">
        {(dash?.pricing || []).map((tier) => (
          <div key={tier.id} className={`price-card ${tier.highlighted ? "highlight" : ""}`}>
            <div className="price-card-top">
              <h3>{tier.name}</h3>
              <strong>{tier.price_label}</strong>
            </div>
            <p>{tier.blurb}</p>
            <ul>
              {tier.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            {tier.highlighted && <span className="pill live">Best for selling embeds</span>}
          </div>
        ))}
      </section>

      <section className="deploy-api panel">
        <div className="panel-head">
          <div>
            <h3>Integration contract</h3>
            <p>Stable surfaces your customers (or KFORCE) call</p>
          </div>
        </div>
        <div className="api-table">
          <div>
            <code>GET {dash?.api_base || "/api"}/public/agents/&#123;embed_key&#125;</code>
            <span>Public agent branding + greeting (published only)</span>
          </div>
          <div>
            <code>POST {dash?.api_base || "/api"}/public/chat</code>
            <span>Body: embed_key, question, session_id — answers from that agent’s KB only</span>
          </div>
          <div>
            <code>POST {dash?.api_base || "/api"}/public/chat/stream</code>
            <span>SSE stream for embeds when “Stream answers on embed” is on</span>
          </div>
          <div>
            <code>{dash?.widget_origin || ""}/widget.js</code>
            <span>Drop-in floating chat for any website</span>
          </div>
          <div>
            <code>{dash?.widget_origin || ""}/embed/&#123;embed_key&#125;</code>
            <span>Full-page / iframe chat surface</span>
          </div>
        </div>
      </section>

      <section className="deploy-agents">
        <div className="dash-section-head">
          <div>
            <div className="page-kicker">Published inventory</div>
            <h2>Agent endpoints</h2>
          </div>
          <Link to="/agent" className="text-link">
            Configure agents →
          </Link>
        </div>

        <div className="deploy-list">
          {(dash?.agents || []).map((a) => (
            <article key={a.id} className="deploy-row">
              <div className="deploy-row-main">
                <div className="deploy-row-title">
                  <h3>{a.name}</h3>
                  <span className={`ready-pill ${a.readiness}`}>{a.readiness}</span>
                </div>
                <p>{a.monetize_hint}</p>
                {a.published && a.endpoints.widget_snippet ? (
                  <>
                    <label className="field">
                      <span>Website snippet</span>
                      <textarea readOnly rows={2} value={a.endpoints.widget_snippet} />
                    </label>
                    <div className="cta-row">
                      <button
                        className="btn btn-primary"
                        type="button"
                        onClick={() => void copy(`${a.id}-snip`, a.endpoints.widget_snippet || "")}
                      >
                        {copied === `${a.id}-snip` ? "Copied" : "Copy snippet"}
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => void copy(`${a.id}-url`, a.endpoints.embed_url || "")}
                      >
                        {copied === `${a.id}-url` ? "Copied" : "Copy embed URL"}
                      </button>
                      <a className="btn btn-accent" href={a.endpoints.embed_url || "#"} target="_blank" rel="noreferrer">
                        Open live chat
                      </a>
                    </div>
                  </>
                ) : (
                  <div className="cta-row">
                    <button
                      className="btn btn-primary"
                      type="button"
                      disabled={busyId === a.id || a.readiness === "draft"}
                      onClick={() => void publish(a.id)}
                    >
                      {busyId === a.id ? "Publishing…" : a.readiness === "draft" ? "Connect KB first" : "Publish endpoints"}
                    </button>
                    <Link className="btn btn-ghost" to="/connect" onClick={() => void selectAgent(a.id)}>
                      Connect knowledge
                    </Link>
                  </div>
                )}
              </div>
              <aside className="deploy-row-meta">
                <div>
                  <span>Docs</span>
                  <strong>{a.counts.documents ?? 0}</strong>
                </div>
                <div>
                  <span>Asks</span>
                  <strong>{a.counts.asks ?? 0}</strong>
                </div>
                <div>
                  <span>Public chat</span>
                  <code>{a.endpoints.public_chat_url}</code>
                </div>
                {a.embed_key && (
                  <div>
                    <span>Embed key</span>
                    <code>{a.embed_key.slice(0, 12)}…</code>
                  </div>
                )}
              </aside>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
