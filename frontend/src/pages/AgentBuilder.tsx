import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  ACCENT_OPTIONS,
  TONE_OPTIONS,
  VERBOSITY_OPTIONS,
} from "../agentSettings";
import ChatConsole from "../components/ChatConsole";
import EditableText from "../components/EditableText";
import KnowledgeConnectPanel from "../components/KnowledgeConnectPanel";
import { formatApiError } from "../api/client";
import { defaultSamplesForAgent, parseSampleLines } from "../sampleQuestions";
import { useWorkspace } from "../state";

type BuilderTab = "setup" | "knowledge" | "voice" | "publish";

const TABS: { id: BuilderTab; label: string; hint: string }[] = [
  { id: "setup", label: "Setup", hint: "Name & greeting" },
  { id: "knowledge", label: "Knowledge", hint: "Files, URL, SharePoint" },
  { id: "voice", label: "Voice", hint: "Tone & trust display" },
  { id: "publish", label: "Publish", hint: "Embed & go live" },
];

export default function AgentBuilder() {
  const {
    agents,
    currentAgent,
    agentId,
    selectAgent,
    createAgent,
    renameAgent,
    refreshAgents,
    agentSettings: s,
    updateAgentSettings,
    resetAgentSettings,
    publishInfo,
    publishAgent,
    unpublishAgent,
  } = useWorkspace();

  const [tab, setTab] = useState<BuilderTab>("setup");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [descDraft, setDescDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDescDraft(currentAgent?.description || "");
  }, [currentAgent?.id, currentAgent?.description]);

  async function onCreate() {
    if (!newName.trim() || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await createAgent(newName.trim(), newDesc.trim());
      setNewName("");
      setNewDesc("");
      setCreating(false);
      setTab("knowledge");
      setMsg("Agent created — attach knowledge next.");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function onPublish() {
    setBusy(true);
    setMsg(null);
    try {
      await publishAgent();
      setMsg("Published — copy the embed snippet for your site.");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUnpublish() {
    setBusy(true);
    try {
      await unpublishAgent();
      setMsg("Unpublished — embed endpoint disabled.");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function copySnippet() {
    if (!publishInfo?.snippet) return;
    await navigator.clipboard.writeText(publishInfo.snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  const docs = currentAgent?.counts?.documents ?? 0;
  const nodes = currentAgent?.counts?.nodes ?? 0;
  const chunks = currentAgent?.counts?.chunks ?? 0;
  const domainProfile = (currentAgent?.settings?.domainProfile || null) as
    | { label?: string; entityTypes?: string[]; focus?: string; confidence?: number }
    | null;

  return (
    <div className="builder">
      <header className="builder-hero">
        <div>
          <div className="page-kicker">Agents</div>
          <h2 className="section-title">Build an evidence-bound agent</h2>
          <p className="section-sub">
            Pick an agent, attach knowledge, set voice, then publish. Each agent owns its own graph.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            setCreating((v) => !v);
            setMsg(null);
          }}
        >
          {creating ? "Cancel" : "New agent"}
        </button>
      </header>

      {creating && (
        <section className="builder-create panel">
          <div className="builder-create-row">
            <label className="field">
              <span>Name</span>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. PlayReady Agent"
                autoFocus
              />
            </label>
            <label className="field">
              <span>Description</span>
              <input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="What knowledge does this agent own?"
              />
            </label>
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy || !newName.trim()}
              onClick={() => void onCreate()}
            >
              Create
            </button>
          </div>
        </section>
      )}

      <section className="builder-fleet" aria-label="Your agents">
        <div className="builder-fleet-scroll">
          {agents.map((a) => {
            const active = a.id === agentId;
            return (
              <button
                key={a.id}
                type="button"
                className={`fleet-chip ${active ? "active" : ""}`}
                onClick={() => {
                  void selectAgent(a.id);
                  setMsg(null);
                }}
              >
                <span className="fleet-chip-mark" aria-hidden>
                  {a.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="fleet-chip-body">
                  <strong>{a.name}</strong>
                  <em>
                    {a.published ? "Live" : "Draft"} · {a.counts?.documents ?? 0} docs
                  </em>
                </span>
              </button>
            );
          })}
          {agents.length === 0 && (
            <p className="muted" style={{ margin: "0.35rem 0" }}>
              No agents yet — create one to start.
            </p>
          )}
        </div>
      </section>

      {currentAgent && (
        <div className="builder-workspace">
          <div className="builder-main">
            <div className="builder-agent-bar">
              <div className="builder-agent-title">
                <EditableText
                  as="h3"
                  value={currentAgent.name}
                  onSave={(name) => renameAgent(currentAgent.id, name, currentAgent.description)}
                />
                {currentAgent.published ? (
                  <span className="pill live">Live</span>
                ) : (
                  <span className="pill">Draft</span>
                )}
                {domainProfile?.label ? (
                  <span className="pill" title={domainProfile.focus || "Inferred from uploaded knowledge"}>
                    Domain · {domainProfile.label}
                  </span>
                ) : null}
              </div>
              <div className="kb-stat-strip builder-agent-stats">
                <div className="kb-stat">
                  <b>{docs}</b>
                  <span>docs</span>
                </div>
                <div className="kb-stat">
                  <b>{nodes}</b>
                  <span>nodes</span>
                </div>
                <div className="kb-stat">
                  <b>{chunks}</b>
                  <span>chunks</span>
                </div>
              </div>
            </div>

            <nav className="builder-tabs" aria-label="Agent editor">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`builder-tab ${tab === t.id ? "active" : ""}`}
                  onClick={() => setTab(t.id)}
                >
                  <strong>{t.label}</strong>
                  <span>{t.hint}</span>
                </button>
              ))}
            </nav>

            <div className="builder-panel">
              {tab === "setup" && (
                <div className="builder-pane">
                  <p className="builder-pane-lead">
                    How this agent introduces itself in chat and on embeds.
                  </p>
                  <label className="field">
                    <span>Display name</span>
                    <input
                      value={s.agentName}
                      onChange={(e) => updateAgentSettings({ agentName: e.target.value })}
                      onBlur={() => {
                        if (currentAgent && s.agentName.trim()) {
                          void renameAgent(
                            currentAgent.id,
                            s.agentName.trim(),
                            currentAgent.description
                          );
                        }
                      }}
                      maxLength={40}
                    />
                  </label>
                  <label className="field">
                    <span>Description</span>
                    <input
                      value={descDraft}
                      onChange={(e) => setDescDraft(e.target.value)}
                      onBlur={() => {
                        if (descDraft !== (currentAgent.description || "")) {
                          void renameAgent(currentAgent.id, currentAgent.name, descDraft);
                        }
                      }}
                      placeholder="What this agent knows"
                      maxLength={160}
                    />
                  </label>
                  <label className="field">
                    <span>Greeting</span>
                    <textarea
                      rows={3}
                      value={s.greeting}
                      onChange={(e) => updateAgentSettings({ greeting: e.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>Input placeholder</span>
                    <input
                      value={s.placeholder}
                      onChange={(e) => updateAgentSettings({ placeholder: e.target.value })}
                    />
                  </label>
                  <div className="builder-pane-foot">
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => setTab("knowledge")}
                    >
                      Next · Knowledge
                    </button>
                  </div>
                </div>
              )}

              {tab === "knowledge" && (
                <div className="builder-pane">
                  <div className="kb-section-head">
                    <p className="builder-pane-lead" style={{ margin: 0 }}>
                      Sources feed only this agent’s isolated graph.
                    </p>
                    <div className="cta-row kb-section-actions">
                      <Link className="btn btn-ghost" to="/map">
                        Map
                      </Link>
                      <Link className="btn btn-ghost" to="/ask">
                        Ask
                      </Link>
                    </div>
                  </div>
                  <KnowledgeConnectPanel
                    compact
                    onIngestComplete={() => void refreshAgents()}
                  />
                  <div className="builder-pane-foot">
                    <button type="button" className="btn btn-ghost" onClick={() => setTab("setup")}>
                      Back
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => setTab("voice")}
                    >
                      Next · Voice
                    </button>
                  </div>
                </div>
              )}

              {tab === "voice" && (
                <div className="builder-pane">
                  <p className="builder-pane-lead">Answer style and what proof the UI shows.</p>

                  <div className="builder-block">
                    <h4>Tone</h4>
                    <div className="tone-grid tone-grid-compact">
                      {TONE_OPTIONS.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          className={`tone-card ${s.tone === t.id ? "active" : ""}`}
                          onClick={() => updateAgentSettings({ tone: t.id })}
                        >
                          <strong>{t.label}</strong>
                          <span>{t.hint}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="builder-voice-row">
                    <div className="builder-block">
                      <h4>Verbosity</h4>
                      <div className="seg">
                        {VERBOSITY_OPTIONS.map((v) => (
                          <button
                            key={v.id}
                            type="button"
                            className={s.verbosity === v.id ? "active" : ""}
                            onClick={() => updateAgentSettings({ verbosity: v.id })}
                          >
                            {v.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="builder-block">
                      <h4>Accent</h4>
                      <div className="accent-row">
                        {ACCENT_OPTIONS.map((a) => (
                          <button
                            key={a.id}
                            type="button"
                            className={`accent-swatch ${s.accent === a.id ? "active" : ""}`}
                            style={{ "--swatch": a.swatch } as CSSProperties}
                            onClick={() => updateAgentSettings({ accent: a.id })}
                            title={a.label}
                          >
                            <span />
                            {a.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="builder-block">
                    <h4>Suggested questions</h4>
                    <label className="field">
                      <span>One per line · shown as Try chips</span>
                      <textarea
                        rows={3}
                        value={(s.sampleQuestions || []).join("\n")}
                        placeholder={defaultSamplesForAgent(s.agentName, domainProfile).join("\n")}
                        onChange={(e) =>
                          updateAgentSettings({ sampleQuestions: parseSampleLines(e.target.value) })
                        }
                      />
                    </label>
                    <button
                      className="btn btn-ghost"
                      type="button"
                      onClick={() =>
                        updateAgentSettings({
                          sampleQuestions: defaultSamplesForAgent(s.agentName, domainProfile),
                        })
                      }
                    >
                      Reset to domain defaults
                    </button>
                  </div>

                  <div className="builder-block">
                    <h4>Trust display</h4>
                    <div className="trust-toggles">
                      <label className="toggle-row">
                        <input
                          type="checkbox"
                          checked={s.showTrustTrail}
                          onChange={(e) =>
                            updateAgentSettings({ showTrustTrail: e.target.checked })
                          }
                        />
                        <span>Trust Trail</span>
                      </label>
                      <label className="toggle-row">
                        <input
                          type="checkbox"
                          checked={s.showCitations}
                          onChange={(e) =>
                            updateAgentSettings({ showCitations: e.target.checked })
                          }
                        />
                        <span>Citations</span>
                      </label>
                      <label className="toggle-row">
                        <input
                          type="checkbox"
                          checked={s.showTrustScore}
                          onChange={(e) =>
                            updateAgentSettings({ showTrustScore: e.target.checked })
                          }
                        />
                        <span>Scorecard</span>
                      </label>
                      <label className="toggle-row">
                        <input
                          type="checkbox"
                          checked={s.embedStreaming !== false}
                          onChange={(e) =>
                            updateAgentSettings({ embedStreaming: e.target.checked })
                          }
                        />
                        <span>Stream answers on embed</span>
                      </label>
                    </div>
                    <p className="muted" style={{ fontSize: "0.78rem", marginTop: "0.45rem" }}>
                      When on, customer embed/widget reveals answer text as it becomes available.
                      Turn off to deliver the full reply at once.
                    </p>
                  </div>

                  <div className="builder-pane-foot">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => setTab("knowledge")}
                    >
                      Back
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={resetAgentSettings}
                    >
                      Reset defaults
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => setTab("publish")}
                    >
                      Next · Publish
                    </button>
                  </div>
                </div>
              )}

              {tab === "publish" && (
                <div className="builder-pane">
                  <p className="builder-pane-lead">
                    Embed answers only from <strong>{currentAgent.name}</strong>’s knowledge graph.
                  </p>
                  <div className="cta-row">
                    {currentAgent.published ? (
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => void onUnpublish()}
                      >
                        Unpublish
                      </button>
                    ) : (
                      <button
                        className="btn btn-primary"
                        type="button"
                        disabled={busy}
                        onClick={() => void onPublish()}
                      >
                        Publish agent
                      </button>
                    )}
                    {publishInfo && (
                      <button
                        className="btn btn-accent"
                        type="button"
                        onClick={() => void copySnippet()}
                      >
                        {copied ? "Copied" : "Copy embed snippet"}
                      </button>
                    )}
                  </div>
                  {publishInfo && (
                    <div className="embed-box">
                      <label className="field">
                        <span>Direct chat URL</span>
                        <input
                          readOnly
                          value={publishInfo.url}
                          onFocus={(e) => e.target.select()}
                        />
                      </label>
                      <label className="field">
                        <span>Website snippet</span>
                        <textarea
                          readOnly
                          rows={3}
                          value={publishInfo.snippet}
                          onFocus={(e) => e.target.select()}
                        />
                      </label>
                      <p className="muted" style={{ fontSize: "0.75rem" }}>
                        Embed key: <code>{publishInfo.key}</code>
                      </p>
                    </div>
                  )}
                  {!currentAgent.published && docs === 0 && (
                    <p className="builder-hint">
                      Tip: attach knowledge first so the published agent has something to prove.
                    </p>
                  )}
                  <div className="builder-pane-foot">
                    <button type="button" className="btn btn-ghost" onClick={() => setTab("voice")}>
                      Back
                    </button>
                  </div>
                </div>
              )}

              {msg && <p className="builder-msg">{msg}</p>}
            </div>
          </div>

          <aside className="builder-preview">
            <div className="builder-preview-label">Live preview · {currentAgent.name}</div>
            <ChatConsole key={currentAgent.id} settings={s} compact showSamples />
            <p className="muted builder-preview-note">
              {docs > 0
                ? `${docs} docs · ${nodes} nodes in this agent’s KB.`
                : "Empty KB — answers will clarify or refuse until you attach sources."}
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}
