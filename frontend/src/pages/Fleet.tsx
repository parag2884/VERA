import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatApiError, api } from "../api/client";
import AgentMoreMenu from "../components/AgentMoreMenu";
import EditableText from "../components/EditableText";
import { useWorkspace } from "../state";

function statusLabel(a: {
  disabled?: boolean;
  published: boolean;
  counts?: { documents?: number; chunks?: number; nodes?: number };
}) {
  if (a.disabled) return "disabled";
  if (a.published) return "live";
  if ((a.counts?.documents ?? 0) > 0 || (a.counts?.chunks ?? 0) > 0 || (a.counts?.nodes ?? 0) > 0)
    return "ready";
  return "draft";
}

export default function Fleet() {
  const {
    agents,
    agentId,
    selectAgent,
    createAgent,
    renameAgent,
    refreshAgents,
    setAgentDisabled,
    deleteAgent,
  } = useWorkspace();
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [health, setHealth] = useState<
    Awaited<ReturnType<typeof api.knowledgeOsFleet>>["workspaces"]
  >([]);

  useEffect(() => {
    void refreshAgents().catch((e) => setErr(formatApiError(e)));
    void api
      .knowledgeOsFleet()
      .then((r) => setHealth(r.workspaces || []))
      .catch(() => setHealth([]));
  }, [refreshAgents]);

  async function onCreate() {
    const name = newName.trim() || "New agent";
    setBusyId("create");
    try {
      await createAgent(name, "Dedicated knowledge graph for this domain");
      setNewName("");
      setShowCreate(false);
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  async function onPublish(id: string) {
    setBusyId(id);
    setOpenMenu(null);
    try {
      await api.publishAgent(id);
      await refreshAgents();
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  async function onUnpublish(id: string) {
    setBusyId(id);
    setOpenMenu(null);
    try {
      await api.unpublishAgent(id);
      await refreshAgents();
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  async function onToggleDisabled(id: string, disabled: boolean) {
    setBusyId(id);
    setOpenMenu(null);
    try {
      await setAgentDisabled(id, disabled);
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  async function onDelete(id: string, name: string) {
    setOpenMenu(null);
    const ok = window.confirm(
      `Delete “${name}” permanently?\n\nThis removes the agent, its knowledge graph, documents, chats, and embeddings. This cannot be undone.`
    );
    if (!ok) return;
    setBusyId(id);
    try {
      await deleteAgent(id);
      setErr(null);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="fleet-page">
      <div className="page-kicker">Studio</div>
      <div className="fleet-head">
        <div>
          <h2 className="section-title">Agent Fleet</h2>
          <p className="section-sub">
            Click a row to work on that agent. Ask opens chat. More includes publish, connect,
            enable/disable, and delete.
          </p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => setShowCreate((v) => !v)}>
          New agent
        </button>
      </div>

      {showCreate && (
        <div className="bento-create">
          <input
            autoFocus
            value={newName}
            placeholder="Agent name"
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void onCreate();
            }}
          />
          <button
            className="btn btn-primary"
            type="button"
            disabled={busyId === "create"}
            onClick={() => void onCreate()}
          >
            Create
          </button>
        </div>
      )}

      {err && <div className="demo-banner">{err}</div>}

      {health.length > 0 && (
        <section className="bento-table-wrap" style={{ marginBottom: "1.15rem" }}>
          <div className="bento-table-head">
            <h2>Workspace health</h2>
            <span>Coverage · debt · risk · SLA across agents</span>
          </div>
          <table className="agent-table agent-table-auto">
            <thead>
              <tr>
                <th className="fill">Workspace</th>
                <th>Risk</th>
                <th className="num">Debt</th>
                <th className="num">Coverage</th>
                <th className="num">Trust</th>
                <th className="num">Fitness</th>
                <th>SLA</th>
              </tr>
            </thead>
            <tbody>
              {health.map((h) => (
                <tr key={h.agent_id || h.workspace_id}>
                  <td className="fill">{h.name}</td>
                  <td>{h.risk || "—"}</td>
                  <td className="num">{h.debt ?? "—"}</td>
                  <td className="num">{h.coverage ?? "—"}</td>
                  <td className="num">{h.trust ?? "—"}</td>
                  <td className="num">{h.fitness != null ? Number(h.fitness).toFixed(0) : "—"}</td>
                  <td>
                    {h.sla_ok
                      ? "pass"
                      : (h.sla_miss || []).length
                        ? `fail (${(h.sla_miss || []).join(", ")})`
                        : "fail"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="bento-table-wrap">
        <div className="bento-table-head">
          <h2>All agents</h2>
          <span>
            {agents.length} total
            {agentId
              ? ` · Studio: ${agents.find((a) => a.id === agentId)?.name || "selected"}`
              : ""}
          </span>
        </div>

        {!agents.length ? (
          <div className="dash-empty">
            <p>No agents yet — create one to start building a knowledge graph.</p>
            <button className="btn btn-primary" type="button" onClick={() => setShowCreate(true)}>
              New agent
            </button>
          </div>
        ) : (
          <table className="agent-table agent-table-wide col-2-status">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Status</th>
                <th className="num">Docs</th>
                <th className="num">Nodes</th>
                <th className="num">Asks</th>
                <th className="actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => {
                const status = statusLabel(a);
                const busy = busyId === a.id;
                const selected = a.id === agentId;
                const askOk =
                  a.ask_readiness?.status && a.ask_readiness.status !== "unknown"
                    ? a.ask_readiness.status === "ready"
                      ? "Ask ok"
                      : "Ask check"
                    : null;
                return (
                  <tr
                    key={a.id}
                    className={`${selected ? "is-active" : ""} ${a.disabled ? "is-disabled" : ""}`}
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
                          }}
                        />
                      </div>
                    </td>
                    <td>
                      <div className="bento-cell-status">
                        <span className={`ready-pill ${status}`}>
                          {status === "disabled"
                            ? "Disabled"
                            : status === "live"
                              ? "Live"
                              : status === "ready"
                                ? "Ready"
                                : "Draft"}
                        </span>
                        {askOk && (
                          <span
                            className={`ready-pill ${askOk === "Ask ok" ? "ready" : "draft"}`}
                            title={(a.ask_readiness?.failing_patterns || []).join(", ") || undefined}
                          >
                            {askOk}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="num">{a.counts.documents ?? 0}</td>
                    <td className="num">{a.counts.nodes ?? 0}</td>
                    <td className="num">{a.counts.asks ?? 0}</td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <div className="agent-row-actions">
                        <Link
                          className="btn btn-primary"
                          to="/ask"
                          onClick={() => void selectAgent(a.id)}
                        >
                          Ask
                        </Link>
                        <AgentMoreMenu
                          open={openMenu === a.id}
                          disabled={busy}
                          onOpenChange={(open) => setOpenMenu(open ? a.id : null)}
                        >
                          <Link
                            role="menuitem"
                            to="/connect"
                            onClick={() => {
                              setOpenMenu(null);
                              void selectAgent(a.id);
                            }}
                          >
                            Connect knowledge
                          </Link>
                          <Link
                            role="menuitem"
                            to="/map"
                            onClick={() => {
                              setOpenMenu(null);
                              void selectAgent(a.id);
                            }}
                          >
                            Open map
                          </Link>
                          {a.published ? (
                            <button
                              type="button"
                              role="menuitem"
                              disabled={busy}
                              onClick={() => void onUnpublish(a.id)}
                            >
                              Unpublish
                            </button>
                          ) : (
                            <button
                              type="button"
                              role="menuitem"
                              disabled={busy}
                              onClick={() => void onPublish(a.id)}
                            >
                              Publish agent
                            </button>
                          )}
                          {a.disabled ? (
                            <button
                              type="button"
                              role="menuitem"
                              disabled={busy}
                              onClick={() => void onToggleDisabled(a.id, false)}
                            >
                              Enable chatbot
                            </button>
                          ) : (
                            <button
                              type="button"
                              role="menuitem"
                              disabled={busy}
                              onClick={() => void onToggleDisabled(a.id, true)}
                            >
                              Disable chatbot
                            </button>
                          )}
                          <button
                            type="button"
                            role="menuitem"
                            className="danger"
                            disabled={busy}
                            onClick={() => void onDelete(a.id, a.name)}
                          >
                            Delete agent
                          </button>
                        </AgentMoreMenu>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
