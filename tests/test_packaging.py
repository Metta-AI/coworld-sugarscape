from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_has_v1_contract_and_no_engine_runtime() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    game = manifest["game"]

    assert manifest["apiVersion"] == "coworld.softmax.com/v1"
    assert game["name"] == "sugarscape"
    assert "version" not in game  # coworld build stamps template versions.
    assert "engine_runtime" not in game["protocols"]
    assert game["replay_viewer"]["bundle"] == "build/replay-viewer"
    assert game["runnable"]["image"] == "{{GAME_IMAGE}}"
    assert manifest["player"][0]["image"] == "{{BASELINE_IMAGE}}"


def test_manifest_config_and_results_schemas_cover_platform_traps() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    config_schema = manifest["game"]["config_schema"]
    results_schema = manifest["game"]["results_schema"]
    tokens = config_schema["properties"]["tokens"]

    assert {"tokens", "players"} <= set(config_schema["required"])
    assert tokens["type"] == "array"
    assert type(tokens["minItems"]) is int
    assert type(tokens["maxItems"]) is int
    assert config_schema["properties"]["players"]["items"]["required"] == ["name"]
    required_results = {
        "score_method",
        "scores",
        "score.match_mean",
        "score.match_min",
        "result.population_final",
        "result.gini_final",
        "result.extinct",
    }
    assert required_results <= set(results_schema["required"])
    assert results_schema["properties"]["score_method"] == {"const": "w1-hyperbolic/1"}


def test_variants_and_certification_are_token_free_and_fixture_lengths_match() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    assert {variant["id"] for variant in manifest["variants"]} == {
        "solo-wealth",
        "solo-ladder",
        "duo-ladder",
        "duel-4seat",
        "commonwealth",
    }
    for variant in manifest["variants"]:
        assert "tokens" not in variant["game_config"]
    certification = manifest["certification"]
    assert "tokens" not in certification["game_config"]
    assert len(certification["players"]) == len(certification["game_config"]["players"])
    assert certification["game_config"]["startingAgents"] == 30
    assert certification["game_config"]["timesteps"] == 50

    commonwealth = next(
        variant for variant in manifest["variants"] if variant["id"] == "commonwealth"
    )["game_config"]
    assert commonwealth["seed"] == -1
    assert commonwealth["seats"] == 1
    assert commonwealth["timesteps"] == 1000
    assert commonwealth["measurement_window"] == 50
    assert commonwealth["targets"] == ["wellness.max"]
    assert commonwealth["agentDepressionPercentage"] == 0.1
    assert commonwealth["agentReplacements"] == 0
    for key in (
        "environmentSeasonInterval",
        "environmentSeasonalGrowbackDelay",
        "environmentSugarConsumptionPollutionFactor",
        "environmentSugarProductionPollutionFactor",
        "environmentSpiceConsumptionPollutionFactor",
        "environmentSpiceProductionPollutionFactor",
    ):
        assert commonwealth[key] == 0


def test_results_schema_allows_unbounded_commonwealth_scores() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    properties = manifest["game"]["results_schema"]["properties"]

    assert "maximum" not in properties["scores"]["items"]
    assert "maximum" not in properties["score.match_mean"]
    assert "maximum" not in properties["score.match_min"]


def test_container_files_pin_python_and_hash_seed() -> None:
    game_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    player_dockerfile = (ROOT / "players" / "baseline" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    for dockerfile in (game_dockerfile, player_dockerfile):
        assert "FROM python:3.13.5-slim" in dockerfile
        assert "PYTHONHASHSEED=0" in dockerfile
    assert "platform: linux/amd64" in compose
    assert "services:\n  game:" in compose
    assert "\n  baseline:" in compose


def test_tracked_archive_warnings_remain_and_v3_guidance_is_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "**ARCHIVAL ONLY.** Everything under `archived/` is frozen" in readme
    assert "Everything under `archived/` is **archival only**" in agents
    assert "## Sugarscape v3" in readme
    assert "## v3 layout" in agents
