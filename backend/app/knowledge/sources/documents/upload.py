"""Upload / zip expansion for document knowledge sources."""

from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.knowledge.contracts import AcquiredFile, SourceAcquireResult

ZIP_MEMBER_SUFFIXES = {
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


class UploadExpandError(ValueError):
    """Invalid or oversized upload / zip contents."""


def expand_upload(filename: str, mime: str | None, raw: bytes) -> list[AcquiredFile]:
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
                source_kind="documents",
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
                and Path(i.filename).suffix.lower() in ZIP_MEMBER_SUFFIXES
            ]
            if not members:
                raise UploadExpandError(
                    f"{name} has no supported files inside "
                    f"({', '.join(sorted(ZIP_MEMBER_SUFFIXES))})"
                )
            if len(members) > settings.vera_max_upload_files:
                raise UploadExpandError(
                    f"{name} expands to {len(members)} files; "
                    f"max is {settings.vera_max_upload_files}"
                )
            for info in members:
                data = zf.read(info)
                if len(data) > settings.max_file_bytes:
                    raise UploadExpandError(
                        f"{Path(info.filename).name} inside {name} exceeds "
                        f"{settings.vera_max_file_mb}MB limit"
                    )
                rel = info.filename.replace("\\", "/").lstrip("/")
                member_name = rel.replace("/", "__")
                guessed, _ = mimetypes.guess_type(Path(info.filename).name)
                out.append(
                    AcquiredFile(
                        filename=member_name,
                        mime=guessed,
                        content=data,
                        appears_at=f"upload://{name}/{rel}",
                        source_kind="documents",
                    )
                )
    except zipfile.BadZipFile as exc:
        raise UploadExpandError(f"{name} is not a valid zip archive") from exc
    return out


class DocumentsConnector:
    kind = "documents"

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        """Acquire from raw upload parts: list[{filename, mime, content}]."""
        parts = kwargs.get("parts") or []
        files: list[AcquiredFile] = []
        for part in parts:
            files.extend(
                expand_upload(
                    part.get("filename") or "upload.bin",
                    part.get("mime"),
                    part.get("content") or b"",
                )
            )
        settings = get_settings()
        if len(files) > settings.vera_max_upload_files:
            raise UploadExpandError(
                f"Upload expands to {len(files)} files; "
                f"max is {settings.vera_max_upload_files}"
            )
        if not files:
            raise UploadExpandError("No supported files in upload")
        return SourceAcquireResult(kind="documents", files=files)

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "enabled": True,
            "state": "configured",
            "max_file_mb": settings.vera_max_file_mb,
            "max_files": settings.vera_max_upload_files,
            "zip": True,
            "nested_folders": True,
            "formats": sorted(ZIP_MEMBER_SUFFIXES),
        }
