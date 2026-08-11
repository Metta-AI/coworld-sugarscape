from __future__ import annotations

import random

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.instrumentation import EpisodeInstrumentation
from coworld.ruleset import compile_ruleset
from coworld.ruleset_agent import RulesetAgent
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape
from sugarscape.sugarscape import Sugarscape


def _world(config: dict[str, object], rulesets: list[object]) -> CoworldSugarscape:
    resolved = resolve_episode_config(config)
    return CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset) for ruleset in rulesets],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )


def _snapshot(world: Sugarscape) -> tuple[object, ...]:
    agents = tuple(
        sorted(
            (
                agent.ID,
                agent.cell.x,
                agent.cell.y,
                agent.sugar,
                agent.spice,
                agent.age,
                agent.alive,
            )
            for agent in world.agents
        )
    )
    cells = tuple(
        (cell.x, cell.y, cell.sugar, cell.spice, cell.pollution)
        for column in world.environment.grid
        for cell in column
    )
    return world.timestep, agents, cells


def test_initial_agents_are_round_robin_and_use_ruleset_agent(tiny_episode_config: dict[str, object]) -> None:
    world = _world(tiny_episode_config, [None, None])

    assert all(isinstance(agent, RulesetAgent) for agent in world.agents)
    assert [agent.seat for agent in sorted(world.agents, key=lambda agent: agent.ID)] == [
        0,
        1,
        0,
        1,
        0,
        1,
        0,
        1,
    ]


def test_traits_are_clamped_per_variant_and_null_traits_are_untouched(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "agentAggressionFactor": [0.25, 0.25],
            "agentTradeFactor": [0.25, 0.25],
            "agentLendingFactor": [0.25, 0.25],
            "agentFertilityFactor": [1, 1],
        }
    )
    traits = {
        "version": 1,
        "traits": {"aggression": -5, "trade": 4, "lending": 0.75, "fertility": 9},
    }
    world = _world(config, [traits, None])

    customized = next(agent for agent in world.agents if agent.seat == 0)
    untouched = next(agent for agent in world.agents if agent.seat == 1)
    assert (
        customized.aggressionFactor,
        customized.tradeFactor,
        customized.lendingFactor,
        customized.fertilityFactor,
    ) == (0, 1, 0.75, 2)
    assert (
        untouched.aggressionFactor,
        untouched.tradeFactor,
        untouched.lendingFactor,
        untouched.fertilityFactor,
    ) == (0.25, 0.25, 0.25, 1)


def test_replacements_inherit_first_k_dead_seats_in_dtl_order(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config["agentReplacements"] = config["startingAgents"]
    world = _world(config, [None, None])
    deaths = [world.agents[1], world.agents[4], world.agents[7]]
    expected_seats = [agent.seat for agent in deaths]
    for agent in deaths:
        agent.alive = False

    world.timestep = 1
    world.removeDeadAgents()
    world.replaceDeadAgents()

    assert [agent.seat for agent in world.replacedAgents] == expected_seats


def test_newborn_seat_draw_consumes_exactly_one_seeded_random_value(
    tiny_episode_config: dict[str, object],
) -> None:
    world = _world(tiny_episode_config, [None, None])
    parent, mate = world.agents[0], world.agents[1]
    random.seed(9876)
    before = random.getstate()

    child_config = parent.findChildEndowment(mate)
    after = random.getstate()

    random.setstate(before)
    draw = random.random()
    assert after == random.getstate()
    assert child_config["_coworld_seat"] == (parent.seat if draw < 0.5 else mate.seat)
    empty_cell = next(
        cell
        for column in world.environment.grid
        for cell in column
        if cell.agent is None
    )
    child = parent.spawnChild(world.generateAgentID(), 1, empty_cell, child_config)
    assert isinstance(child, RulesetAgent)
    assert child.seat == child_config["_coworld_seat"]


def test_custom_ranking_uses_score_then_distance_then_dtl_order(
    tiny_episode_config: dict[str, object],
) -> None:
    movement = {
        "version": 1,
        "movement": [{"score": ["get", "cell.sugar"]}],
    }
    world = _world(tiny_episode_config, [movement, None])
    agent = next(agent for agent in world.agents if agent.seat == 0)
    candidates = [
        {"cell": world.environment.findCell(0, 0), "wealth": 999, "range": 3},
        {"cell": world.environment.findCell(1, 0), "wealth": -1, "range": 1},
        {"cell": world.environment.findCell(2, 0), "wealth": 0, "range": 1},
    ]
    for record in candidates:
        record["cell"].sugar = 2

    ranked = agent.sortCellsByWealth(candidates)

    assert [record["cell"].x for record in ranked] == [1, 2, 0]


def test_world_feature_cache_uses_current_tick_and_completed_previous_stats(
    tiny_episode_config: dict[str, object],
) -> None:
    movement = {"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]}
    world = _world(tiny_episode_config, [movement, None])
    world.updateRuntimeStats()
    previous_gini = world.runtimeStats["giniCoefficient"]
    previous_mean_wealth = world.runtimeStats["meanWealth"]
    previous_population = len(world.agents)

    world.doTimestep()

    assert world.world_features.timestep == 1
    assert world.world_features.population == previous_population
    assert world.world_features.gini == previous_gini
    assert world.world_features.mean_wealth == previous_mean_wealth


def test_null_rulesets_match_stock_dtl_trajectory(tiny_episode_config: dict[str, object]) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "agentFemaleFertilityAge": [1000, 1000],
            "agentMaleFertilityAge": [1000, 1000],
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
        }
    )
    resolved = resolve_episode_config(config)
    dtl_config = build_dtl_config(resolved)

    random.seed(dtl_config["seed"])
    stock = Sugarscape(dtl_config)
    stock.updateRuntimeStats()
    stock_trajectory = [_snapshot(stock)]
    for _ in range(dtl_config["timesteps"]):
        stock.doTimestep()
        stock_trajectory.append(_snapshot(stock))

    coworld = _world(config, [None, None])
    coworld.updateRuntimeStats()
    coworld_trajectory = [_snapshot(coworld)]
    for _ in range(dtl_config["timesteps"]):
        coworld.doTimestep()
        coworld_trajectory.append(_snapshot(coworld))

    assert coworld_trajectory == stock_trajectory
