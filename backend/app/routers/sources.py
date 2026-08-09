from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.base import AgentContext
from app.config import get_settings
from app.knowledge.base import SourceNotConfiguredError
from app.knowledge.contracts import AcquiredFile
from app.knowledge.registry import get_connector, list_connector_status
from app.knowledge.sources.documents.sample import sample_kb_paths
from app.knowledge.sources.documents.upload import UploadExpandError, expand_upload
from app.knowledge.sources.web.crawl import fetch_website
from app.runtime import get_runtime
from app.schemas import (
    BlobIngestRequest,
    JobOut,
    SharePointIngestRequest,
    UrlIngestRequest,
)
from app.services.ask_readiness import evaluate_workspace_readiness
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/sources", tags=["sources"])


async def _ensure_ingest_slot(store: WorkspaceStore, workspace_id: str) -> None:
    """Reject new ingest while another weave is still queued/running for this agent."""
    active = await store.get_active_ingest_job(workspace_id)
    if not active:
        return
    raise HTTPException(
        409,
        "An ingest is already running for this agent. Wait for it to finish "
        f"(job {active.get('id', '')[:8]}…, {active.get('status')}) before starting another.",
    )


def _expand_upload(filename: str, mime: str | None, raw: bytes) -> list[AcquiredFile]:
    try:
        return expand_upload(filename, mime, raw)
    except UploadExpandError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _run_ingest(
    workspace_id: str,
    job_id: str,
    *,
    files: list[AcquiredFile] | None = None,
    sample: bool = False,
    prior_events: list[dict] | None = None,
    progress_floor: float = 0.05,
) -> None:
    runtime = get_runtime()
    settings = get_settings()
    upload_dir = settings.data_dir / "uploads" / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    floor = max(0.0, min(0.9, progress_floor))
    base_events = list(prior_events or [])

    async with WorkspaceStore() as store:
        await store.update_job(
            workspace_id,
            job_id,
            status="running",
            progress=max(floor, 0.05),
            events=base_events or None,
        )

        async def on_progress(events: list, progress: float) -> None:
            # Map pipeline 0..1 into [floor .. 0.99]
            mapped = floor + (0.99 - floor) * max(0.0, min(1.0, progress))
            merged = base_events + list(events)
            await store.update_job(
                workspace_id,
                job_id,
                status="running",
                progress=mapped,
                events=merged,
            )

        ctx = AgentContext(
            workspace_id=workspace_id,
            job_id=job_id,
            demo_mode=runtime.demo_mode,
            stores=store,
            llm=runtime.llm,
            config={
                "upload_dir": upload_dir,
                "vector_store": runtime.vector_store,
                "on_progress": on_progress,
            },
        )
        initial = {"sample": sample, "files": files or []}
        result = await runtime.orchestrator.run("ingest_pipeline", ctx, initial)
        pipe_events = [e.model_dump(mode="json") for e in result.events]
        events = base_events + pipe_events
        if result.ok:
            cs = result.bag.get("cleanstack_report") or result.bag.get("report") or {}
            # Post-ingest Ask readiness (OOD refuse + passage summary)
            ask_ready: dict = {}
            try:
                ask_ready = await evaluate_workspace_readiness(
                    runtime, store, workspace_id, run_live_asks=True
                )
                health = await store.get_health(workspace_id) or {}
                components = dict(health.get("components") or {})
                components["ask_readiness"] = ask_ready
                await store.save_health(
                    workspace_id,
                    float(health.get("score") or result.bag.get("score") or 0),
                    components,
                )
                events.append(
                    {
                        "agent_id": "ask_readiness",
                        "stage": "stage.readiness.done",
                        "message": (
                            f"Ask readiness: {ask_ready.get('status')} "
                            f"({ask_ready.get('passed')}/{ask_ready.get('total')} suite)"
                        ),
                        "progress": 1.0,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                ask_ready = {"status": "unknown", "error": str(exc)[:200]}
            await store.update_job(
                workspace_id,
                job_id,
                status="completed",
                progress=1.0,
                result={
                    "cleanstack": cs,
                    "health_score": result.bag.get("score"),
                    "ask_readiness": ask_ready,
                    "nodes_created": result.bag.get("nodes_created"),
                    "edges_created": result.bag.get("edges_created"),
                    "evidence_bound_edges": result.bag.get("evidence_bound_edges"),
                    "embedded_count": result.bag.get("embedded_count"),
                    "demo_mode": result.demo_mode or ctx.demo_mode,
                    "impact": {
                        "cleanstack_headline": cs.get("headline"),
                        "reduction_pct": cs.get("reduction_pct"),
                        "embeddings_avoided": cs.get("embeddings_avoided"),
                        "tokens_avoided": cs.get("tokens_avoided"),
                        "estimated_usd_avoided": cs.get("estimated_usd_avoided"),
                        "keepers": cs.get("keepers"),
                        "total_files": cs.get("total_files"),
                        "graph_nodes": result.bag.get("nodes_created"),
                        "graph_edges": result.bag.get("edges_created"),
                        "evidence_bound_edges": result.bag.get("evidence_bound_edges"),
                        "embedded_count": result.bag.get("embedded_count"),
                        "health_score": result.bag.get("score"),
                        "ask_status": ask_ready.get("status"),
                        "ask_pass_rate": ask_ready.get("pass_rate"),
                        "passage": ask_ready.get("passage"),
                    },
                },
                events=events,
            )
        else:
            await store.update_job(
                workspace_id,
                job_id,
                status="failed",
                progress=1.0,
                error=result.error.message if result.error else "ingest failed",
                events=events,
            )


async def _run_url_ingest(
    workspace_id: str,
    job_id: str,
    *,
    url: str,
    max_pages: int | None,
    max_depth: int | None,
) -> None:
    """Crawl publicly, stream progress, then run the shared ingest pipeline."""
    settings = get_settings()
    crawl_events: list[dict] = [
        {
            "agent_id": "crawl",
            "stage": "stage.crawl.start",
            "message": f"Crawling public pages on {url}…",
            "progress": 0.02,
        }
    ]

    async with WorkspaceStore() as store:
        await store.update_job(
            workspace_id,
            job_id,
            status="running",
            progress=0.02,
            events=crawl_events,
        )

        last_crawl: dict = {}

        async def on_crawl(info: dict) -> None:
            last_crawl.update(info)
            pages = int(info.get("pages") or 0)
            mx = max(1, int(info.get("max_pages") or 1))
            checked = int(info.get("checked") or 0)
            queued = int(info.get("queued") or 0)
            rendered_js = int(info.get("rendered_js") or 0)
            skipped_thin = int(info.get("skipped_thin") or 0)
            current = str(info.get("url") or "")
            frac = min(1.0, pages / mx)
            # Crawl occupies ~2% → 30% of the job bar
            prog = 0.02 + 0.28 * frac
            short = current.replace("https://", "").replace("http://", "")
            if len(short) > 64:
                short = short[:61] + "…"
            msg = f"Crawled {pages}/{mx} pages"
            if checked:
                msg += f" · checked {checked}"
            if queued:
                msg += f" · queue {queued}"
            if rendered_js:
                msg += f" · JS render {rendered_js}"
            if skipped_thin:
                msg += f" · skipped thin {skipped_thin}"
            if short:
                msg += f" · {short}"
            crawl_events[:] = [
                {
                    "agent_id": "crawl",
                    "stage": "stage.crawl.start",
                    "message": msg,
                    "progress": prog,
                    "pages": pages,
                    "max_pages": mx,
                    "rendered_js": rendered_js,
                    "skipped_thin": skipped_thin,
                }
            ]
            await store.update_job(
                workspace_id,
                job_id,
                status="running",
                progress=prog,
                events=list(crawl_events),
            )

        try:
            acquired = await fetch_website(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
                on_progress=on_crawl,
            )
        except Exception as exc:  # noqa: BLE001
            crawl_events.append(
                {
                    "agent_id": "crawl",
                    "stage": "stage.crawl.failed",
                    "message": str(exc),
                    "level": "error",
                }
            )
            await store.update_job(
                workspace_id,
                job_id,
                status="failed",
                progress=1.0,
                error=f"Website ingest failed: {exc}",
                events=list(crawl_events),
            )
            return

        if not acquired:
            skipped = int(last_crawl.get("skipped_thin") or 0)
            rendered = int(last_crawl.get("rendered_js") or 0)
            if skipped:
                err = (
                    "Reached the site but found no extractable page body "
                    f"(skipped {skipped} thin/JS shell page(s)"
                    + (f", Playwright rendered {rendered}" if rendered else "")
                    + "). Upload a PDF/doc or try a URL with static content — "
                    "nav-only shells are never stored as knowledge."
                )
            else:
                err = "No supported public pages acquired from website"
            await store.update_job(
                workspace_id,
                job_id,
                status="failed",
                progress=1.0,
                error=err,
                events=list(crawl_events)
                + [
                    {
                        "agent_id": "crawl",
                        "stage": "stage.crawl.failed",
                        "message": err,
                        "level": "error",
                        "skipped_thin": skipped,
                        "rendered_js": rendered,
                    }
                ],
            )
            return

        max_files = _max_acquired_files("ingest_url")
        if len(acquired) > max_files:
            await store.update_job(
                workspace_id,
                job_id,
                status="failed",
                progress=1.0,
                error=f"Source expands to {len(acquired)} files; max is {max_files}",
                events=list(crawl_events),
            )
            return

        crawl_events[:] = [
            {
                "agent_id": "crawl",
                "stage": "stage.crawl.done",
                "message": (
                    f"Crawl complete — {len(acquired)} pages ready for CleanStack / Graph Weaver"
                ),
                "progress": 0.30,
                "pages": len(acquired),
                "max_pages": max_pages or settings.vera_url_max_pages,
            }
        ]
        await store.update_job(
            workspace_id,
            job_id,
            status="running",
            progress=0.30,
            events=list(crawl_events),
        )

    await _run_ingest(
        workspace_id,
        job_id,
        files=acquired,
        sample=False,
        prior_events=list(crawl_events),
        progress_floor=0.30,
    )


@router.post("/upload", response_model=JobOut)
async def upload_sources(
    workspace_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> JobOut:
    settings = get_settings()
    if len(files) > settings.vera_max_upload_files:
        raise HTTPException(400, f"Max {settings.vera_max_upload_files} files")

    acquired: list[AcquiredFile] = []
    for f in files:
        raw = await f.read()
        if len(raw) > settings.max_file_bytes:
            raise HTTPException(
                400,
                f"{f.filename} exceeds {settings.vera_max_file_mb}MB size limit",
            )
        acquired.extend(_expand_upload(f.filename or "upload.bin", f.content_type, raw))

    if len(acquired) > settings.vera_max_upload_files:
        raise HTTPException(
            400,
            f"Upload expands to {len(acquired)} files; "
            f"max is {settings.vera_max_upload_files}",
        )
    if not acquired:
        raise HTTPException(400, "No supported files in upload")

    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        await _ensure_ingest_slot(store, workspace_id)
        job = await store.create_job(workspace_id, "ingest")

    asyncio.create_task(_run_ingest(workspace_id, job["id"], files=acquired, sample=False))
    return JobOut(
        id=job["id"],
        workspace_id=workspace_id,
        type="ingest",
        status="queued",
        progress=0.0,
    )


def _max_acquired_files(job_type: str) -> int:
    """Upload zip stays at vera_max_upload_files; website crawl may be much larger."""
    settings = get_settings()
    if job_type == "ingest_url":
        return max(settings.vera_max_upload_files, settings.vera_url_hard_max_pages)
    return settings.vera_max_upload_files


async def _queue_ingest(workspace_id: str, acquired: list[AcquiredFile], job_type: str = "ingest") -> JobOut:
    if not acquired:
        raise HTTPException(400, "No supported files acquired from source")
    max_files = _max_acquired_files(job_type)
    if len(acquired) > max_files:
        raise HTTPException(
            400,
            f"Source expands to {len(acquired)} files; max is {max_files}",
        )
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        await _ensure_ingest_slot(store, workspace_id)
        job = await store.create_job(workspace_id, job_type)
    asyncio.create_task(_run_ingest(workspace_id, job["id"], files=acquired, sample=False))
    return JobOut(
        id=job["id"],
        workspace_id=workspace_id,
        type=job_type,
        status="queued",
        progress=0.0,
    )


@router.post("/url", response_model=JobOut)
async def ingest_website(body: UrlIngestRequest) -> JobOut:
    """Queue URL crawl + ingest immediately so the UI can poll live progress."""
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(body.workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        await _ensure_ingest_slot(store, body.workspace_id)
        job = await store.create_job(body.workspace_id, "ingest_url")
        await store.update_job(
            body.workspace_id,
            job["id"],
            status="running",
            progress=0.01,
            events=[
                {
                    "agent_id": "crawl",
                    "stage": "stage.crawl.start",
                    "message": f"Starting crawl of {body.url}…",
                    "progress": 0.01,
                }
            ],
        )
    asyncio.create_task(
        _run_url_ingest(
            body.workspace_id,
            job["id"],
            url=body.url,
            max_pages=body.max_pages,
            max_depth=body.max_depth,
        )
    )
    return JobOut(
        id=job["id"],
        workspace_id=body.workspace_id,
        type="ingest_url",
        status="running",
        progress=0.01,
        events=[
            {
                "agent_id": "crawl",
                "stage": "stage.crawl.start",
                "message": f"Starting crawl of {body.url}…",
                "progress": 0.01,
            }
        ],
    )


@router.post("/sharepoint", response_model=JobOut)
async def ingest_sharepoint(body: SharePointIngestRequest) -> JobOut:
    try:
        result = await get_connector("sharepoint").acquire(url=body.url, demo=body.demo)
        acquired = result.files
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"SharePoint ingest failed: {exc}") from exc
    return await _queue_ingest(body.workspace_id, acquired, job_type="ingest_sharepoint")


@router.post("/blob", response_model=JobOut)
async def ingest_blob(body: BlobIngestRequest) -> JobOut:
    try:
        result = await get_connector("blob").acquire(
            container=body.container,
            prefix=body.prefix,
        )
    except SourceNotConfiguredError as exc:
        raise HTTPException(
            501,
            detail={
                "code": "BLOB_NOT_CONFIGURED",
                "message": str(exc),
                "setup_hint": exc.setup_hint,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not result.files:
        raise HTTPException(
            501,
            detail={
                "code": "BLOB_SDK_PENDING",
                "message": (
                    "Blob connector is configured but list/download is not enabled yet. "
                    "See app/knowledge/sources/blob/README.md."
                ),
            },
        )
    return await _queue_ingest(body.workspace_id, result.files, job_type="ingest_blob")


@router.get("/connectors")
async def list_connectors() -> dict:
    return list_connector_status()


@router.post("/sample", response_model=JobOut)
async def load_sample(workspace_id: str = Form(...)) -> JobOut:
    sample_files = sample_kb_paths()
    if not sample_files:
        raise HTTPException(
            400,
            "Sample KB has nothing to load (folder missing or empty). "
            "Upload your own documents instead.",
        )
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        await _ensure_ingest_slot(store, workspace_id)
        job = await store.create_job(workspace_id, "ingest_sample")

    asyncio.create_task(_run_ingest(workspace_id, job["id"], sample=True))
    return JobOut(
        id=job["id"],
        workspace_id=workspace_id,
        type="ingest_sample",
        status="queued",
        progress=0.0,
    )


@router.get("/cleanstack/{workspace_id}")
async def latest_cleanstack(workspace_id: str) -> dict:
    async with WorkspaceStore() as store:
        ws = await store.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        report = await store.get_latest_cleanstack_report(workspace_id)
    if not report:
        return {"ok": False, "report": None}
    return {"ok": True, "report": report}


@router.get("/jobs/{workspace_id}/{job_id}", response_model=JobOut)
async def get_job(workspace_id: str, job_id: str) -> JobOut:
    async with WorkspaceStore() as store:
        job = await store.get_job(workspace_id, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JobOut(
        id=job["id"],
        workspace_id=job["workspace_id"],
        type=job["type"],
        status=job["status"],
        progress=job["progress"],
        error=job.get("error"),
        result=job.get("result") or {},
        events=job.get("events") or [],
    )
