import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { DEFAULT_AGENT_SETTINGS, type AgentSettings } from "../agentSettings";
import { api, type ChatResponse, formatApiError } from "../api/client";
import { AnswerMarkdown } from "../components/AnswerMarkdown";
import ThinkingStatus, { shortThinkingLabel, THINKING_STEPS } from "../components/ThinkingStatus";

type Msg = { role: "user" | "assistant"; text: string; data?: ChatResponse };

export default function Embed() {
  const { embedKey = "" } = useParams();
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [thinkStep, setThinkStep] = useState(0);

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

  useEffect(() => {
    if (!embedKey) return;
    api
      .publicAgent(embedKey)
      .then((cfg) => {
        setSettings({
          ...DEFAULT_AGENT_SETTINGS,
          agentName: cfg.name,
          greeting: cfg.greeting,
          placeholder: cfg.placeholder,
          accent: (cfg.accent as AgentSettings["accent"]) || "coral",
          showTrustTrail: cfg.show_trust_trail,
          showCitations: cfg.show_citations,
          showTrustScore: false,
        });
      })
      .catch((e) => setError(formatApiError(e)));
  }, [embedKey]);

  async function send(q: string) {
    if (!q.trim() || busy || !embedKey) return;
    const text = q.trim();
    setQuestion("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const res = await api.publicChat(embedKey, text, sessionId);
      setSessionId(res.session_id);
      const reply =
        res.decision === "clarify"
          ? res.clarification_prompt || "Please clarify."
          : res.answer || "No response.";
      setMsgs((m) => [...m, { role: "assistant", text: reply, data: res }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: formatApiError(e) }]);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="embed-root">
        <div className="embed-error">{error}</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="embed-root">
        <div className="muted" style={{ padding: "1.5rem" }}>
          Loading agent…
        </div>
      </div>
    );
  }

  return (
    <div className={`embed-root accent-${settings.accent}`}>
      <header className="embed-head">
        <div className="agent-avatar" aria-hidden>
          {settings.agentName.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <strong>{settings.agentName}</strong>
          <div className="muted" style={{ fontSize: "0.75rem" }}>
            Powered by VERA · evidence-bound
          </div>
        </div>
      </header>

      <div className="embed-log">
        {!msgs.length && !busy && <p className="agent-greeting muted">{settings.greeting}</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "assistant" ? <AnswerMarkdown text={m.text} /> : <div>{m.text}</div>}
            {m.data?.citations?.length && settings.showCitations ? (
              <div className="embed-cites">
                {m.data.citations.slice(0, 3).map((c, j) => (
                  <div key={j}>
                    <strong>{c.document}</strong>
                    {c.quote ? ` — “${c.quote.slice(0, 140)}${c.quote.length > 140 ? "…" : ""}”` : ""}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        <ThinkingStatus active={busy} />
      </div>

      <form
        className="embed-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(question);
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={settings.placeholder}
          disabled={busy}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !question.trim()}>
          {busy ? shortThinkingLabel(thinkStep) : "Ask"}
        </button>
      </form>
    </div>
  );
}
