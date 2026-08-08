from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class AgentRegistry:
    """Plugin registry — swap mock/azure/connectors without touching routers."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent[Any, Any]] = {}

    def register(self, agent: Agent[Any, Any]) -> None:
        if agent.id in self._agents:
            raise ValueError(f"Agent already registered: {agent.id}")
        self._agents[agent.id] = agent

    def get(self, agent_id: str) -> Agent[Any, Any]:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {agent_id}") from exc

    def list(self) -> list[dict[str, str]]:
        return [
            {"id": a.id, "display_name": a.display_name}
            for a in sorted(self._agents.values(), key=lambda x: x.id)
        ]

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents
