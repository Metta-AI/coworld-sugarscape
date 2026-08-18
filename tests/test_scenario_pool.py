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
FAMILY_REPRESENTATIVES = [0, 4, 8, 12, 16, 20]
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


@pytest.mark.parametrize("scenario_index", FAMILY_REPRESENTATIVES)
def test_one_short_episode_per_family(scenario_index: int) -> None:
    config = solo_ladder_config()
    config.update(
        {
            "seed": scenario_index,
            "timesteps": 3,
            "measurement_window": 3,
        }
    )

    results, replay, _timings = run_episode(config, [None], emit_timing_logs=False)

    expected_target = config["scenario_pool"][scenario_index]["targets"][0]
    assert results["scenario_index"] == scenario_index
    assert results["result.timesteps_completed"] == 3
    assert len(results["scores"]) == len(results["details"]) == 1
    assert results["details"][0]["target_id"] == expected_target
    assert results["targets"][0]["id"] == expected_target
    assert replay


def test_pool_invariants() -> None:
    pool = solo_ladder_config()["scenario_pool"]
    catalog_ids = set(load_target_catalog().targets)
    scenario_ids = [scenario["id"] for scenario in pool]
    maps = [
        json.dumps(scenario["config_overrides"], sort_keys=True, separators=(",", ":"))
        for scenario in pool
    ]

    assert len(pool) == 24
    assert len(set(scenario_ids)) == 24
    assert len(set(maps)) == 24
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
    assert set(families.values()) == {4}

    capacity = [scenario for scenario in pool if scenario["id"].startswith("capacity.")]
    assert all(scenario["config_overrides"]["agentMaxAge"] == [-1, -1] for scenario in capacity)
    assert all(scenario["config_overrides"]["agentReplacements"] == 0 for scenario in capacity)
    assert all(scenario["config_overrides"]["agentFertilityFactor"] == [0, 0] for scenario in capacity)


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
