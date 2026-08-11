"""Synchronous Sugarscape world integration for compiled player rulesets."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Sequence

from sugarscape.sugarscape import Sugarscape

from .instrumentation import EpisodeInstrumentation, timed_subphase
from .measurement import RollingMeasurements
from .ruleset import CompiledRuleset
from .ruleset_agent import RulesetAgent
from .seats import SeatManager, TraitRange


@dataclass(slots=True)
class WorldFeatureCache:
    """World features shared by every candidate evaluation in one tick."""

    timestep: int = 0
    population: int = 0
    gini: float = 0.0
    mean_wealth: float = 0.0


class CoworldSugarscape(Sugarscape):
    """DTL Sugarscape with seat-aware agents and non-invasive timings."""

    def __init__(
        self,
        configuration: dict[str, object],
        compiled_rulesets: Sequence[CompiledRuleset],
        trait_ranges: dict[str, TraitRange],
        *,
        instrumentation: EpisodeInstrumentation | None = None,
        measurements: RollingMeasurements | None = None,
    ) -> None:
        self.instrumentation = instrumentation or EpisodeInstrumentation(enabled=False)
        self.measurements = measurements
        self.replay_writer = None
        self.world_features = WorldFeatureCache()
        self.seat_manager = SeatManager(len(compiled_rulesets), compiled_rulesets, trait_ranges)
        # This is the single seed point for the process-global DTL RNG stream.
        random.seed(configuration["seed"])
        super().__init__(configuration, agent_factory=RulesetAgent)
        self._environment_timestep = self.environment.doTimestep
        self.environment.doTimestep = self._timed_environment_timestep

    def doTimestep(self) -> None:
        """Publish current/T-1 world features, then delegate the tick to DTL."""

        next_tick = self.timestep + 1
        self.world_features.timestep = next_tick
        self.world_features.population = len(self.agents)
        self.world_features.gini = self.runtimeStats["giniCoefficient"]
        self.world_features.mean_wealth = self.runtimeStats["meanWealth"]
        started = self.instrumentation.begin_tick(next_tick)
        try:
            super().doTimestep()
            if self.measurements is not None:
                with timed_subphase(self.instrumentation, "measurement"):
                    self.measurements.record_tick(self)
            if self.replay_writer is not None:
                with timed_subphase(self.instrumentation, "replay_frame"):
                    self.replay_writer.capture_frame(self)
        finally:
            self.instrumentation.end_tick(started)

    def removeDeadAgents(self) -> None:
        """Capture death events after DTL fixes removal order but before stats clear them."""

        super().removeDeadAgents()
        if self.measurements is not None:
            self.measurements.record_deaths(self.deadAgents)

    def replaceDeadAgents(self) -> None:
        """Queue the first K dead seats before DTL creates replacements."""

        replacement_count = max(0, self.configuration["agentReplacements"] - len(self.agents))
        if replacement_count:
            self.seat_manager.queue_replacements(self.deadAgents, replacement_count)
        super().replaceDeadAgents()

    def updateRuntimeStats(self) -> None:
        with timed_subphase(self.instrumentation, "statistics"):
            super().updateRuntimeStats()

    def _timed_environment_timestep(self, timestep: int) -> None:
        with timed_subphase(self.instrumentation, "environment"):
            self._environment_timestep(timestep)
