import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatApiError, Job } from "../api/client";
import { useWorkspace } from "../state";
import AgentPipelineProgress from "./AgentPipelineProgress";
import CleanStackImpact, { CleanStackReport } from "./CleanStackImpact";

type SourceTab = string;

type CatalogTile = {
  id: string | null;
  title: string;
  blurb: string;
  state: "live" | "needs_config" | "planned" | "soon";
  setup_hint?: string;
  interactive: boolean;
};

type Props = {
  compact?: boolean;
  onIngestComplete?: () => void;
};

const FALLBACK_CATALOG: CatalogTile[] = [
  { id: "upload", title: "Files & Zip", blurb: "PDF, Office, images", state: "live", interactive: true },
  { id: "website", title: "Website", blurb: "Public docs & pages", state: "live", interactive: true },
  { id: "sharepoint", title: "SharePoint", blurb: "Sites & libraries", state: "live", interactive: true },
  { id: "blob", title: "Azure Blob", blurb: "Container sync", state: "needs_config", interactive: true },
  { id: "outlook", title: "Email & calendar", blurb: "Ask about mail, meetings, summaries", state: "planned", interactive: false },
  { id: "onedrive", title: "OneDrive", blurb: "Personal / work files", state: "planned", interactive: false },
  { id: "teams", title: "Microsoft Teams", blurb: "Channels & files", state: "planned", interactive: false },
  { id: "onelake", title: "OneLake / Fabric", blurb: "Lakehouse files", state: "planned", interactive: false },
  { id: "azure_sql", title: "Azure SQL", blurb: "Structured facts", state: "planned", interactive: false },
  { id: "confluence", title: "Confluence", blurb: "Wiki spaces", state: "planned", interactive: false },
  { id: "gdrive", title: "Google Drive", blurb: "Shared drives & Docs", state: "planned", interactive: false },
];

const LIVE_TABS = new Set(["upload", "website", "sharepoint", "blob"]);

function tileStateLabel(state: CatalogTile["state"]): string {
  if (state === "live") return "Ready";
  if (state === "needs_config") return "Setup";
  return "Next";
}

function tileCssState(state: CatalogTile["state"]): string {
  if (state === "live") return "live";
  if (state === "needs_config") return "setup";
  return "soon";
}

export default function KnowledgeConnectPanel({ compact, onIngestComplete }: Props) {
  const { ensureWorkspace, setDemoMode, refreshAgents, currentAgent } = useWorkspace();
  const nav = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [tab, setTab] = useState<SourceTab>("upload");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [sharepointUrl, setSharepointUrl] = useState("");
  const [blobContainer, setBlobContainer] = useState("");
  const [blobPrefix, setBlobPrefix] = useState("");
  const [blobConfigured, setBlobConfigured] = useState(false);
  const [catalog, setCatalog] = useState<CatalogTile[]>(FALLBACK_CATALOG);
  const [plannedHint, setPlannedHint] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api
      .connectors()
      .then((c) => {
        const blob = c.blob || {};
        setBlobConfigured(Boolean(blob.configured) || blob.state === "configured");
        if (Array.isArray(c.catalog) && c.catalog.length) {
          setCatalog(
            c.catalog.map((row) => {
              const raw = (row.state || "planned").toLowerCase();
              let state: CatalogTile["state"] = "planned";
              if (raw === "configured" || (row.id === "blob" && row.configured)) state = "live";
              else if (raw === "needs_config") state = "needs_config";
              else if (["upload", "website", "sharepoint", "documents", "web"].includes(row.id))
                state = "live";
              else if (row.id === "blob") state = row.configured ? "live" : "needs_config";
              else if (raw === "planned" || raw === "soon") state = "planned";
              else if (raw === "live") state = "live";
              const id = row.id === "documents" ? "upload" : row.id === "web" ? "website" : row.id;
              return {
                id,
                title: row.title,
                blurb: row.blurb,
                state,
                setup_hint: row.setup_hint,
                interactive: LIVE_TABS.has(id),
              };
            })
          );
        }
      })
      .catch(() => {
        setBlobConfigured(false);
        setCatalog(FALLBACK_CATALOG);
      });
  }, []);

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
    // Large website crawls (hundreds of pages + weave) can exceed a few minutes.
    for (let i = 0; i < 900; i++) {
      const j = await api.job(workspaceId, jobId);
      setJob(j);
      const ev = (j.events || []) as Array<{ message?: string }>;
      const last = [...ev].reverse().find((e) => e.message);
      if (last?.message) setStatusText(last.message);
      if (j.result && (j.result as { demo_mode?: boolean }).demo_mode) setDemoMode(true);
      if (j.status === "completed" || j.status === "failed") {
        await refreshAgents().catch(() => undefined);
        return j;
      }
      if (i > 0 && i % 15 === 0) {
        await refreshAgents().catch(() => undefined);
      }
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
      setStatusText(`Crawling public pages on ${websiteUrl.trim()}…`);
      const ws = await ensureWorkspace();
      // Full public crawl: sitemap + same-host BFS (server defaults ~500 pages / depth 4)
      const j = await api.ingestUrl(ws, websiteUrl.trim(), {
        max_pages: 500,
        max_depth: 4,
      });
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

  async function runBlob() {
    if (!blobContainer.trim()) {
      setError("Enter an Azure Blob container name");
      return;
    }
    await runJob(async () => {
      setStatusText(`Syncing blob container ${blobContainer.trim()}…`);
      const ws = await ensureWorkspace();
      const j = await api.ingestBlob(ws, {
        container: blobContainer.trim(),
        prefix: blobPrefix.trim() || undefined,
      });
      return { ws, job: j, label: "Azure Blob" };
    });
  }

  const report = (job?.result?.cleanstack || null) as CleanStackReport | null;
  const impact = (job?.result?.impact || null) as Record<string, number> | null;
  const visibleCatalog = compact
    ? catalog.filter((s) => s.state === "live" || s.id === "blob")
    : catalog;
  const showPipeline = !compact || busy || Boolean(job);
  const activeTile = catalog.find((s) => s.id === tab);

  const sourceControls = (
    <>
      {!compact && (
        <p className="muted" style={{ marginTop: 0, marginBottom: "0.75rem" }}>
          VERA builds <strong>AI that works</strong> — answers only from knowledge you connect here,
          and says when the sources don’t cover the question. Hook Email & calendar so Ask can brief
          you on important mail, upcoming meetings, and summaries — same as Website or Files.
        </p>
      )}
      {activeTile && !LIVE_TABS.has(tab) && (
        <div className="source-pane">
          <p className="muted" style={{ marginTop: 0 }}>
            <strong>{activeTile.title}</strong> is provisioned in the connector registry but not
            wired for ingest yet. Same pattern as Blob/SharePoint: acquire → CleanStack → weave →
            Ask with proof.
          </p>
          {activeTile.setup_hint && (
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              Planned setup: {activeTile.setup_hint}
            </p>
          )}
          {plannedHint && (
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              {plannedHint}
            </p>
          )}
        </div>
      )}
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
              Enter the website homepage (example: https://www.thoughtworks.com). VERA will read up
              to about 500 public pages from that site.
              <br />
              <br />
              We keep pages like About, Leaders, News, and Services. We skip case studies, client
              stories, job listings, and glossary pages — those fill the crawl without helping Ask.
              Pages that need a login are skipped.
              <br />
              <br />
              If Ask still misses something important, crawl that section next (example: …/about-us
              or …/about-us/leaders).
            </p>
          )}
          <label className="field">
            <span>Website URL</span>
            <input
              type="url"
              placeholder="https://www.example.com"
              value={websiteUrl}
              disabled={busy}
              onChange={(e) => setWebsiteUrl(e.target.value)}
            />
          </label>
          <div className="cta-row">
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void runWebsite()}>
              {busy ? "Crawling public site…" : "Crawl public site"}
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

      {tab === "blob" && (
        <div className="source-pane">
          {!compact && (
            <p className="muted" style={{ marginTop: 0 }}>
              Sync files from an Azure Blob container into the same ingest pipeline as uploads.
              {!blobConfigured && (
                <>
                  {" "}
                  Set <code>VERA_AZURE_BLOB_CONNECTION_STRING</code> in the API env to enable
                  (see Configuration docs).
                </>
              )}
            </p>
          )}
          <label className="field">
            <span>Container</span>
            <input
              type="text"
              placeholder="knowledge-docs"
              value={blobContainer}
              disabled={busy}
              onChange={(e) => setBlobContainer(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Prefix (optional)</span>
            <input
              type="text"
              placeholder="policies/"
              value={blobPrefix}
              disabled={busy}
              onChange={(e) => setBlobPrefix(e.target.value)}
            />
          </label>
          <div className="cta-row">
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy || !blobConfigured}
              title={
                blobConfigured
                  ? "List and ingest blobs from the container"
                  : "Configure VERA_AZURE_BLOB_CONNECTION_STRING first"
              }
              onClick={() => void runBlob()}
            >
              {busy ? "Syncing blob…" : blobConfigured ? "Connect Azure Blob" : "Blob needs config"}
            </button>
          </div>
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
          {visibleCatalog.map((src) =>
            src.id && src.interactive ? (
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
              agentName={currentAgent?.name}
              jobType={job?.type}
              events={(job?.events as Array<Record<string, unknown>>) || []}
              progress={job?.progress || (busy ? 0.01 : 0)}
              status={job?.status || (busy ? "running" : undefined)}
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
        {visibleCatalog.map((src) => (
          <button
            key={src.title}
            type="button"
            className={`kb-tile ${src.id && tab === src.id ? "active" : ""} ${tileCssState(src.state)}`}
            disabled={busy}
            onClick={() => {
              if (!src.id) return;
              setTab(src.id);
              setPlannedHint(
                src.interactive
                  ? null
                  : src.setup_hint || "Reserved module — implement under app/knowledge/sources/."
              );
            }}
          >
            <strong>{src.title}</strong>
            <span>{src.blurb}</span>
            <em>{tileStateLabel(src.state)}</em>
          </button>
        ))}
      </div>
      <div className="grid-2">
        <div className="stack">
          <div className="panel">
            <div className="panel-head">
              <div>
                <h3>
                  {activeTile?.title || "Connect"}
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
              <p>
                Live progress for <strong>{currentAgent?.name || "this agent"}</strong> only — other
                agents stay isolated.
              </p>
            </div>
            {job?.status === "completed" && (
              <>
                <div className="metric-tile" style={{ minWidth: 110 }}>
                  <div className="label">Health</div>
                  <div className="value">{String(job.result?.health_score ?? "—")}</div>
                </div>
                {job.result?.ask_readiness && (
                  <div className="metric-tile" style={{ minWidth: 130 }}>
                    <div className="label">Ask ready</div>
                    <div className="value">
                      {String(
                        (job.result.ask_readiness as { status?: string }).status ?? "—"
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          <AgentPipelineProgress
            agentName={currentAgent?.name}
            jobType={job?.type}
            events={(job?.events as Array<Record<string, unknown>>) || []}
            progress={job?.progress || (busy ? 0.01 : 0)}
            status={job?.status || (busy ? "running" : undefined)}
            statusText={statusText}
          />
        </div>
      </div>
    </div>
  );
}
