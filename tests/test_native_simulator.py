from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.instrumentation import EpisodeInstrumentation
from coworld.native_fixture import (
    NativeReferenceWorld,
    build_native_v2_reference_world,
    native_v2_config,
)
from coworld.native_oracle import (
    SOURCE_PIN,
    NativeSnapshot,
    snapshot_world,
    step_python,
    validate_supported_world,
)
from coworld.native_simulator import (
    benchmark_native,
    benchmark_python,
    build_native_simulator,
    step_native,
)
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape


ROOT = Path(__file__).resolve().parents[1]


def _supported_config() -> dict[str, object]:
    return native_v2_config(seed=1729, timesteps=8)


def _world(config: dict[str, object] | None = None) -> CoworldSugarscape:
    if config is None:
        return build_native_v2_reference_world(seed=1729, timesteps=8)
    resolved = resolve_episode_config(config or _supported_config())
    return NativeReferenceWorld(
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


def test_native_schema_pin_matches_the_dtl_submodule() -> None:
    pinned_commit = subprocess.run(
        ["git", "rev-parse", "HEAD:src/sugarscape"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert SOURCE_PIN == pinned_commit


def test_native_matches_pinned_dtl_after_each_tick() -> None:
    binary = build_native_simulator()
    world = _world()

    for _ in range(4):
        actual = step_native(snapshot_world(world), 1, binary=binary)
        world.doTimestep()
        assert actual == snapshot_world(world)


def test_python_contract_matches_native_for_long_resume() -> None:
    binary = build_native_simulator()
    initial = snapshot_world(_world())

    assert step_python(initial, 100) == step_native(initial, 100, binary=binary)


@pytest.mark.parametrize(
    ("cause", "overrides", "death_age"),
    [
        (
            "starvation",
            {
                "agentStartingSugar": [1, 1],
                "environmentMaxSugar": 0,
                "environmentSugarPeaks": [[2, 4, 0], [4, 2, 0]],
                "environmentSugarRegrowRate": 0,
            },
            0,
        ),
        ("aging", {"agentMaxAge": [1, 1]}, 1),
    ],
)
def test_native_deaths_match_dtl_removal_order_and_state(
    cause: str, overrides: dict[str, object], death_age: int
) -> None:
    binary = build_native_simulator()
    config = _supported_config()
    config.update(overrides)
    world = _world(config)
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=binary)
    world.doTimestep()
    expected = snapshot_world(world)

    assert actual == expected
    assert actual.agents == ()
    assert actual.live_order == ()
    assert [death[3] for death in actual.deaths] == [cause] * 4
    assert [death[2] for death in actual.deaths] == [death_age] * 4
    assert all(occupant is None for _sugar, _maximum, occupant in actual.cells)


def test_native_benchmark_times_only_the_simulation_loop() -> None:
    binary = build_native_simulator()
    initial = snapshot_world(_world())

    result = benchmark_native(initial, 4, binary=binary)

    assert result.ticks == 4
    assert result.elapsed_ns > 0
    assert result.snapshot.timestep == initial.timestep + 4


def test_python_and_native_benchmarks_run_the_same_contract() -> None:
    binary = build_native_simulator()
    initial = snapshot_world(_world())

    python = benchmark_python(initial, 100)
    native = benchmark_native(initial, 100, binary=binary)

    assert python.ticks == native.ticks == 100
    assert python.elapsed_ns > 0
    assert python.snapshot == native.snapshot


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["agents"][0].__setitem__("maxAge", -2), "maxAge"),
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
