from __future__ import annotations

from copy import deepcopy
import json

import pytest

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.instrumentation import EpisodeInstrumentation
from coworld.native_fixture import build_native_v1_reference_world, native_v1_config
from coworld.native_oracle import NativeSnapshot, snapshot_world, validate_supported_world
from coworld.native_simulator import benchmark_native, build_native_simulator, step_native
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape


def _supported_config() -> dict[str, object]:
    return native_v1_config(seed=1729, timesteps=8)


def _world(config: dict[str, object] | None = None) -> CoworldSugarscape:
    if config is None:
        return build_native_v1_reference_world(seed=1729, timesteps=8)
    resolved = resolve_episode_config(config or _supported_config())
    return CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(None) for _ in range(int(resolved["seats"]))],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )


def test_snapshot_round_trip_preserves_latent_order_rng_and_x_major_grid() -> None:
    snapshot = snapshot_world(_world())

    assert NativeSnapshot.from_json(json.loads(json.dumps(snapshot.as_json()))) == snapshot
    assert len(snapshot.cells) == snapshot.width * snapshot.height
    assert len(snapshot.ordered_candidates) == len(snapshot.cells)
    assert len(snapshot.rng_words) == 624
    assert snapshot.live_order != tuple(sorted(snapshot.live_order))


def test_native_matches_pinned_dtl_after_each_tick() -> None:
    binary = build_native_simulator()
    world = _world()

    for _ in range(4):
        actual = step_native(snapshot_world(world), 1, binary=binary)
        world.doTimestep()
        assert actual == snapshot_world(world)


def test_native_benchmark_times_only_the_simulation_loop() -> None:
    binary = build_native_simulator()
    initial = snapshot_world(_world())

    result = benchmark_native(initial, 4, binary=binary)

    assert result.ticks == 4
    assert result.elapsed_ns > 0
    assert result.snapshot.timestep == initial.timestep + 4


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["agents"][0].__setitem__("maxAge", 20), "maxAge"),
        (
            lambda raw: raw["cells"][0].__setitem__(
                "sugar", raw["cells"][0]["maxSugar"] + 1
            ),
            "maxSugar",
        ),
        (
            lambda raw: raw["orderedCandidates"][0][0].__setitem__(1, 0),
            "candidate distance",
        ),
    ],
)
def test_snapshot_parser_rejects_states_the_native_core_rejects(mutate, message: str) -> None:
    raw = snapshot_world(_world()).as_json()
    mutate(raw)

    with pytest.raises(ValueError, match=message):
        NativeSnapshot.from_json(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("agentMaxAge", [20, 20], "aging death"),
        ("agentTradeFactor", [1, 1], "trade"),
        ("agentFertilityFactor", [1, 1], "reproduction"),
    ],
)
def test_validator_rejects_unimplemented_mechanics(
    field: str, value: object, message: str
) -> None:
    config = deepcopy(_supported_config())
    config[field] = value

    with pytest.raises(ValueError, match=message):
        validate_supported_world(_world(config))


def test_validator_rejects_sugarlang_rules() -> None:
    resolved = resolve_episode_config(_supported_config())
    ruleset = {"version": 1, "movement": [{"score": ["get", "cell.sugar"]}]}
    world = CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset), compile_ruleset(None)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )

    with pytest.raises(ValueError, match="SugarLang"):
        validate_supported_world(world)


def test_validator_rejects_a_world_after_death() -> None:
    world = _world()
    world.agents[0].doDeath("starvation")

    with pytest.raises(ValueError, match="alive and placed"):
        validate_supported_world(world)
