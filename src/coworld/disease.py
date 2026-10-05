"""Apply disease modifiers once per infection, including incubation and death."""

from __future__ import annotations

from typing import Any

from . import dtl


class Disease(dtl.condition_module.Disease):
    """Keep upstream transmission and immunity without stacking active penalties."""

    def __init__(self, diseaseID: int | str, configuration: dict[str, Any]) -> None:
        super().__init__(diseaseID, configuration)
        self._active_agents: set[dtl.Agent] = set()

    def trigger(self, agent: dtl.Agent) -> None:
        if agent in self._active_agents:
            return
        super().trigger(agent)
        self._active_agents.add(agent)

    def recover(self, agent: dtl.Agent) -> None:
        if agent in self._active_agents:
            super().recover(agent)
            self._active_agents.remove(agent)
        else:
            # An incubating infection has not applied any modifiers.
            self.infected.remove(agent)


class ZombieVirus(Disease, dtl.condition_module.ZombieVirus):
    """Use the same activation lifecycle with upstream zombie configuration."""
