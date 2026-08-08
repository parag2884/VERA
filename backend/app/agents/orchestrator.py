from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.agents.base import AgentContext, AgentError, AgentEvent, AgentResult
from app.agents.registry import AgentRegistry
from app.logging_utils import redact_mapping

logger = logging.getLogger(__name__)

StageHandler = Callable[[AgentContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PipelineStage:
    """Orchestrator-owned stage. Agents never choose the next hop."""

    id: str
    agent_id: str
    description: str = ""
    # Optional transform: (ctx, bag) -> validated input model instance
    input_builder: Callable[[AgentContext, dict[str, Any]], BaseModel] | None = None
    # Optional merge: (bag, agent_output_dict) -> bag updates
    output_merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    # Early-exit: return a terminal bag when truthy
    early_exit: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


@dataclass
class PipelineDefinition:
    id: str
    display_name: str
    stages: list[PipelineStage] = field(default_factory=list)


@dataclass
class PipelineRunResult:
    ok: bool
    pipeline_id: str
    bag: dict[str, Any]
    events: list[AgentEvent]
    stage_results: dict[str, AgentResult[Any]]
    error: AgentError | None = None
    demo_mode: bool = False


class PipelineOrchestrator:
    """Runs typed DAGs. Stage transitions are owned here — never by agent hints."""

    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self._pipelines: dict[str, PipelineDefinition] = {}

    def register_pipeline(self, pipeline: PipelineDefinition) -> None:
        self._pipelines[pipeline.id] = pipeline

    def get_pipeline(self, pipeline_id: str) -> PipelineDefinition:
        try:
            return self._pipelines[pipeline_id]
        except KeyError as exc:
            raise KeyError(f"Unknown pipeline: {pipeline_id}") from exc

    def list_pipelines(self) -> list[dict[str, str]]:
        return [
            {"id": p.id, "display_name": p.display_name}
            for p in self._pipelines.values()
        ]

    async def run(
        self,
        pipeline_id: str,
        ctx: AgentContext,
        initial: dict[str, Any] | None = None,
    ) -> PipelineRunResult:
        pipeline = self.get_pipeline(pipeline_id)
        bag: dict[str, Any] = dict(initial or {})
        stage_results: dict[str, AgentResult[Any]] = {}
        total = max(len(pipeline.stages), 1)

        ctx.emit(
            "orchestrator",
            "pipeline.start",
            f"Starting {pipeline.display_name}",
            progress=0.0,
            data={"pipeline_id": pipeline_id},
        )

        for index, stage in enumerate(pipeline.stages):
            progress = index / total
            ctx.emit(
                "orchestrator",
                f"stage.{stage.id}.start",
                stage.description or f"Running {stage.agent_id}",
                progress=progress,
                data={"stage_id": stage.id, "agent_id": stage.agent_id},
            )
            await self._flush_progress(ctx, progress)

            agent = self.registry.get(stage.agent_id)
            try:
                if stage.input_builder:
                    payload = stage.input_builder(ctx, bag)
                else:
                    payload = agent.input_model.model_validate(bag)

                # Validate type contract
                if not isinstance(payload, agent.input_model):
                    payload = agent.input_model.model_validate(payload)

                result = await agent.run(ctx, payload)
            except Exception as exc:  # noqa: BLE001 — boundary
                logger.exception("Agent %s failed", stage.agent_id)
                error = AgentError(
                    code="AGENT_EXCEPTION",
                    message=str(exc),
                    retryable=False,
                    details=redact_mapping({"agent_id": stage.agent_id}),
                )
                ctx.emit(
                    stage.agent_id,
                    f"stage.{stage.id}.error",
                    str(exc),
                    level="error",
                    progress=progress,
                )
                await self._flush_progress(ctx, progress)
                return PipelineRunResult(
                    ok=False,
                    pipeline_id=pipeline_id,
                    bag=bag,
                    events=list(ctx.event_sink),
                    stage_results=stage_results,
                    error=error,
                    demo_mode=ctx.demo_mode,
                )

            stage_results[stage.id] = result
            for event in result.events:
                ctx.event_sink.append(event)

            if not result.ok:
                ctx.emit(
                    stage.agent_id,
                    f"stage.{stage.id}.failed",
                    result.error.message if result.error else "Stage failed",
                    level="error",
                    progress=progress,
                )
                await self._flush_progress(ctx, progress)
                return PipelineRunResult(
                    ok=False,
                    pipeline_id=pipeline_id,
                    bag=bag,
                    events=list(ctx.event_sink),
                    stage_results=stage_results,
                    error=result.error
                    or AgentError(code="STAGE_FAILED", message=f"{stage.id} failed"),
                    demo_mode=ctx.demo_mode,
                )

            output_dict = result.data.model_dump() if result.data is not None else {}
            if stage.output_merger:
                bag.update(stage.output_merger(bag, output_dict))
            else:
                bag.update(output_dict)

            done_progress = (index + 1) / total
            ctx.emit(
                stage.agent_id,
                f"stage.{stage.id}.done",
                f"Completed {stage.agent_id}",
                progress=done_progress,
                data={"metrics": result.metrics},
            )
            await self._flush_progress(ctx, done_progress)

            if stage.early_exit:
                terminal = stage.early_exit(bag)
                if terminal is not None:
                    bag.update(terminal)
                    ctx.emit(
                        "orchestrator",
                        "pipeline.early_exit",
                        f"Early exit after {stage.id}",
                        progress=1.0,
                        data={"stage_id": stage.id},
                    )
                    await self._flush_progress(ctx, 1.0)
                    return PipelineRunResult(
                        ok=True,
                        pipeline_id=pipeline_id,
                        bag=bag,
                        events=list(ctx.event_sink),
                        stage_results=stage_results,
                        demo_mode=ctx.demo_mode,
                    )

        ctx.emit(
            "orchestrator",
            "pipeline.done",
            f"Finished {pipeline.display_name}",
            progress=1.0,
        )
        await self._flush_progress(ctx, 1.0)
        return PipelineRunResult(
            ok=True,
            pipeline_id=pipeline_id,
            bag=bag,
            events=list(ctx.event_sink),
            stage_results=stage_results,
            demo_mode=ctx.demo_mode,
        )

    async def _flush_progress(self, ctx: AgentContext, progress: float) -> None:
        """Persist live job progress so the UI isn't stuck at 5% during long stages."""
        cb = (ctx.config or {}).get("on_progress")
        if not callable(cb):
            return
        try:
            await cb(
                [e.model_dump(mode="json") for e in ctx.event_sink],
                float(progress),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Job progress flush failed")
