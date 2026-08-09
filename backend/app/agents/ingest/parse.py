from __future__ import annotations

import hashlib
import logging

from app.agents.base import AgentContext, AgentError, AgentResult, AgentWarning
from app.agents.ingest.contracts import ParseInput, ParseOutput, ParsedFile
from app.knowledge.sources.documents.parse_docs import (
    extract_document_text,
    needs_ocr_emit,
)

logger = logging.getLogger(__name__)


class ParseAgent:
    id = "parse"
    display_name = "Parse Agent"
    input_model = ParseInput
    output_model = ParseOutput

    async def run(self, ctx: AgentContext, payload: ParseInput) -> AgentResult[ParseOutput]:
        store = ctx.stores
        parsed: list[ParsedFile] = []
        warnings: list[AgentWarning] = []

        for f in payload.files:
            try:
                ctx.emit(self.id, "parse.file", f"Parsing {f.filename}", progress=0.2)
                await ctx.flush_job_progress(0.2)
                if needs_ocr_emit(f.filename, f.mime, f.content):
                    ctx.emit(
                        self.id,
                        "parse.ocr",
                        f"OCR / scanned content — {f.filename}",
                        progress=0.28,
                    )
                    await ctx.flush_job_progress(0.28)
                text, structure = extract_document_text(f.filename, f.mime, f.content)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Parse failed for %s: %s", f.filename, exc)
                warnings.append(
                    AgentWarning(code="PARSE_FAIL", message=f"{f.filename}: {exc}")
                )
                text, structure = "", {"error": str(exc)}

            text = text.strip()
            text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            if store is not None:
                await store.update_source_instance(
                    ctx.workspace_id,
                    f.source_id,
                    text_hash=text_hash,
                    status="parsed",
                )

            file_warnings: list[str] = []
            if not text:
                file_warnings.append("empty_extract")
            if structure.get("ocr"):
                file_warnings.append("ocr_used")
                warnings.append(
                    AgentWarning(
                        code="OCR_USED",
                        message=f"{f.filename}: used OCR ({structure.get('ocr_pages', 0)} pages)",
                    )
                )

            parsed.append(
                ParsedFile(
                    source_id=f.source_id,
                    filename=f.filename,
                    mime=f.mime,
                    text=text,
                    binary_hash=f.binary_hash,
                    text_hash=text_hash,
                    byte_size=f.byte_size,
                    appears_at=f.appears_at,
                    structure=structure,
                    warnings=file_warnings,
                )
            )

        if store is not None:
            await store.commit()

        nonempty = sum(1 for p in parsed if p.text)
        if nonempty == 0:
            return AgentResult(
                ok=False,
                error=AgentError(
                    code="PARSE_EMPTY",
                    message=(
                        "No extractable text even after OCR. "
                        "Check the file is a readable PDF/image (not blank or encrypted)."
                    ),
                ),
                warnings=warnings,
            )

        ctx.emit(self.id, "parse.done", f"Parsed {nonempty}/{len(parsed)} files", progress=1.0)
        await ctx.flush_job_progress(0.35)
        return AgentResult(
            ok=True,
            data=ParseOutput(files=parsed),
            warnings=warnings,
            metrics={"parsed": nonempty, "total": len(parsed)},
        )
