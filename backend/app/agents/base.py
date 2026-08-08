from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    stage: str
    message: str
    level: str = "info"
    progress: float | None = None
    ts: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentWarning(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel, Generic[OutputT]):
    ok: bool
    data: OutputT | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    warnings: list[AgentWarning] = Field(default_factory=list)
    error: AgentError | None = None


@dataclass
class AgentContext:
    """Shared execution context. Storage access is always workspace-scoped."""

    workspace_id: str
    job_id: str | None = None
    assistant_id: str | None = None
    demo_mode: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    stores: Any = None
    llm: Any = None
    event_sink: list[AgentEvent] = field(default_factory=list)

    def emit(
        self,
        agent_id: str,
        stage: str,
        message: str,
        *,
        level: str = "info",
        progress: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            agent_id=agent_id,
            stage=stage,
            message=message,
            level=level,
            progress=progress,
            data=data or {},
        )
        self.event_sink.append(event)
        return event

    async def flush_job_progress(self, progress: float | None = None) -> None:
        cb = (self.config or {}).get("on_progress")
        if not callable(cb):
            return
        prog = progress
        if prog is None:
            for ev in reversed(self.event_sink):
                if ev.progress is not None:
                    prog = ev.progress
                    break
        await cb(
            [e.model_dump(mode="json") for e in self.event_sink],
            float(prog if prog is not None else 0.5),
        )


@runtime_checkable
class Agent(Protocol, Generic[InputT, OutputT]):
    id: str
    display_name: str
    input_model: type[InputT]
    output_model: type[OutputT]

    async def run(self, ctx: AgentContext, payload: InputT) -> AgentResult[OutputT]:
        ...
