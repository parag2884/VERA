from __future__ import annotations

from pathlib import Path

from app.agents.base import AgentContext, AgentError, AgentResult, AgentWarning
from app.agents.ingest.contracts import AcquiredFile, ConnectInput, ConnectOutput
from app.knowledge.sources.documents.sample import load_sample_files


class ConnectAgent:
    id = "connect"
    display_name = "Connect Agent"
    input_model = ConnectInput
    output_model = ConnectOutput

    async def run(self, ctx: AgentContext, payload: ConnectInput) -> AgentResult[ConnectOutput]:
        files = list(payload.files)
        warnings: list[AgentWarning] = []

        if payload.sample:
            files = load_sample_files()
            if not files:
                return AgentResult(
                    ok=False,
                    error=AgentError(
                        code="SAMPLE_EMPTY",
                        message="Sample KB has no loadable files — nothing to ingest.",
                    ),
                )
            ctx.emit(self.id, "connect.sample", f"Loaded {len(files)} sample sources", progress=0.2)

        if not files:
            return AgentResult(
                ok=False,
                error=AgentError(code="NO_FILES", message="No source files acquired"),
            )

        # Persist raw bytes under workspace storage
        store_root: Path = ctx.config.get("upload_dir") or Path(".")
        store_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            safe_name = Path(f.filename).name.replace("..", "")
            dest = store_root / safe_name
            dest.write_bytes(f.content)
            f.storage_path = dest.as_posix()
            f.appears_at = f.appears_at or f"upload://{safe_name}"

        ctx.emit(self.id, "connect.done", f"Acquired {len(files)} source descriptors", progress=1.0)
        return AgentResult(
            ok=True,
            data=ConnectOutput(files=files, acquired_count=len(files)),
            warnings=warnings,
            metrics={"acquired": len(files)},
        )
