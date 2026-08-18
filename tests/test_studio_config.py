from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from coworld.config import resolve_episode_config
from coworld.studio import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MANIFEST_PATH,
    StudioVariantCatalog,
    compose_run_config,
)


def test_catalog_exposes_explicit_kinds_and_context_ids() -> None:
    public = StudioVariantCatalog.load().public_dict()
    variants = {variant["id"]: variant for variant in public["variants"]}

    assert {variant_id: variant["kind"] for variant_id, variant in variants.items()} == {
        "local-default": "fixed",
        "solo-wealth": "fixed",
        "solo-ladder": "pooled",
        "duo-ladder": "pooled",
        "commonwealth": "fixed",
    }
    assert "duel-4seat" not in variants
    assert variants["local-default"]["context_id"] == "default"
    assert variants["commonwealth"]["context_id"] == "commonwealth"
    for variant in variants.values():
        for scenario in variant["scenarios"]:
            assert scenario["context_id"] == f"{variant['id']}:{scenario['id']}"


def test_duplicate_scenario_ids_are_scoped_to_a_variant(tmp_path: Path) -> None:
    catalog = StudioVariantCatalog.load()
    solo_ids = {scenario["id"] for scenario in catalog.variant("solo-ladder").scenarios}
    duo_ids = {scenario["id"] for scenario in catalog.variant("duo-ladder").scenarios}
    shared = next(iter(solo_ids & duo_ids))

    assert catalog.scenario("solo-ladder", shared)["targets"] != catalog.scenario(
        "duo-ladder", shared
    )["targets"]

    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    solo = next(variant for variant in manifest["variants"] if variant["id"] == "solo-ladder")
    solo["game_config"]["scenario_pool"].append(
        deepcopy(solo["game_config"]["scenario_pool"][0])
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate scenario id"):
        StudioVariantCatalog.load(manifest_path=manifest_path)


def test_public_catalog_never_exposes_platform_tokens() -> None:
    encoded = json.dumps(StudioVariantCatalog.load().public_dict())

    assert '"tokens"' not in encoded
    for token in json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))["tokens"]:
        assert token not in encoded


def test_composition_strips_tokens_and_resolves_arity_before_targets(
    tmp_path: Path,
) -> None:
    local = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    local.update(
        {
            "tokens": ["platform-seat-zero"],
            "seats": 2,
            "startingAgents": 8,
            "agentReplacements": 0,
            "targets": ["wellness.max"],
        }
    )
    local_path = tmp_path / "config.json"
    local_path.write_text(json.dumps(local), encoding="utf-8")
    catalog = StudioVariantCatalog.load(local_config_path=local_path)

    run = compose_run_config(
        catalog,
        variant_id="local-default",
        mode="fixed",
        seed="9007199254740993",
    )

    assert "tokens" not in run.engine_config
    assert "tokens" not in run.resolved_config
    assert run.seed == "9007199254740993"
    assert run.engine_config["seed"] == 9_007_199_254_740_993
    assert run.resolved_config["seats"] == 2
    assert [target.id for target in run.resolved_targets] == [
        "wellness.max",
        "wellness.max",
    ]


@pytest.mark.parametrize("seed", [0, "01", "+1", "-1", " 1"])
def test_seed_boundary_rejects_noncanonical_values(seed: object) -> None:
    with pytest.raises(ValueError, match="canonical"):
        compose_run_config(
            StudioVariantCatalog.load(),
            variant_id="local-default",
            mode="fixed",
            seed=seed,  # type: ignore[arg-type]
        )


def test_ranked_preview_matches_engine_seed_to_scenario_resolution() -> None:
    catalog = StudioVariantCatalog.load()
    variant = catalog.variant("solo-ladder")
    seed = "9007199254740993"
    run = compose_run_config(
        catalog,
        variant_id=variant.id,
        mode="ranked-preview",
        seed=seed,
    )
    expected_index = int(seed) % len(variant.scenarios)

    assert run.resolved_config == resolve_episode_config(run.engine_config)
    assert run.resolved_config["scenario_index"] == expected_index
    assert run.scenario_id == variant.scenarios[expected_index]["id"]
    assert run.context_id == f"{variant.id}:{run.scenario_id}"
    assert len(run.resolved_targets) == run.resolved_config["seats"]


def test_exploration_narrows_pool_without_scaling_measurement_window() -> None:
    catalog = StudioVariantCatalog.load()
    variant = catalog.variant("solo-ladder")
    scenario = variant.scenarios[-1]
    run = compose_run_config(
        catalog,
        variant_id=variant.id,
        mode="exploration",
        seed="23",
        scenario_id=scenario["id"],
        timesteps=73,
    )

    assert run.engine_config["scenario_pool"] == [scenario]
    assert run.resolved_config["scenario_index"] == 0
    assert run.resolved_config["timesteps"] == 73
    assert run.engine_config["measurement_window"] == variant.game_config[
        "measurement_window"
    ]
    assert run.resolved_config["measurement_window"] == variant.game_config[
        "measurement_window"
    ]
    assert run.context_id == f"{variant.id}:{scenario['id']}"


def test_exploration_timestep_override_beats_scenario_override(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    variant = next(item for item in manifest["variants"] if item["id"] == "solo-ladder")
    scenario = next(
        item
        for item in variant["game_config"]["scenario_pool"]
        if item["id"] == "wealth-skewed.twin-peaks"
    )
    scenario.setdefault("config_overrides", {})["timesteps"] = 999
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    catalog = StudioVariantCatalog.load(manifest_path=manifest_path)

    run = compose_run_config(
        catalog,
        variant_id="solo-ladder",
        mode="exploration",
        seed="23",
        scenario_id="wealth-skewed.twin-peaks",
        timesteps=73,
    )

    assert run.resolved_config["timesteps"] == 73
    assert "timesteps" not in run.engine_config["scenario_pool"][0]["config_overrides"]


def test_commonwealth_is_a_fixed_scalar_variant() -> None:
    run = compose_run_config(
        StudioVariantCatalog.load(),
        variant_id="commonwealth",
        mode="fixed",
        seed="7",
    )

    assert run.context_id == "commonwealth"
    assert run.resolved_config["seats"] == 1
    assert [(target.id, target.kind) for target in run.resolved_targets] == [
        ("wellness.max", "maximize")
    ]
