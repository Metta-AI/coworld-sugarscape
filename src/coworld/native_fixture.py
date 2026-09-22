"""Reference configuration for native v2 parity and throughput measurements."""

from __future__ import annotations

from .config import build_dtl_config, resolve_episode_config
from .instrumentation import EpisodeInstrumentation
from .ruleset import compile_ruleset
from .seats import parse_trait_ranges
from .simulation import CoworldSugarscape


class NativeReferenceWorld(CoworldSugarscape):
    """Retain DTL death events before its statistics pass clears them."""

    native_deaths: tuple[tuple[int, int, int, str], ...] = ()

    def updateRuntimeStats(self) -> None:
        self.native_deaths = tuple(
            (agent.ID, agent.seat, agent.age, agent.causeOfDeath)
            for agent in self.deadAgents
        )
        super().updateRuntimeStats()


def native_v2_config(*, seed: int = 1729, timesteps: int = 10_000) -> dict[str, object]:
    return {
        "seed": seed,
        "seats": 2,
        "timesteps": timesteps,
        "startingAgents": 4,
        "startingDiseases": 0,
        "agentAggressionFactor": [0, 0],
        "agentDecisionModelFactor": [0, 0],
        "agentFertilityFactor": [0, 0],
        "agentImmuneSystemLength": 0,
        "agentLendingFactor": [0, 0],
        "agentLookaheadFactor": [0, 0],
        "agentMaleToFemaleRatio": 0,
        "agentMaxAge": [-1, -1],
        "agentMovement": [1, 2],
        "agentRacialTagStringLength": 0,
        "agentSpiceMetabolism": [0, 0],
        "agentStartingSpice": [0, 0],
        "agentStartingSugar": [100, 100],
        "agentSugarMetabolism": [1, 1],
        "agentTagging": False,
        "agentTagStringLength": 0,
        "agentTradeFactor": [0, 0],
        "agentUniversalSpice": [0, 0],
        "agentUniversalSugar": [0, 0],
        "agentVision": [1, 2],
        "environmentHeight": 7,
        "environmentMaxSpice": 0,
        "environmentMaxSugar": 4,
        "environmentPollutionDiffusionDelay": 0,
        "environmentPollutionTimeframe": [0, 0],
        "environmentSeasonInterval": 0,
        "environmentSpicePeaks": [[2, 2, 0], [4, 4, 0]],
        "environmentSpiceRegrowRate": 0,
        "environmentSugarPeaks": [[2, 4, 4], [4, 2, 4]],
        "environmentSugarRegrowRate": 1,
        "environmentWidth": 7,
        "environmentWraparound": True,
    }


def build_native_v2_reference_world(
    *, seed: int = 1729, timesteps: int = 10_000
) -> CoworldSugarscape:
    resolved = resolve_episode_config(native_v2_config(seed=seed, timesteps=timesteps))
    return NativeReferenceWorld(
        build_dtl_config(resolved),
        [compile_ruleset(None) for _ in range(int(resolved["seats"]))],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )
