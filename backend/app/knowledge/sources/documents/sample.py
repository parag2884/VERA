"""Sample knowledge-base loader (documents connector)."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT
from app.knowledge.contracts import AcquiredFile, SourceAcquireResult

SAMPLE_DIR = BACKEND_ROOT / "app" / "data" / "sample_kb"
SAMPLE_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


def sample_kb_paths() -> list[Path]:
    if not SAMPLE_DIR.is_dir():
        return []
    return [
        p
        for p in sorted(SAMPLE_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in SAMPLE_SUFFIXES
    ]


def load_sample_files() -> list[AcquiredFile]:
    files: list[AcquiredFile] = []
    for path in sample_kb_paths():
        mime, _ = mimetypes.guess_type(path.name)
        files.append(
            AcquiredFile(
                filename=path.name,
                mime=mime or "text/plain",
                content=path.read_bytes(),
                appears_at=f"sample://{path.name}",
                source_kind="sample",
            )
        )
    return files


class SampleConnector:
    kind = "sample"

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        files = load_sample_files()
        if not files:
            raise FileNotFoundError(
                "Sample KB has nothing to load (folder missing or empty)."
            )
        return SourceAcquireResult(kind="sample", files=files, meta={"sample": True})

    def status(self) -> dict[str, Any]:
        paths = sample_kb_paths()
        return {
            "enabled": True,
            "state": "configured" if paths else "empty",
            "file_count": len(paths),
        }
