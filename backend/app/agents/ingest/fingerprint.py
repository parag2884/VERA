from __future__ import annotations

import hashlib

from app.agents.base import AgentContext, AgentError, AgentResult
from app.agents.ingest.contracts import FingerprintInput, FingerprintOutput, FingerprintedFile


class FingerprintAgent:
    id = "fingerprint"
    display_name = "Fingerprint Agent"
    input_model = FingerprintInput
    output_model = FingerprintOutput

    async def run(
        self, ctx: AgentContext, payload: FingerprintInput
    ) -> AgentResult[FingerprintOutput]:
        store = ctx.stores
        if store is None:
            return AgentResult(
                ok=False,
                error=AgentError(code="NO_STORE", message="Workspace store required"),
            )

        out: list[FingerprintedFile] = []
        for f in payload.files:
            binary_hash = hashlib.sha256(f.content).hexdigest()
            source_id = await store.insert_source_instance(
                ctx.workspace_id,
                filename=f.filename,
                mime=f.mime,
                byte_size=len(f.content),
                binary_hash=binary_hash,
                storage_path=f.storage_path,
                appears_at=f.appears_at,
                status="fingerprinted",
            )
            out.append(
                FingerprintedFile(
                    source_id=source_id,
                    filename=f.filename,
                    mime=f.mime,
                    content=f.content,
                    binary_hash=binary_hash,
                    byte_size=len(f.content),
                    appears_at=f.appears_at,
                    storage_path=f.storage_path,
                )
            )

        await store.commit()
        ctx.emit(self.id, "fingerprint.done", f"Fingerprinted {len(out)} files", progress=1.0)
        return AgentResult(
            ok=True,
            data=FingerprintOutput(files=out),
            metrics={"fingerprinted": len(out)},
        )
