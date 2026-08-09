"""SharePoint / OneDrive-style library ingest (Graph when configured, demo otherwise)."""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import BACKEND_ROOT, get_settings
from app.knowledge.contracts import AcquiredFile

logger = logging.getLogger(__name__)

DEMO_ROOT = BACKEND_ROOT / "app" / "data" / "sample_sharepoint"

_SUPPORTED = {
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


def graph_configured() -> bool:
    s = get_settings()
    return bool(s.vera_ms_tenant_id and s.vera_ms_client_id and s.vera_ms_client_secret)


async def _graph_token() -> str:
    s = get_settings()
    url = f"https://login.microsoftonline.com/{s.vera_ms_tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            data={
                "client_id": s.vera_ms_client_id,
                "client_secret": s.vera_ms_client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def _parse_sharepoint_url(url: str) -> dict[str, str]:
    """Best-effort parse of SharePoint site + folder path."""
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    p = urlparse(raw)
    host = p.netloc
    path = unquote(p.path or "/")

    site = ""
    folder = ""
    m = re.search(r"/sites/([^/]+)", path, re.I)
    if m:
        site = m.group(1)
        rest = path[m.end() :]
        # Drop Forms/AllItems.aspx etc.
        rest = re.sub(r"/Forms/.*$", "", rest, flags=re.I)
        rest = rest.strip("/")
        # Shared Documents / Shared%20Documents
        rest = re.sub(r"^Shared Documents/?", "", rest, flags=re.I)
        folder = rest
    return {"host": host, "site": site, "folder": folder, "url": raw}


async def fetch_sharepoint_graph(url: str) -> list[AcquiredFile]:
    """Recursively download supported files under a SharePoint library/folder via Graph."""
    settings = get_settings()
    parsed = _parse_sharepoint_url(url)
    if not parsed["site"]:
        raise ValueError(
            "Could not parse SharePoint site from URL. "
            "Expected …sharepoint.com/sites/{SiteName}/…"
        )
    token = await _graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    hostname = parsed["host"]
    site_name = parsed["site"]
    folder = parsed["folder"]

    async with httpx.AsyncClient(timeout=60.0, headers=headers, follow_redirects=True) as client:
        site_resp = await client.get(
            f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{site_name}"
        )
        if site_resp.status_code >= 400:
            raise ValueError(
                f"Graph site lookup failed ({site_resp.status_code}). "
                "Ensure the app has Sites.Read.All and the site URL is correct."
            )
        site_id = site_resp.json()["id"]
        drive_resp = await client.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        )
        drive_resp.raise_for_status()
        drive_id = drive_resp.json()["id"]

        if folder:
            root_path = f"/root:/{folder}:"
            children_url = (
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}{root_path}/children"
            )
        else:
            children_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"

        files: list[AcquiredFile] = []
        await _walk_drive_children(client, drive_id, children_url, "", files, settings)
        return files


async def _walk_drive_children(
    client: httpx.AsyncClient,
    drive_id: str,
    children_url: str,
    rel_prefix: str,
    out: list[AcquiredFile],
    settings: Any,
) -> None:
    url = children_url
    while url and len(out) < settings.vera_max_upload_files:
        resp = await client.get(url)
        if resp.status_code >= 400:
            logger.warning("drive list failed %s: %s", url, resp.text[:200])
            break
        data = resp.json()
        for item in data.get("value") or []:
            name = item.get("name") or "item"
            if item.get("folder") is not None:
                child_id = item["id"]
                next_url = (
                    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/"
                    f"{child_id}/children"
                )
                await _walk_drive_children(
                    client,
                    drive_id,
                    next_url,
                    f"{rel_prefix}{name}/",
                    out,
                    settings,
                )
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in _SUPPORTED:
                continue
            item_id = item["id"]
            content_url = (
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
            )
            bin_resp = await client.get(content_url)
            if bin_resp.status_code >= 400:
                continue
            raw = bin_resp.content
            if len(raw) > settings.max_file_bytes:
                logger.info("skip oversized %s", name)
                continue
            rel = f"{rel_prefix}{name}"
            mime, _ = mimetypes.guess_type(name)
            # Preserve folder path in filename for CleanStack/display
            safe = rel.replace("\\", "/").replace("/", "__")
            out.append(
                AcquiredFile(
                    filename=safe,
                    mime=mime,
                    content=raw,
                    appears_at=f"sharepoint://{rel}",
                    source_kind="sharepoint",
                )
            )
            if len(out) >= settings.vera_max_upload_files:
                return
        url = data.get("@odata.nextLink")


def load_sharepoint_demo() -> list[AcquiredFile]:
    """Nested folder demo library when Graph credentials are absent."""
    root = DEMO_ROOT
    if not root.exists():
        raise FileNotFoundError("Demo SharePoint library missing")
    files: list[AcquiredFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SUPPORTED:
            continue
        rel = path.relative_to(root).as_posix()
        mime, _ = mimetypes.guess_type(path.name)
        files.append(
            AcquiredFile(
                filename=rel.replace("/", "__"),
                mime=mime,
                content=path.read_bytes(),
                appears_at=f"sharepoint-demo://{rel}",
                source_kind="sharepoint",
            )
        )
    return files


async def fetch_sharepoint(url: str | None, *, demo: bool = False) -> list[AcquiredFile]:
    if demo or (not url and not graph_configured()):
        return load_sharepoint_demo()
    if not graph_configured():
        raise ValueError(
            "SharePoint Graph is not configured. Set VERA_MS_TENANT_ID, "
            "VERA_MS_CLIENT_ID, VERA_MS_CLIENT_SECRET — or use Demo library."
        )
    if not url:
        raise ValueError("SharePoint URL is required")
    return await fetch_sharepoint_graph(url)
