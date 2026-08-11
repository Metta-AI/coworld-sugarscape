from __future__ import annotations

from statistics import median
from time import perf_counter_ns
import random

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.instrumentation import EpisodeInstrumentation
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape
from sugarscape.sugarscape import Sugarscape


def _measure(agent: object, *, batches: int = 7, iterations: int = 150) -> int:
    samples: list[int] = []
    for batch in range(batches):
        random.seed(10_000 + batch)
        started = perf_counter_ns()
        for _ in range(iterations):
            agent.rankCellsInRange()
        samples.append(perf_counter_ns() - started)
    return int(median(samples))


def measure_ranking_overhead() -> tuple[int, int, float]:
    """Return median stock/custom nanoseconds and their ratio."""

    raw = {
        "seed": 73,
        "seats": 1,
        "timesteps": 1,
        "startingAgents": 30,
        "startingDiseases": 0,
        "environmentWidth": 20,
        "environmentHeight": 20,
        "environmentSugarPeaks": [[5, 14, 4], [14, 5, 4]],
        "environmentSpicePeaks": [[5, 5, 4], [14, 14, 4]],
        "agentAggressionFactor": [0, 0],
        "agentMovement": [6, 6],
        "agentVision": [6, 6],
    }
    resolved = resolve_episode_config(raw)
    dtl_config = build_dtl_config(resolved)
    random.seed(dtl_config["seed"])
    stock_world = Sugarscape(dtl_config)
    stock_agent = min(stock_world.agents, key=lambda agent: agent.ID)

    movement = compile_ruleset(
        {"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]}
    )
    ruleset_world = CoworldSugarscape(
        dtl_config,
        [movement],
        parse_trait_ranges(None),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )
    ruleset_agent = min(ruleset_world.agents, key=lambda agent: agent.ID)

    _measure(stock_agent, batches=1, iterations=20)
    _measure(ruleset_agent, batches=1, iterations=20)
    stock_ns = _measure(stock_agent)
    ruleset_ns = _measure(ruleset_agent)
    ratio = ruleset_ns / stock_ns

    return stock_ns, ruleset_ns, ratio


def test_sugarlang_ranking_overhead_is_at_most_twice_stock() -> None:
    _, _, ratio = measure_ranking_overhead()

    assert ratio <= 2.0, f"SugarLang ranking overhead was {ratio:.3f}x stock"
