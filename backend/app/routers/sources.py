from __future__ import annotations

import asyncio
import io
import mimetypes
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.base import AgentContext
from app.agents.ingest.contracts import AcquiredFile
from app.config import get_settings
from app.runtime import get_runtime
from app.schemas import JobOut, SharePointIngestRequest, UrlIngestRequest
from app.services.sharepoint_ingest import fetch_sharepoint, graph_configured
from app.services.web_ingest import fetch_website
from app.stores.sql import WorkspaceStore

router = APIRouter(prefix="/api/sources", tags=["sources"])

_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample_kb"
_SAMPLE_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


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


def _sample_kb_files() -> list[Path]:
    if not _SAMPLE_DIR.is_dir():
        return []
    return [
        p
        for p in sorted(_SAMPLE_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in _SAMPLE_SUFFIXES
    ]


_ZIP_MEMBER_SUFFIXES = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
}


def _expand_upload(filename: str, mime: str | None, raw: bytes) -> list[AcquiredFile]:
    """Expand .zip into supported member files; otherwise return a single file."""
    name = Path(filename or "upload.bin").name
    suffix = Path(name).suffix.lower()
    is_zip = suffix == ".zip" or (mime or "").lower() in {
        "application/zip",
        "application/x-zip-compressed",
    }
    if not is_zip:
        return [
            AcquiredFile(
                filename=name,
                mime=mime or mimetypes.guess_type(name)[0],
                content=raw,
                appears_at=f"upload://{name}",
            )
        ]

    settings = get_settings()
    out: list[AcquiredFile] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            members = [
                i
                for i in zf.infolist()
                if not i.is_dir()
                and not Path(i.filename).name.startswith(".")
                and "__MACOSX" not in i.filename.replace("\\", "/")
                and Path(i.filename).suffix.lower() in _ZIP_MEMBER_SUFFIXES
            ]
            if not members:
                raise HTTPException(
                    400,
                    f"{name} has no supported files inside "
                    f"({', '.join(sorted(_ZIP_MEMBER_SUFFIXES))})",
                )
            if len(members) > settings.vera_max_upload_files:
                raise HTTPException(
                    400,
                    f"{name} expands to {len(members)} files; "
                    f"max is {settings.vera_max_upload_files}",
                )
            for info in members:
                data = zf.read(info)
                if len(data) > settings.max_file_bytes:
                    raise HTTPException(
                        400,
                        f"{Path(info.filename).name} inside {name} exceeds "
                        f"{settings.vera_max_file_mb}MB limit",
                    )
                # Preserve nested folders from the zip (Foundry-style library layout)
                rel = info.filename.replace("\\", "/").lstrip("/")
                member_name = rel.replace("/", "__")
                guessed, _ = mimetypes.guess_type(Path(info.filename).name)
                out.append(
                    AcquiredFile(
                        filename=member_name,
                        mime=guessed,
                        content=data,
                        appears_at=f"upload://{name}/{rel}",
                    )
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, f"{name} is not a valid zip archive") from exc
    return out


async def _run_ingest(
    workspace_id: str,
    job_id: str,
    *,
    files: list[AcquiredFile] | None = None,
    sample: bool = False,
) -> None:
    runtime = get_runtime()
    settings = get_settings()
    upload_dir = settings.data_dir / "uploads" / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    async with WorkspaceStore() as store:
        await store.update_job(workspace_id, job_id, status="running", progress=0.05)

        async def on_progress(events: list, progress: float) -> None:
            await store.update_job(
                workspace_id,
                job_id,
                status="running",
                progress=max(0.05, min(0.99, progress)),
                events=events,
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
        events = [e.model_dump(mode="json") for e in result.events]
        if result.ok:
            cs = result.bag.get("cleanstack_report") or result.bag.get("report") or {}
            await store.update_job(
                workspace_id,
                job_id,
                status="completed",
                progress=1.0,
                result={
                    "cleanstack": cs,
                    "health_score": result.bag.get("score"),
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


async def _queue_ingest(workspace_id: str, acquired: list[AcquiredFile], job_type: str = "ingest") -> JobOut:
    if not acquired:
        raise HTTPException(400, "No supported files acquired from source")
    settings = get_settings()
    if len(acquired) > settings.vera_max_upload_files:
        raise HTTPException(
            400,
            f"Source expands to {len(acquired)} files; max is {settings.vera_max_upload_files}",
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
    try:
        acquired = await fetch_website(
            body.url,
            max_pages=body.max_pages,
            max_depth=body.max_depth,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Website ingest failed: {exc}") from exc
    return await _queue_ingest(body.workspace_id, acquired, job_type="ingest_url")


@router.post("/sharepoint", response_model=JobOut)
async def ingest_sharepoint(body: SharePointIngestRequest) -> JobOut:
    try:
        acquired = await fetch_sharepoint(body.url, demo=body.demo)
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"SharePoint ingest failed: {exc}") from exc
    return await _queue_ingest(body.workspace_id, acquired, job_type="ingest_sharepoint")


@router.get("/connectors")
async def list_connectors() -> dict:
    settings = get_settings()
    return {
        "upload": {
            "enabled": True,
            "max_file_mb": settings.vera_max_file_mb,
            "max_files": settings.vera_max_upload_files,
            "zip": True,
            "nested_folders": True,
        },
        "website": {
            "enabled": True,
            "max_pages": settings.vera_url_max_pages,
            "max_depth": settings.vera_url_max_depth,
        },
        "sharepoint": {
            "enabled": True,
            "graph_configured": graph_configured(),
            "demo_available": True,
            "recursive_folders": True,
        },
    }


@router.post("/sample", response_model=JobOut)
async def load_sample(workspace_id: str = Form(...)) -> JobOut:
    sample_files = _sample_kb_files()
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
