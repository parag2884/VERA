import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatApiError, Job } from "../api/client";
import { useWorkspace } from "../state";
import AgentPipelineProgress from "./AgentPipelineProgress";
import CleanStackImpact, { CleanStackReport } from "./CleanStackImpact";

type SourceTab = "upload" | "website" | "sharepoint";

type Props = {
  compact?: boolean;
  onIngestComplete?: () => void;
};

const CATALOG = [
  { id: "upload" as const, title: "Files & Zip", blurb: "PDF, Office, images", state: "live" as const },
  { id: "website" as const, title: "Website", blurb: "Public docs & pages", state: "live" as const },
  { id: "sharepoint" as const, title: "SharePoint", blurb: "Sites & libraries", state: "live" as const },
  { id: null, title: "Azure Blob", blurb: "Container sync", state: "soon" as const },
  { id: null, title: "OneLake / Fabric", blurb: "Lakehouse files", state: "soon" as const },
  { id: null, title: "Azure SQL", blurb: "Structured facts", state: "soon" as const },
];

export default function KnowledgeConnectPanel({ compact, onIngestComplete }: Props) {
  const { ensureWorkspace, setDemoMode, refreshAgents } = useWorkspace();
  const nav = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [tab, setTab] = useState<SourceTab>("upload");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [sharepointUrl, setSharepointUrl] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function clearKnowledge() {
    const ok = window.confirm(
      "Clear all documents, graph, and chat history for this agent?\n\nThe agent stays — you’ll re-upload knowledge for a fresh weave."
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const ws = await ensureWorkspace();
      await api.purgeKnowledge(ws);
      setStatusText("Knowledge cleared — upload documents to rebuild the graph.");
      await refreshAgents().catch(() => undefined);
      onIngestComplete?.();
    } catch (e) {
      setError(formatApiError(e));
      setStatusText(null);
    } finally {
      setBusy(false);
    }
  }

  async function poll(workspaceId: string, jobId: string) {
    for (let i = 0; i < 300; i++) {
      const j = await api.job(workspaceId, jobId);
      setJob(j);
      const ev = (j.events || []) as Array<{ message?: string }>;
      const last = [...ev].reverse().find((e) => e.message);
      if (last?.message) setStatusText(last.message);
      if (j.result && (j.result as { demo_mode?: boolean }).demo_mode) setDemoMode(true);
      if (j.status === "completed" || j.status === "failed") return j;
      await new Promise((r) => setTimeout(r, 800));
    }
    throw new Error("Timed out waiting for ingest");
  }

  async function runJob(start: () => Promise<{ ws: string; job: Job; label: string }>) {
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const { ws, job: j, label } = await start();
      setJob(j);
      setStatusText(`${label} queued…`);
      const done = await poll(ws, j.id);
      if (done.status === "failed") throw new Error(done.error || "Ingest failed");
      setStatusText("Ingest complete — CleanStack impact below.");
      onIngestComplete?.();
    } catch (e) {
      setError(formatApiError(e));
      setStatusText(null);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function runSample() {
    if (busy) return;
    const ok = window.confirm(
      "Load the built-in demo KB?\n\n" +
        "This is a small IT / remote-access sample (policies + VPN guides) — not your PlayReady docs.\n\n" +
        "It will weave a new graph and use Azure while it runs. Continue only if you want that demo."
    );
    if (!ok) return;
    await runJob(async () => {
      setStatusText("Starting sample ingest…");
      const ws = await ensureWorkspace();
      const j = await api.loadSample(ws);
      return { ws, job: j, label: "Sample KB" };
    });
  }

  async function onUpload(files: FileList | null) {
    if (!files?.length) return;
    const names = Array.from(files)
      .map((f) => f.name)
      .join(", ");
    await runJob(async () => {
      setStatusText(`Uploading ${names}…`);
      const ws = await ensureWorkspace();
      const j = await api.upload(ws, files);
      return { ws, job: j, label: "Upload" };
    });
  }

  async function runWebsite() {
    if (!websiteUrl.trim()) {
      setError("Enter a website URL");
      return;
    }
    await runJob(async () => {
      setStatusText(`Crawling ${websiteUrl.trim()}…`);
      const ws = await ensureWorkspace();
      const j = await api.ingestUrl(ws, websiteUrl.trim());
      return { ws, job: j, label: "Website" };
    });
  }

  async function runSharePoint(demo: boolean) {
    if (!demo && !sharepointUrl.trim()) {
      setError("Paste a SharePoint site or folder URL, or use the demo library");
      return;
    }
    await runJob(async () => {
      setStatusText(demo ? "Loading demo SharePoint library…" : "Syncing SharePoint…");
      const ws = await ensureWorkspace();
      const j = await api.ingestSharePoint(ws, {
        url: demo ? undefined : sharepointUrl.trim(),
        demo,
      });
      return { ws, job: j, label: demo ? "SharePoint demo" : "SharePoint" };
    });
  }

  const report = (job?.result?.cleanstack || null) as CleanStackReport | null;
  const impact = (job?.result?.impact || null) as Record<string, number> | null;
  const catalog = compact ? CATALOG.filter((s) => s.state === "live") : CATALOG;
  const showPipeline = !compact || busy || Boolean(job);

  const sourceControls = (
    <>
      {tab === "upload" && (
        <div className="source-pane">
          {!compact && (
            <p className="muted" style={{ marginTop: 0 }}>
              Upload PDFs, Office docs, images, or a <strong>.zip</strong> (up to 100MB). Nested zip
              folders are preserved. Max 100 files after expand.
            </p>
          )}
          <div className="cta-row">
            <label className="btn btn-primary" style={{ cursor: busy ? "not-allowed" : "pointer" }}>
              {busy ? "Building index…" : "Upload files / zip"}
              <input
                ref={fileRef}
                type="file"
                multiple
                hidden
                disabled={busy}
                accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.tif,.tiff"
                onChange={(e) => void onUpload(e.target.files)}
              />
            </label>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={busy}
              title="Loads a small built-in IT/VPN demo corpus — not your product docs"
              onClick={() => void runSample()}
            >
              Load demo sample
            </button>
          </div>
          {!compact && (
            <p className="muted" style={{ marginTop: "0.55rem", fontSize: "0.8rem" }}>
              Demo sample is optional — a tiny remote-access policy set for trying VERA. Prefer upload
              for real agent knowledge.
            </p>
          )}
        </div>
      )}

      {tab === "website" && (
        <div className="source-pane">
          {!compact && (
            <p className="muted" style={{ marginTop: 0 }}>
              Paste a public page URL. VERA fetches the page (and same-site links up to depth 1) into
              markdown sources for CleanStack.
            </p>
          )}
          <label className="field">
            <span>Website URL</span>
            <input
              type="url"
              placeholder="https://learn.microsoft.com/…"
              value={websiteUrl}
              disabled={busy}
              onChange={(e) => setWebsiteUrl(e.target.value)}
            />
          </label>
          <div className="cta-row">
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void runWebsite()}>
              {busy ? "Crawling…" : "Add website"}
            </button>
          </div>
        </div>
      )}

      {tab === "sharepoint" && (
        <div className="source-pane">
          {!compact && (
            <p className="muted" style={{ marginTop: 0 }}>
              Point at a SharePoint site or library folder. Without Graph credentials, use the nested{" "}
              <strong>demo library</strong>.
            </p>
          )}
          <label className="field">
            <span>SharePoint site / folder URL</span>
            <input
              type="url"
              placeholder="https://contoso.sharepoint.com/sites/Knowledge/Shared Documents/Policies"
              value={sharepointUrl}
              disabled={busy}
              onChange={(e) => setSharepointUrl(e.target.value)}
            />
          </label>
          <div className="cta-row">
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy}
              onClick={() => void runSharePoint(false)}
            >
              {busy ? "Syncing…" : "Connect SharePoint"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={busy}
              onClick={() => void runSharePoint(true)}
            >
              Use demo library
            </button>
          </div>
          {!compact && (
            <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
              Real sync needs <code>VERA_MS_TENANT_ID</code>, <code>VERA_MS_CLIENT_ID</code>,{" "}
              <code>VERA_MS_CLIENT_SECRET</code> with Sites.Read.All + Files.Read.All.
            </p>
          )}
        </div>
      )}

      {statusText && !error && !compact && (
        <p className="muted" style={{ marginTop: "1rem", fontSize: "0.9rem" }}>
          {statusText}
        </p>
      )}
      {error && <p style={{ color: "var(--red)", marginTop: "0.75rem" }}>{error}</p>}
    </>
  );

  if (compact) {
    return (
      <div className="kb-connect-panel kb-connect-compact">
        <div className="kb-compact-tabs" role="tablist" aria-label="Knowledge source">
          {catalog.map((src) =>
            src.id ? (
              <button
                key={src.title}
                type="button"
                role="tab"
                aria-selected={tab === src.id}
                className={`kb-tab ${tab === src.id ? "active" : ""}`}
                disabled={busy}
                onClick={() => setTab(src.id!)}
              >
                {src.title}
              </button>
            ) : null
          )}
        </div>

        <div className="kb-source-block">{sourceControls}</div>

        <div className="cta-row" style={{ marginTop: "0.65rem", flexWrap: "wrap" }}>
          <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => void clearKnowledge()}>
            Clear knowledge
          </button>
        </div>
        {statusText && !showPipeline && (
          <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.82rem" }}>
            {statusText}
          </p>
        )}

        {showPipeline && (
          <div className="kb-pipeline-block">
            <AgentPipelineProgress
              compact
              events={(job?.events as Array<Record<string, unknown>>) || []}
              progress={job?.progress || 0}
              status={job?.status}
              statusText={statusText}
            />
          </div>
        )}

        {report && (
          <div className="kb-impact-block">
            <CleanStackImpact report={report} impact={impact} />
            <div className="cta-row" style={{ marginTop: "0.75rem" }}>
              <button className="btn btn-primary" type="button" onClick={() => nav("/ask")}>
                Ask
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => nav("/map")}>
                Map
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="kb-connect-panel">
      <div className="kb-catalog">
        {catalog.map((src) => (
          <button
            key={src.title}
            type="button"
            className={`kb-tile ${src.id && tab === src.id ? "active" : ""} ${src.state}`}
            disabled={busy || src.state === "soon"}
            onClick={() => src.id && setTab(src.id)}
          >
            <strong>{src.title}</strong>
            <span>{src.blurb}</span>
            <em>{src.state === "live" ? "Ready" : "Next"}</em>
          </button>
        ))}
      </div>

      <div className="grid-2">
        <div className="stack">
          <div className="panel">
            <div className="panel-head">
              <div>
                <h3>
                  {tab === "upload" ? "Files & Zip" : tab === "website" ? "Website" : "SharePoint"}
                </h3>
                <p>Feeds the active agent only — other agents stay isolated.</p>
              </div>
              <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => void clearKnowledge()}>
                Clear knowledge
              </button>
            </div>
            {sourceControls}
            {statusText && !job && (
              <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
                {statusText}
              </p>
            )}
          </div>

          {report && (
            <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "1.25rem 1.3rem" }}>
                <CleanStackImpact report={report} impact={impact} />
                <div className="cta-row" style={{ marginTop: "1.1rem" }}>
                  <button className="btn btn-primary" type="button" onClick={() => nav("/ask")}>
                    Ask with Trust Trails
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => nav("/map")}>
                    Open knowledge map
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => nav("/insights")}>
                    Insights
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="panel panel-soft">
          <div className="panel-head">
            <div>
              <h3>Named agent stages</h3>
              <p>Watch CleanStack as a first-class gate — not a black-box spinner.</p>
            </div>
            {job?.status === "completed" && (
              <div className="metric-tile" style={{ minWidth: 110 }}>
                <div className="label">Health</div>
                <div className="value">{String(job.result?.health_score ?? "—")}</div>
              </div>
            )}
          </div>
          <AgentPipelineProgress
            events={(job?.events as Array<Record<string, unknown>>) || []}
            progress={job?.progress || 0}
            status={job?.status}
            statusText={statusText}
          />
        </div>
      </div>
    </div>
  );
}
