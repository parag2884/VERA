import { useMemo, useState } from "react";

export type EmbedCodeTab = "html" | "iframe" | "python";

type Props = {
  embedKey: string;
  embedUrl: string;
  widgetSnippet: string;
  /** Origin that serves widget.js + /embed (no trailing slash). */
  widgetOrigin?: string;
  /** API root including /api, e.g. https://host/api */
  apiBase?: string;
  agentName?: string;
};

const TABS: { id: EmbedCodeTab; label: string; hint: string }[] = [
  { id: "html", label: "HTML", hint: "Website widget" },
  { id: "iframe", label: "iframe", hint: "Full chat page" },
  { id: "python", label: "Python", hint: "Server / backend" },
];

function defaultOrigin(): string {
  if (typeof window === "undefined") return "https://your-vera-host";
  return window.location.origin;
}

function defaultApiBase(origin: string): string {
  return `${origin.replace(/\/$/, "")}/api`;
}

export function buildEmbedSamples(opts: {
  embedKey: string;
  embedUrl: string;
  widgetSnippet: string;
  widgetOrigin?: string;
  apiBase?: string;
  agentName?: string;
}): Record<EmbedCodeTab, string> {
  const origin = (opts.widgetOrigin || defaultOrigin()).replace(/\/$/, "");
  const api = (opts.apiBase || defaultApiBase(origin)).replace(/\/$/, "");
  const key = opts.embedKey;
  const name = opts.agentName || "VERA agent";
  const snippet =
    opts.widgetSnippet?.trim() ||
    `<script src="${origin}/widget.js" data-vera-key="${key}" data-vera-origin="${origin}" async></script>`;
  const embedUrl = opts.embedUrl || `${origin}/embed/${key}`;

  const html = `<!-- Paste before </body> on your site — floating ${name} chat -->
${snippet}

<!-- Optional: restrict which pages can call this key via Agent → Voice → allowed origins -->`;

  const iframe = `<!-- Embed the full published chat UI in your page or portal -->
<iframe
  src="${embedUrl}"
  title="${name}"
  style="width:100%;max-width:420px;height:640px;border:0;border-radius:16px;box-shadow:0 8px 28px rgba(0,0,0,.12);"
  allow="clipboard-write"
></iframe>

<!-- Or open directly: ${embedUrl} -->`;

  const python = `# Call the published agent from your backend / automation
# pip install requests

import requests

EMBED_KEY = "${key}"
API_BASE = "${api}"  # VERA public API root

def ask_vera(question: str, session_id: str | None = None) -> dict:
    r = requests.post(
        f"{API_BASE}/public/chat",
        json={
            "embed_key": EMBED_KEY,
            "question": question,
            "session_id": session_id,
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()

# Optional: load greeting / branding
# cfg = requests.get(f"{API_BASE}/public/agents/{EMBED_KEY}", timeout=30).json()

result = ask_vera("Ask a question grounded in this agent's knowledge…")
print(result.get("decision"), result.get("answer") or result.get("clarification_prompt"))
`;

  return { html, iframe, python };
}

export default function EmbedCodePanel({
  embedKey,
  embedUrl,
  widgetSnippet,
  widgetOrigin,
  apiBase,
  agentName,
}: Props) {
  const [tab, setTab] = useState<EmbedCodeTab>("html");
  const [copied, setCopied] = useState(false);

  const samples = useMemo(
    () =>
      buildEmbedSamples({
        embedKey,
        embedUrl,
        widgetSnippet,
        widgetOrigin,
        apiBase,
        agentName,
      }),
    [embedKey, embedUrl, widgetSnippet, widgetOrigin, apiBase, agentName],
  );

  const code = samples[tab];

  async function copy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="embed-code-panel">
      <div className="embed-code-head">
        <div>
          <div className="page-kicker">Integrate</div>
          <h3 className="embed-code-title">Add this agent to your platform</h3>
          <p className="muted embed-code-sub">
            Same pattern as top product sites — drop-in HTML widget, iframe, or call the public API
            from Python.
          </p>
        </div>
        <button className="btn btn-accent" type="button" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>

      <div className="embed-code-tabs" role="tablist" aria-label="Embed code language">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`embed-code-tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            <span>{t.label}</span>
            <small>{t.hint}</small>
          </button>
        ))}
      </div>

      <label className="field embed-code-field">
        <span>
          {tab === "html" && "Website widget snippet"}
          {tab === "iframe" && "Inline chat iframe"}
          {tab === "python" && "Python (requests)"}
        </span>
        <textarea
          className="embed-code-textarea"
          readOnly
          rows={tab === "python" ? 18 : 8}
          value={code}
          spellCheck={false}
          onFocus={(e) => e.target.select()}
        />
      </label>

      <p className="muted embed-code-foot">
        Direct chat: <a href={embedUrl} target="_blank" rel="noreferrer">{embedUrl}</a>
        {" · "}
        Embed key: <code>{embedKey}</code>
      </p>
    </div>
  );
}
