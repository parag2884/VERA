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
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const ws = await ensureWorkspace();
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
    } catch (e) {
      setMsgs((m) => [
        ...m,
        { role: "assistant", text: e instanceof Error ? e.message : String(e) },
      ]);
    } finally {
      setBusy(false);
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
          <div className="muted agent-chat-sub">
            Tone · {settings.tone} · {settings.verbosity}
            {currentAgent?.counts?.documents != null
              ? ` · ${currentAgent.counts.documents} docs`
              : ""}
          </div>
        </div>
      </div>

      <div className="chat-view-bar">
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

      <div className="chat-log">
        {msgs.length === 0 && !busy && (
          <div className="empty-state agent-greeting">{settings.greeting}</div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.data && <span className={`decision ${m.data.decision}`}>{m.data.decision}</span>}
            {m.role === "assistant" ? (
              <AnswerMarkdown text={m.text} />
            ) : (
              <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
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

            {settings.showTrustScore && m.data?.trust_score && m.data.decision === "answer" && (
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
        ))}
        <ThinkingStatus active={busy} />
      </div>

      {showSamples && samples.length > 0 && (!focusMode || (msgs.length === 0 && !busy)) && (
        <div className="chat-try">
          <div className="chips">
            {samples.map((s) => (
              <button key={s} className="chip" type="button" disabled={busy} onClick={() => void send(s)}>
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
