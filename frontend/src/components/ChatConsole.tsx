import { useEffect, useMemo, useState } from "react";
import { AgentSettings } from "../agentSettings";
import { api, ChatResponse } from "../api/client";
import { defaultSamplesForAgent } from "../sampleQuestions";
import { useWorkspace } from "../state";
import { AnswerMarkdown } from "./AnswerMarkdown";
import ThinkingStatus, { shortThinkingLabel, THINKING_STEPS } from "./ThinkingStatus";

type Msg = { role: "user" | "assistant"; text: string; data?: ChatResponse };

type Props = {
  settings: AgentSettings;
  compact?: boolean;
  showSamples?: boolean;
  /** Full-height ChatGPT-style shell (Ask page). */
  focusMode?: boolean;
  /** Show agent dropdown in the chat header. */
  showAgentPicker?: boolean;
};

export default function ChatConsole({
  settings,
  compact,
  showSamples = true,
  focusMode = false,
  showAgentPicker = false,
}: Props) {
  const {
    ensureWorkspace,
    setDemoMode,
    updateAgentSettings,
    agents,
    agentId,
    selectAgent,
    currentAgent,
  } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [thinkStep, setThinkStep] = useState(0);
  const [showScoreFor, setShowScoreFor] = useState<number | null>(null);
  const [showExtras, setShowExtras] = useState(false);
  const [streaming, setStreaming] = useState(() => {
    try {
      const v = localStorage.getItem("vera.askStreaming");
      return v === null ? true : v === "1";
    } catch {
      return true;
    }
  });
  const [streamStatus, setStreamStatus] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem("vera.askStreaming", streaming ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [streaming]);

  const domainProfile = (currentAgent?.settings?.domainProfile || null) as
    | { label?: string; focus?: string; entityTypes?: string[] }
    | null;
  const samples = useMemo(() => {
    const custom = (settings.sampleQuestions || []).map((q) => q.trim()).filter(Boolean);
    if (custom.length) return custom.slice(0, 6);
    return defaultSamplesForAgent(settings.agentName, domainProfile);
  }, [settings.sampleQuestions, settings.agentName, domainProfile]);

  useEffect(() => {
    if (!busy) {
      setThinkStep(0);
      return;
    }
    setThinkStep(0);
    const id = window.setInterval(() => {
      setThinkStep((s) => Math.min(s + 1, THINKING_STEPS.length - 1));
    }, 1400);
    return () => window.clearInterval(id);
  }, [busy]);

  async function send(q: string) {
    if (!q.trim() || busy) return;
    const text = q.trim();
    setQuestion("");
    setBusy(true);
    setStreamStatus(null);
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const ws = await ensureWorkspace();
      if (streaming) {
        // Placeholder bubble that fills as tokens arrive
        setMsgs((m) => [...m, { role: "assistant", text: "" }]);
        const res = await api.chatStream(ws, text, sessionId, {
          tone: settings.tone,
          verbosity: settings.verbosity,
          onStatus: (message) => setStreamStatus(message),
          onToken: (piece) => {
            setMsgs((m) => {
              if (!m.length) return m;
              const copy = m.slice();
              const last = copy[copy.length - 1];
              if (!last || last.role !== "assistant") return m;
              copy[copy.length - 1] = { ...last, text: `${last.text}${piece}` };
              return copy;
            });
          },
        });
        setSessionId(res.session_id);
        if (res.demo_mode) setDemoMode(true);
        const reply =
          res.decision === "clarify"
            ? res.clarification_prompt || "Please clarify."
            : res.answer || "No response.";
        setMsgs((m) => {
          const copy = m.slice();
          const last = copy[copy.length - 1];
          if (last?.role === "assistant") {
            copy[copy.length - 1] = { role: "assistant", text: reply, data: res };
          } else {
            copy.push({ role: "assistant", text: reply, data: res });
          }
          return copy;
        });
      } else {
        const res = await api.chat(ws, text, sessionId, {
          tone: settings.tone,
          verbosity: settings.verbosity,
        });
        setSessionId(res.session_id);
        if (res.demo_mode) setDemoMode(true);
        const reply =
          res.decision === "clarify"
            ? res.clarification_prompt || "Please clarify."
            : res.answer || "No response.";
        setMsgs((m) => [...m, { role: "assistant", text: reply, data: res }]);
      }
    } catch (e) {
      setMsgs((m) => {
        const copy = m.slice();
        const errText = e instanceof Error ? e.message : String(e);
        const last = copy[copy.length - 1];
        if (last?.role === "assistant" && !last.data) {
          copy[copy.length - 1] = { role: "assistant", text: errText };
          return copy;
        }
        return [...copy, { role: "assistant", text: errText }];
      });
    } finally {
      setBusy(false);
      setStreamStatus(null);
    }
  }

  return (
    <div
      className={`panel chat-shell accent-${settings.accent}${compact ? " chat-compact" : ""}${
        focusMode ? " chat-focus" : ""
      }`}
    >
      <div className="agent-chat-head">
        <div className="agent-avatar" aria-hidden>
          {settings.agentName.slice(0, 1).toUpperCase()}
        </div>
        <div className="agent-chat-meta" style={{ flex: 1, minWidth: 0 }}>
          {showAgentPicker && agents.length > 0 ? (
            <label className="chat-agent-picker">
              <span className="chat-agent-picker-label">Agent</span>
              <select
                value={agentId || ""}
                aria-label="Select agent to ask"
                onChange={(e) => {
                  if (e.target.value) void selectAgent(e.target.value);
                }}
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {a.published ? " · live" : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="agent-chat-name">{settings.agentName}</div>
          )}
          {!focusMode && (
            <div className="muted agent-chat-sub">
              Tone · {settings.tone} · {settings.verbosity}
              {currentAgent?.counts?.documents != null
                ? ` · ${currentAgent.counts.documents} docs`
                : ""}
            </div>
          )}
        </div>
        <div className="chat-header-actions">
          <button
            type="button"
            className={`chat-seg-btn ${streaming ? "on" : "off"}`}
            aria-pressed={streaming}
            title="Stream answer text as it becomes available"
            onClick={() => setStreaming((v) => !v)}
          >
            <span className="chat-seg-mark" aria-hidden>
              {streaming ? "✓" : ""}
            </span>
            Streaming {streaming ? "On" : "Off"}
          </button>
          {focusMode && (
            <button
              type="button"
              className={`chat-extras-toggle ${showExtras ? "on" : ""}`}
              aria-expanded={showExtras}
              aria-label="Answer display options"
              onClick={() => setShowExtras((v) => !v)}
            >
              Options
            </button>
          )}
        </div>
      </div>

      {(!focusMode || showExtras) && (
        <div className={`chat-view-bar${focusMode ? " chat-view-bar-focus" : ""}`}>
          <span className="chat-view-label">Show in answers</span>
          <div className="chat-view-seg" role="group" aria-label="Show in answers">
            {(
              [
                ["showCitations", "Citations", settings.showCitations],
                ["showTrustTrail", "Trail", settings.showTrustTrail],
                ["showTrustScore", "Score", settings.showTrustScore],
              ] as const
            ).map(([key, label, on]) => (
              <button
                key={key}
                type="button"
                className={`chat-seg-btn ${on ? "on" : "off"}`}
                aria-pressed={on}
                onClick={() => updateAgentSettings({ [key]: !on })}
              >
                <span className="chat-seg-mark" aria-hidden>
                  {on ? "✓" : ""}
                </span>
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-log">
        {msgs.length === 0 && !busy && (
          <div className="empty-state agent-greeting">{settings.greeting}</div>
        )}
        {msgs.map((m, i) => {
          // Hide the streaming placeholder until the first token arrives
          // (otherwise an empty bordered bubble looks like a blank circle).
          const waitingForTokens =
            m.role === "assistant" && !m.data && !(m.text || "").trim();
          if (waitingForTokens) return null;
          return (
          <div key={i} className={`bubble ${m.role}`}>
            {m.data && !focusMode && (
              <span className={`decision ${m.data.decision}`}>{m.data.decision}</span>
            )}
            {m.role === "assistant" ? (
              <AnswerMarkdown
                text={m.text}
                live={streaming && busy && !m.data && i === msgs.length - 1}
              />
            ) : (
              <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
            )}
            {m.data && focusMode && (
              <div className="chat-meta-chips">
                <span className={`chip-mini ${m.data.decision}`}>{m.data.decision}</span>
                {settings.showTrustScore && m.data.trust_score ? (
                  <span className="chip-mini muted">
                    trust {m.data.trust_score.overall.toFixed(2)}
                  </span>
                ) : null}
                {m.data.retrieval_mode ? (
                  <span className="chip-mini muted">{m.data.retrieval_mode}</span>
                ) : null}
              </div>
            )}

            {settings.showTrustTrail && m.data?.trust_trail?.length ? (
              <div className="trail">
                Trust Trail ·{" "}
                {m.data.trust_trail.map((h) => `${h.from} —${h.rel}→ ${h.to}`).join(" · ")}
              </div>
            ) : null}

            {settings.showCitations && m.data?.citations?.length ? (
              <div className="citations">
                {m.data.citations.map((c, idx) => (
                  <div className="citation" key={idx}>
                    <strong>{c.document}</strong>
                    {c.locator ? <span className="muted"> · {c.locator}</span> : null}
                    <div style={{ marginTop: "0.35rem" }}>“{c.quote}”</div>
                  </div>
                ))}
              </div>
            ) : null}

            {m.data?.clarify_options?.length ? (
              <div className="chips" style={{ marginTop: "0.85rem" }}>
                {m.data.clarify_options.map((o) => (
                  <button
                    key={o.id}
                    className="chip"
                    type="button"
                    onClick={() => void send(o.label)}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            ) : null}

            {!focusMode &&
              settings.showTrustScore &&
              m.data?.trust_score &&
              m.data.decision === "answer" && (
              <div style={{ marginTop: "0.85rem" }}>
                <button
                  className="chip"
                  type="button"
                  onClick={() => setShowScoreFor((v) => (v === i ? null : i))}
                >
                  Trust score {m.data.trust_score.overall.toFixed(2)} · Why?
                </button>
                {showScoreFor === i && (
                  <div className="scorecard">
                    {Object.entries(m.data.trust_score).map(([k, v]) => (
                      <div className="score-item" key={k}>
                        <b>{Number(v).toFixed(2)}</b>
                        {k.replace(/_/g, " ")}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          );
        })}
        <ThinkingStatus active={busy && !streamStatus} />
        {busy && streamStatus ? (
          <div className="chat-stream-status" aria-live="polite">
            {streamStatus}
          </div>
        ) : null}
      </div>

      {showSamples && samples.length > 0 && (!focusMode || (msgs.length === 0 && !busy)) && (
        <div className="chat-try">
          <div className="chips">
            {samples.map((s) => (
              <button
                key={s}
                className="chip"
                type="button"
                disabled={busy}
                title={s}
                onClick={() => void send(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="composer">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void send(question)}
          placeholder={settings.placeholder}
          disabled={busy}
        />
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void send(question)}>
          {busy ? shortThinkingLabel(thinkStep) : "Ask"}
        </button>
      </div>
    </div>
  );
}
