from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.episode import run_episode
from coworld.targets import load_target_catalog, resolve_seat_targets


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "coworld_manifest.json"
FAMILY_REPRESENTATIVES = [0, 14, 28, 42, 56, 66]  # first scenario of each family
PACK_REPRESENTATIVES = [
    "wealth-skewed.twin-peaks.spice",
    "wealth-skewed.twin-peaks.reproduction",
    "wealth-skewed.twin-peaks.pollution",
    "wealth-egalitarian.central-plateau.disease",
    "capacity.compact-regrow-1.seasons",
    "survivorship.young-frontier.market",
    "tribe-convergence.three-way-mixed.combat",
    "price.overlapping-peaks.everything",
]
sys.path.insert(0, str(ROOT / "tools"))

from generate_scenario_pool import scenario_pool_span, write_manifest  # noqa: E402


def solo_ladder_config() -> dict[str, object]:
    return variant_config("solo-ladder")


def duo_ladder_config() -> dict[str, object]:
    return variant_config("duo-ladder")


def variant_config(variant_id: str) -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return next(
        variant["game_config"]
        for variant in manifest["variants"]
        if variant["id"] == variant_id
    )


def test_all_scenarios_resolve_and_validate() -> None:
    config = solo_ladder_config()
    pool = config["scenario_pool"]
    catalog = load_target_catalog()

    for index, scenario in enumerate(pool):
        episode_config = dict(config)
        episode_config["seed"] = index
        resolved = resolve_episode_config(episode_config)
        dtl_config = build_dtl_config(resolved)
        targets = resolve_seat_targets(
            resolved["targets"],
            seats=int(resolved["seats"]),
            measurement_window=int(resolved["measurement_window"]),
            catalog=catalog,
        )

        assert resolved["scenario_index"] == index
        assert len(targets) == 1
        for key, value in scenario["config_overrides"].items():
            if key != "trait_ranges":
                assert dtl_config[key] == value, f"{scenario['id']}: DTL rewrote {key}"


def test_generator_check_matches_committed_manifest() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_scenario_pool.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "scenario pool matches generator" in completed.stdout


def test_generator_write_is_byte_idempotent(tmp_path: Path) -> None:
    source = MANIFEST_PATH.read_text(encoding="utf-8")
    start, end = scenario_pool_span(source)
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text(source[:start] + "[]" + source[end:], encoding="utf-8")

    assert write_manifest(manifest_path) is True
    first = manifest_path.read_bytes()
    assert write_manifest(manifest_path) is False
    assert manifest_path.read_bytes() == first


@pytest.mark.parametrize(
    "source,error",
    [
        ('{"variants": [{"id": "other"}]}', "found 0"),
        (
            '{"variants": ['
            '{"id": "solo-ladder", "game_config": {"scenario_pool": []}},'
            '{"id": "solo-ladder", "game_config": {"scenario_pool": []}}'
            "]}",
            "found 2",
        ),
        ('{"variants": [{"id": "solo-ladder", "game_config": {}}]}', "scenario_pool"),
    ],
)
def test_generator_rejects_missing_or_ambiguous_pool(source: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        scenario_pool_span(source)


def _pool_indices() -> range:
    return range(len(solo_ladder_config()["scenario_pool"]))


@pytest.mark.parametrize("scenario_index", _pool_indices())
def test_every_scenario_runs_a_short_episode(scenario_index: int) -> None:
    config = solo_ladder_config()
    config.update({"seed": scenario_index, "timesteps": 3, "measurement_window": 3})

    results, replay, _timings = run_episode(config, [None], emit_timing_logs=False)

    assert results["scenario_index"] == scenario_index
    assert results["result.timesteps_completed"] == 3
    assert replay


@pytest.mark.parametrize("scenario_id", PACK_REPRESENTATIVES)
def test_pack_representatives_survive_mechanic_activation(scenario_id: str) -> None:
    config = solo_ladder_config()
    pool_ids = [scenario["id"] for scenario in config["scenario_pool"]]
    config.update(
        {
            "seed": pool_ids.index(scenario_id),
            "timesteps": 70,
            "measurement_window": 10,
        }
    )

    results, replay, _timings = run_episode(config, [None], emit_timing_logs=False)

    assert results["result.timesteps_completed"] == 70
    assert replay


def test_pack_mechanics_are_disclosed_to_players() -> None:
    from coworld.server import public_config

    config = solo_ladder_config()
    pool_ids = [scenario["id"] for scenario in config["scenario_pool"]]
    config["seed"] = pool_ids.index("price.overlapping-peaks.everything")
    resolved = resolve_episode_config(config)
    disclosed = public_config(resolved)

    for key in (
        "agentSpiceMetabolism",
        "agentTradeFactor",
        "agentTagging",
        "agentAggressionFactor",
        "startingDiseases",
        "environmentSugarProductionPollutionFactor",
        "environmentSeasonInterval",
        "trait_ranges",
    ):
        assert disclosed[key] == resolved[key], key
    for hidden in ("seed", "scenario_pool", "targets", "tokens"):
        assert hidden not in disclosed, hidden


def test_pool_invariants() -> None:
    pool = solo_ladder_config()["scenario_pool"]
    catalog_ids = {
        target.id
        for target in load_target_catalog().targets.values()
        if target.kind == "distribution"
    }
    scenario_ids = [scenario["id"] for scenario in pool]
    maps = [
        json.dumps(scenario["config_overrides"], sort_keys=True, separators=(",", ":"))
        for scenario in pool
    ]

    assert len(pool) == 80
    assert len(set(scenario_ids)) == 80
    assert len(set(maps)) == 80
    assert {target for scenario in pool for target in scenario["targets"]} == catalog_ids
    assert all(len(scenario["targets"]) == 1 for scenario in pool)

    families = {
        "wealth-skewed": 0,
        "wealth-egalitarian": 0,
        "capacity": 0,
        "survivorship": 0,
        "price": 0,
        "tribe": 0,
    }
    for scenario in pool:
        overrides = scenario["config_overrides"]
        assert not {"seed", "scenario_pool"} & set(overrides)
        assert scenario["targets"][0] in catalog_ids
        assert 40 <= overrides["environmentWidth"] <= 60
        assert 40 <= overrides["environmentHeight"] <= 60
        assert 200 <= overrides["startingAgents"] <= 400
        for resource in ("Sugar", "Spice"):
            for x, y, height in overrides[f"environment{resource}Peaks"]:
                assert 0 <= x < overrides["environmentWidth"]
                assert 0 <= y < overrides["environmentHeight"]
                assert 0 <= height <= overrides[f"environmentMax{resource}"]
        family = next(
            name
            for name in families
            if scenario["id"].startswith(f"{name}.")
            or (name == "tribe" and scenario["id"].startswith("tribe-"))
        )
        families[family] += 1
    assert families == {
        "wealth-skewed": 14,
        "wealth-egalitarian": 14,
        "capacity": 14,
        "survivorship": 14,
        "price": 10,
        "tribe": 14,
    }

    capacity = [scenario for scenario in pool if scenario["id"].startswith("capacity.")]
    assert all(scenario["config_overrides"]["agentMaxAge"] == [-1, -1] for scenario in capacity)
    assert all(scenario["config_overrides"]["agentReplacements"] == 0 for scenario in capacity)
    assert all(scenario["config_overrides"]["agentFertilityFactor"] == [0, 0] for scenario in capacity)


def test_pack_invariants() -> None:
    pool = solo_ladder_config()["scenario_pool"]
    by_id = {scenario["id"]: scenario["config_overrides"] for scenario in pool}

    packs: dict[str, list[str]] = {}
    for scenario_id in by_id:
        parts = scenario_id.split(".")
        pack = parts[2] if len(parts) == 3 else "baseline"
        packs.setdefault(pack, []).append(scenario_id)

    assert {pack: len(ids) for pack, ids in packs.items()} == {
        "baseline": 12,
        "spice": 10,
        "market": 10,
        "combat": 12,
        "disease": 8,
        "pollution": 4,
        "seasons": 10,
        "reproduction": 2,
        "everything": 12,
    }

    # The pool is ordered family -> base -> packs, with fixed pack order.
    def base_and_pack(scenario_id: str) -> tuple[str, str]:
        parts = scenario_id.split(".")
        if len(parts) == 3:
            return ".".join(parts[:2]), parts[2]
        return scenario_id, "baseline"

    expected_sequence = {
        "wealth-skewed": ["baseline", "spice", "market", "combat", "reproduction", "pollution", "everything"],
        "wealth-egalitarian": ["baseline", "spice", "market", "combat", "disease", "seasons", "everything"],
        "capacity": ["baseline", "spice", "market", "combat", "pollution", "seasons", "everything"],
        "survivorship": ["baseline", "spice", "market", "combat", "disease", "seasons", "everything"],
        "price": ["baseline", "combat", "seasons", "disease", "everything"],
        "tribe": ["baseline", "spice", "market", "combat", "disease", "seasons", "everything"],
    }
    sequence: dict[str, list[str]] = {}
    for scenario in pool:
        base_id, pack = base_and_pack(scenario["id"])
        sequence.setdefault(base_id, []).append(pack)
    for base_id, pack_sequence in sequence.items():
        family = "tribe" if base_id.startswith("tribe-") else base_id.split(".")[0]
        assert pack_sequence == expected_sequence[family], base_id
    assert len(sequence) == 12

    for scenario_id, overrides in by_id.items():
        parts = scenario_id.split(".")
        pack = parts[2] if len(parts) == 3 else "baseline"
        if pack in ("spice", "market", "everything"):
            assert overrides["environmentMaxSpice"] > 0, scenario_id
            assert overrides["agentSpiceMetabolism"][1] > 0, scenario_id
            assert overrides["environmentSpicePeaks"], scenario_id
        if pack in ("market", "everything"):
            assert overrides["agentTradeFactor"] == [1, 1], scenario_id
        if pack in ("combat", "everything"):
            assert overrides["agentTagging"] is True, scenario_id
            assert overrides["agentAggressionFactor"] == [0, 2], scenario_id
        if pack in ("disease", "everything"):
            assert overrides["startingDiseases"] == 40, scenario_id
        if pack in ("pollution", "everything"):
            assert overrides["environmentSugarProductionPollutionFactor"] == 1, scenario_id
            assert overrides["environmentPollutionTimeframe"] == [0, 1000], scenario_id
            assert overrides["environmentPollutionDiffusionDelay"] == 10, scenario_id
        if pack in ("seasons", "everything"):
            assert overrides["environmentSeasonInterval"] == 50, scenario_id
        if pack == "reproduction":
            assert overrides["agentFertilityFactor"] == [1, 1], scenario_id
            assert overrides["agentReplacements"] == 0, scenario_id
        if pack == "baseline" and not scenario_id.startswith(("price.", "tribe-")):
            assert overrides["environmentMaxSpice"] == 0, scenario_id
            assert overrides["agentTagging"] is False, scenario_id

    # price never emits redundant spice/market packs
    assert not any(s.endswith((".spice", ".market")) for s in by_id if s.startswith("price."))

    # `everything` preserves each base's regime instead of overwriting it.
    for base_id in sequence:
        base = by_id[base_id]
        chaos = by_id[f"{base_id}.everything"]
        assert chaos["agentFertilityFactor"] == base["agentFertilityFactor"], base_id
        assert chaos["agentReplacements"] == base["agentReplacements"], base_id
        assert chaos["trait_ranges"]["fertility"] == base["trait_ranges"]["fertility"], base_id
        if base_id.startswith("price."):
            for key in (
                "agentStartingSpice",
                "agentSpiceMetabolism",
                "agentTradeFactor",
                "environmentMaxSpice",
                "environmentSpicePeaks",
                "environmentSpiceRegrowRate",
            ):
                assert chaos[key] == base[key], f"{base_id}: {key}"
            assert chaos["trait_ranges"]["trade"] == base["trait_ranges"]["trade"], base_id
        else:
            assert chaos["trait_ranges"]["trade"] == [0, 1], base_id
        if base_id.startswith("tribe-"):
            assert chaos["environmentMaxTribes"] == base["environmentMaxTribes"], base_id
        assert chaos["trait_ranges"]["aggression"] == [0, 2], base_id


def test_every_override_key_is_a_known_config_key() -> None:
    from coworld.config import load_dtl_defaults

    known = set(load_dtl_defaults()) | {"trait_ranges"}
    for scenario in solo_ladder_config()["scenario_pool"]:
        unknown = set(scenario["config_overrides"]) - known
        assert not unknown, f"{scenario['id']}: {sorted(unknown)}"


def test_duo_pool_reuses_every_solo_world_with_distinct_targets() -> None:
    solo = solo_ladder_config()
    duo = duo_ladder_config()
    solo_pool = solo["scenario_pool"]
    duo_pool = duo["scenario_pool"]

    assert duo["seats"] == 2
    assert len(duo["players"]) == 2
    assert [scenario["id"] for scenario in duo_pool] == [scenario["id"] for scenario in solo_pool]
    assert all(len(scenario["targets"]) == 2 for scenario in duo_pool)
    assert all(len(set(scenario["targets"])) == 2 for scenario in duo_pool)
    assert all(scenario["config_overrides"]["startingAgents"] % 2 == 0 for scenario in duo_pool)

    for index, (solo_scenario, duo_scenario) in enumerate(zip(solo_pool, duo_pool)):
        solo_target = solo_scenario["targets"][0]
        assert solo_target in duo_scenario["targets"]
        if index % 2 == 0:
            assert duo_scenario["targets"][0] == solo_target
        else:
            assert duo_scenario["targets"][1] == solo_target


@pytest.mark.parametrize("scenario_index", FAMILY_REPRESENTATIVES)
def test_one_short_duo_episode_per_family(scenario_index: int) -> None:
    config = duo_ladder_config()
    config.update({"seed": scenario_index, "timesteps": 3, "measurement_window": 3})

    results, replay, _timings = run_episode(config, [None, None], emit_timing_logs=False)

    expected_targets = config["scenario_pool"][scenario_index]["targets"]
    assert results["scenario_index"] == scenario_index
    assert results["result.timesteps_completed"] == 3
    assert len(results["scores"]) == len(results["details"]) == 2
    assert [detail["target_id"] for detail in results["details"]] == expected_targets
    assert [target["id"] for target in results["targets"]] == expected_targets
    assert replay
