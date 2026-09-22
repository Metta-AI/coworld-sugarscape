from __future__ import annotations

from copy import copy, deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.instrumentation import EpisodeInstrumentation
from coworld.native_fixture import (
    NativeReferenceWorld,
    build_native_v7_reference_world,
    native_v7_config,
)
from coworld.native_oracle import (
    SOURCE_PIN,
    NativeSnapshot,
    audit_snapshot_compatibility,
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
    return native_v7_config(seed=1729, timesteps=8)


def _world(config: dict[str, object] | None = None) -> CoworldSugarscape:
    if config is None:
        return build_native_v7_reference_world(seed=1729, timesteps=8)
    resolved = resolve_episode_config(config or _supported_config())
    return NativeReferenceWorld(
        build_dtl_config(resolved),
        [compile_ruleset(None) for _ in range(int(resolved["seats"]))],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )


def test_snapshot_round_trip_preserves_latent_order_rng_and_x_major_grid() -> None:
    snapshot = snapshot_world(_world())

    assert (
        NativeSnapshot.from_json(json.loads(json.dumps(snapshot.as_json()))) == snapshot
    )
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


def _place_two_agents(world: CoworldSugarscape):
    first, second = sorted(world.agents, key=lambda agent: agent.ID)
    first.resetCell()
    second.resetCell()
    first.cell = world.environment.findCell(2, 2)
    second.cell = world.environment.findCell(3, 2)
    first.cell.agent = first
    second.cell.agent = second
    first.findCellsInRange()
    second.findCellsInRange()
    return first, second


def test_native_trade_matches_dtl_cached_mrs_and_metrics() -> None:
    config = _supported_config()
    config.update(
        {
            "startingAgents": 2,
            "agentTradeFactor": [1, 1],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    first, second = _place_two_agents(world)
    first.sugar, first.spice = 20, 5
    second.sugar, second.spice = 5, 20
    first.sugarMetabolism = first.spiceMetabolism = 1
    second.sugarMetabolism = second.spiceMetabolism = 1
    first.marginalRateOfSubstitution = second.marginalRateOfSubstitution = 1
    first.cell.sugar = first.cell.spice = 0
    second.cell.sugar = second.cell.spice = 0

    initial = snapshot_world(world)
    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual
    assert sum(agent[31] for agent in actual.agents) > 0


def test_native_rejected_lethal_trade_still_logs_attempted_price() -> None:
    config = _supported_config()
    config.update(
        {
            "startingAgents": 2,
            "agentTradeFactor": [1, 1],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
            "environmentSugarRegrowRate": 0,
            "environmentSpiceRegrowRate": 0,
        }
    )
    world = _world(config)
    first, second = _place_two_agents(world)
    for agent, trade_factor in ((first, 0.5), (second, 2)):
        agent.sugar = agent.spice = 20
        agent.sugarMetabolism = agent.spiceMetabolism = 25
        agent.sugarMetabolismModifier = agent.spiceMetabolismModifier = -25
        agent.tradeFactor = trade_factor
        agent.marginalRateOfSubstitution = 1
        agent.cell.sugar = agent.cell.spice = 0
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual
    assert [(agent[4], agent[5]) for agent in actual.agents] == [(20, 20), (20, 20)]
    assert sum(agent[31] for agent in actual.agents) > 0


def test_native_disease_progression_matches_dtl() -> None:
    config = _supported_config()
    config.update(
        {
            "startingAgents": 2,
            "startingDiseases": 1,
            "startingDiseasesPerAgent": [0, 0],
            "agentImmuneSystemLength": 3,
            "agentDiseaseProtectionChance": [0, 0],
            "diseaseTagStringLength": [1, 1],
            "diseaseIncubationPeriod": [0, 0],
            "diseaseTransmissionChance": [1, 1],
            "diseaseMovementPenalty": [-1, -1],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    _place_two_agents(world)
    carrier = next(agent for agent in world.agents if agent.diseases)
    target = next(agent for agent in world.agents if not agent.diseases)
    disease = carrier.diseases[0]["disease"]
    target.immuneSystem = [1 - disease.tags[0]] * len(target.immuneSystem)

    initial = snapshot_world(world)
    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual
    assert len(next(agent for agent in actual.agents if agent[0] == target.ID)[38]) == 1


def test_native_disease_recovery_preserves_repeated_activation_residue() -> None:
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 1,
            "startingDiseases": 1,
            "startingDiseasesPerAgent": [1, 1],
            "agentImmuneSystemLength": 3,
            "diseaseTagStringLength": [1, 1],
            "diseaseIncubationPeriod": [0, 0],
            "diseaseMovementPenalty": [-1, -1],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    agent = world.agents[0]
    record = agent.diseases[0]
    agent.immuneSystem[record["startIndex"]] = record["disease"].tags[0]
    initial_modifier = agent.movementModifier
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual
    survivor = actual.agents[0]
    assert survivor[38] == ()
    assert survivor[14] == initial_modifier


def test_native_disease_recovery_removal_skips_shifted_record() -> None:
    config = _supported_config()
    config.update(
        {
            "startingAgents": 2,
            "startingDiseases": 2,
            "startingDiseasesPerAgent": [0, 0],
            "agentImmuneSystemLength": 3,
            "diseaseTagStringLength": [1, 1],
            "diseaseIncubationPeriod": [0, 0],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    _place_two_agents(world)
    agent = max(world.agents, key=lambda value: len(value.diseases))
    if len(agent.diseases) == 1:
        donated = dict(agent.diseases[0])
        disease = copy(donated["disease"])
        disease.ID = 1
        disease.infected = []
        donated["disease"] = disease
        world.diseases.append(disease)
        agent.addDisease(donated)
    for record in agent.diseases:
        record["disease"].tags = [0]
        agent.immuneSystem[record["startIndex"]] = 0
    initial = snapshot_world(world)
    assert len(initial.agents[0][38]) == 2

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual
    assert len(actual.agents[0][38]) == 1


def test_dead_creditor_tombstone_transfers_debt_to_living_children() -> None:
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 3,
            "agentAggressionFactor": [0, 0],
            "agentInheritancePolicy": "children",
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    creditor, debtor, child = sorted(world.agents, key=lambda agent: agent.ID)
    creditor.socialNetwork["children"].append(child)
    creditor.addLoanToAgent(debtor, 0, 0, 9, 0, 6, 1)
    creditor.doDeath("aging")
    world.removeDeadAgents()
    initial = snapshot_world(world)
    world.deadAgents = []

    assert initial.creditor_tombstones == ((creditor.ID, "children", (child.ID,)),)

    native = step_native(initial, 1, binary=build_native_simulator())
    python = step_python(initial, 1)
    world.doTimestep()
    expected = snapshot_world(world)

    assert native == expected
    assert python == expected
    assert expected.creditor_tombstones == ()
    child_state = next(agent for agent in expected.agents if agent[0] == child.ID)
    debtor_state = next(agent for agent in expected.agents if agent[0] == debtor.ID)
    assert child_state[63] == debtor_state[62]
    assert child_state[63][0][4:] == (1, 1)


def test_native_accepts_valid_noncontiguous_disease_ids() -> None:
    config = _supported_config()
    config.update(
        {
            "seed": 48,
            "startingAgents": 2,
            "startingDiseases": 3,
            "startingDiseasesPerAgent": [3, 3],
            "agentImmuneSystemLength": 8,
            "diseaseTagStringLength": [2, 2],
            "agentAggressionFactor": [0, 0],
            "agentTagging": False,
            "agentMovement": [0, 0],
            "agentVision": [0, 0],
        }
    )
    world = _world(config)
    initial = snapshot_world(world)
    assert [disease[0] for disease in initial.diseases] == [1]

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert step_python(initial, 1) == actual


def test_validator_rejects_named_disease_ids() -> None:
    config = _supported_config()
    config["diseaseList"] = ["zombieVirus"]

    with pytest.raises(ValueError, match="named diseases"):
        snapshot_world(_world(config))


def test_native_combat_matches_dtl_loot_death_and_removal_order() -> None:
    config = _supported_config()
    config.update({"seats": 1, "startingAgents": 2, "agentTagging": False})
    world = _world(config)
    attacker, prey = _place_two_agents(world)
    attacker.sugar, attacker.spice = 10, 10
    prey.sugar, prey.spice = 4, 3
    attacker.tags, prey.tags = [0] * 5, [1] * 5
    attacker.tribe, prey.tribe = attacker.findTribe(), prey.findTribe()
    attacker.tagging = prey.tagging = False
    prey.movement = 0
    prey.vision = 0
    attacker.findCellsInRange()
    prey.findCellsInRange()
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert any(death[0] == prey.ID and death[3] == "combat" for death in actual.deaths)
    survivor = next(agent for agent in actual.agents if agent[0] == attacker.ID)
    assert survivor[2:4] == (3, 2)


def test_native_tagging_matches_dtl_rng_and_immediate_tribe_update() -> None:
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 2,
            "agentAggressionFactor": [0, 0],
            "agentTagStringLength": 2,
        }
    )
    world = _world(config)
    tagger, target = _place_two_agents(world)
    tagger.movement = target.movement = 0
    tagger.tags, target.tags = [0, 0], [1, 1]
    tagger.tribe, target.tribe = tagger.findTribe(), target.findTribe()
    target.tagging = False
    tagger.findCellsInRange()
    target.findCellsInRange()
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=build_native_simulator())
    world.doTimestep()

    assert actual == snapshot_world(world)
    tagged = next(agent for agent in actual.agents if agent[0] == target.ID)
    assert tagged[27] == 1
    assert tagged[26].count(0) == 1


def test_exact_cell_welfare_ruleset_matches_native() -> None:
    binary = build_native_simulator()
    resolved = resolve_episode_config(_supported_config())
    ruleset = {"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]}
    world = NativeReferenceWorld(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset), compile_ruleset(ruleset)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )

    for _ in range(4):
        actual = step_native(snapshot_world(world), 1, binary=binary)
        world.doTimestep()
        assert actual == snapshot_world(world)


def test_depressed_bases_and_infection_modifiers_match_native() -> None:
    binary = build_native_simulator()
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 1,
            "agentDepressionPercentage": 1,
            "agentMovement": [3, 3],
            "agentVision": [3, 3],
            "agentSugarMetabolism": [2, 2],
            "agentSpiceMetabolism": [2, 2],
        }
    )
    world = _world(config)
    agent = world.agents[0]
    assert agent.depressed
    assert agent.movement == 6
    assert agent.sugarMetabolism == 8
    assert agent.spiceMetabolism == 8
    agent.visionModifier = -1
    agent.movementModifier = -4
    agent.sugarMetabolismModifier = -6
    agent.spiceMetabolismModifier = -6
    agent.findCellsInRange()
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=binary)
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert actual.agents[0][10] == 6
    assert actual.agents[0][14:17] == (-4, -6, -6)
    assert actual.agents[0][21]
    assert actual.agents[0][22] == pytest.approx(0.5763)


def test_two_resource_welfare_can_reverse_the_sugar_only_winner() -> None:
    binary = build_native_simulator()
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 1,
            "agentLookaheadFactor": [0, 0],
            "agentMovement": [1, 1],
            "agentVision": [1, 1],
            "agentSugarMetabolism": [1, 1],
            "agentSpiceMetabolism": [3, 3],
            "environmentMaxSugar": 0,
            "environmentMaxSpice": 0,
            "environmentSugarPeaks": [[2, 4, 0], [4, 2, 0]],
            "environmentSpicePeaks": [[2, 2, 0], [4, 4, 0]],
            "environmentSugarRegrowRate": 0,
            "environmentSpiceRegrowRate": 0,
        }
    )
    world = _world(config)
    agent = world.agents[0]
    agent.sugar = 10
    agent.spice = 10
    neighbors = list(agent.cell.ranges[1])
    sugar_winner, spice_winner = neighbors[:2]
    sugar_winner.sugar = sugar_winner.maxSugar = 9
    sugar_winner.spice = sugar_winner.maxSpice = 1
    spice_winner.sugar = spice_winner.maxSugar = 1
    spice_winner.spice = spice_winner.maxSpice = 9
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=binary)
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert (actual.agents[0][2], actual.agents[0][3]) == (
        spice_winner.x,
        spice_winner.y,
    )
    assert sugar_winner.sugar > spice_winner.sugar


def test_exact_zero_spice_causes_dtl_and_native_starvation() -> None:
    binary = build_native_simulator()
    config = _supported_config()
    config.update(
        {
            "seats": 1,
            "startingAgents": 1,
            "agentStartingSugar": [100, 100],
            "agentSugarMetabolism": [0, 0],
            "agentStartingSpice": [1, 1],
            "agentSpiceMetabolism": [1, 1],
            "environmentMaxSugar": 0,
            "environmentMaxSpice": 0,
            "environmentSugarPeaks": [[2, 4, 0], [4, 2, 0]],
            "environmentSpicePeaks": [[2, 2, 0], [4, 4, 0]],
            "environmentSugarRegrowRate": 0,
            "environmentSpiceRegrowRate": 0,
        }
    )
    world = _world(config)
    initial = snapshot_world(world)

    actual = step_native(initial, 1, binary=binary)
    world.doTimestep()

    assert actual == snapshot_world(world)
    assert actual.deaths == ((0, 0, 0, "starvation"),)
    assert all(cell[4] is None for cell in actual.cells)


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
    assert all(cell[4] is None for cell in actual.cells)


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
            lambda raw: raw["cells"][0].__setitem__(
                "spice", raw["cells"][0]["maxSpice"] + 1
            ),
            "maxSpice",
        ),
        (
            lambda raw: raw["orderedCandidates"][0][0].__setitem__(1, 0),
            "candidate distance",
        ),
        (
            lambda raw: raw.__setitem__("configurationSha256", "A" * 64),
            "configurationSha256",
        ),
    ],
)
def test_snapshot_parser_rejects_states_the_native_core_rejects(
    mutate, message: str
) -> None:
    raw = snapshot_world(_world()).as_json()
    mutate(raw)

    with pytest.raises(ValueError, match=message):
        NativeSnapshot.from_json(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("agentTagPreferences", True, "tag preferences"),
        ("agentInheritancePolicy", "friends", "inheritancePolicy"),
    ],
)
def test_validator_rejects_unimplemented_mechanics(
    field: str, value: object, message: str
) -> None:
    config = deepcopy(_supported_config())
    config[field] = value

    with pytest.raises(ValueError, match=message):
        validate_supported_world(_world(config))


def test_validator_rejects_other_sugarlang_rules() -> None:
    resolved = resolve_episode_config(_supported_config())
    ruleset = {"version": 1, "movement": [{"score": ["get", "cell.sugar"]}]}
    world = CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset), compile_ruleset(None)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )

    with pytest.raises(ValueError, match="cell.welfare movement"):
        validate_supported_world(world)


def test_validator_accepts_traits_with_cell_welfare_movement() -> None:
    resolved = resolve_episode_config(_supported_config())
    ruleset = {
        "version": 1,
        "traits": {"aggression": 0, "trade": 0, "lending": 0, "fertility": 0},
        "movement": [{"score": ["get", "cell.welfare"]}],
    }
    world = CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset), compile_ruleset(None)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )

    validate_supported_world(world)


def test_validator_rejects_a_world_after_death() -> None:
    world = _world()
    world.agents[0].doDeath("starvation")

    with pytest.raises(ValueError, match="alive and placed"):
        validate_supported_world(world)


def test_commonwealth_seed_1729_matches_dtl_through_first_births_and_loan_repayment() -> (
    None
):
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    config = next(
        variant["game_config"]
        for variant in manifest["variants"]
        if variant["id"] == "commonwealth"
    ) | {"seed": 1729}
    resolved = resolve_episode_config(config)
    ruleset = {
        "version": 1,
        "traits": {"aggression": 0, "trade": 1, "lending": 1, "fertility": 1},
        "movement": [{"score": ["get", "cell.welfare"]}],
    }
    world = NativeReferenceWorld(
        build_dtl_config(resolved),
        [compile_ruleset(ruleset)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )

    audit = audit_snapshot_compatibility(world)

    assert (
        audit.configuration_sha256
        == "21d01473529dff583f4c50021bb7e9aac618559c4eafb714ffba056566e3e74c"
    )
    assert audit.ruleset_sha256 == (
        "f13b0a218f455a9d06fe379d635043c1a5194d905e1dec1ea32f4a2efc671a37",
    )
    assert (audit.population, audit.depressed_agents, audit.infected_agents) == (
        250,
        25,
        50,
    )
    assert audit.modified_agents == 50
    assert audit.blockers == ()

    binary = build_native_simulator()
    checkpoints = {
        1: (240, 250, 0),
        16: (78, 252, 0),
        17: (76, 254, 1),
        22: (65, 254, 3),
    }
    for timestep in range(1, 23):
        initial = snapshot_world(world)
        native = step_native(initial, 1, binary=binary)
        python = step_python(initial, 1)
        world.doTimestep()
        expected = snapshot_world(world)

        assert native == expected, (
            timestep,
            [
                field
                for field in initial.__dataclass_fields__
                if getattr(native, field) != getattr(expected, field)
            ],
        )
        assert python == expected, timestep
        if timestep in checkpoints:
            population, next_agent_id, loans = checkpoints[timestep]
            assert (len(expected.agents), expected.next_agent_id) == (
                population,
                next_agent_id,
            )
            assert sum(len(agent[62]) for agent in expected.agents) == loans
