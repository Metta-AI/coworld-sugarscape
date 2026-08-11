from __future__ import annotations

import random

import pytest

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.episode import canonical_results_payload, run_episode
from coworld.targets import load_target_catalog


def test_absent_or_negative_one_seed_comes_from_os_entropy(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.pop("seed")
    assert resolve_episode_config(config, seed_source=lambda: 4242)["seed"] == 4242
    config["seed"] = -1
    assert resolve_episode_config(config, seed_source=lambda: 5151)["seed"] == 5151


def test_explicit_seed_is_honored_without_calling_entropy(tiny_episode_config: dict[str, object]) -> None:
    def fail() -> int:
        raise AssertionError("entropy source was called")

    assert resolve_episode_config(tiny_episode_config, seed_source=fail)["seed"] == 17


def test_platform_only_player_fields_never_reach_dtl(tiny_episode_config: dict[str, object]) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "players": [{"name": "one"}, {"name": "two"}],
            "tokens": ["secret-one", "secret-two"],
            "player_connect_timeout_seconds": 180,
        }
    )
    dtl_config = build_dtl_config(resolve_episode_config(config))

    assert "players" not in dtl_config
    assert "tokens" not in dtl_config
    assert "player_connect_timeout_seconds" not in dtl_config


def test_scenario_selection_does_not_consume_dtl_rng(tiny_episode_config: dict[str, object]) -> None:
    config = dict(tiny_episode_config)
    config["seed"] = 5
    config["scenario_pool"] = [
        {"config_overrides": {"timesteps": 1}},
        {"config_overrides": {"timesteps": 2}},
        {"config_overrides": {"timesteps": 3}},
    ]
    random.seed(99)
    before = random.getstate()

    resolved = resolve_episode_config(config)

    assert random.getstate() == before
    assert resolved["scenario_index"] == 2
    assert resolved["timesteps"] == 3


@pytest.mark.parametrize("starting_agents,seats", [(7, 2), (8, 3)])
def test_starting_agents_must_be_divisible_by_seats(
    tiny_episode_config: dict[str, object], starting_agents: int, seats: int
) -> None:
    config = dict(tiny_episode_config)
    config.update({"startingAgents": starting_agents, "seats": seats})
    with pytest.raises(ValueError, match="divisible"):
        resolve_episode_config(config)


def test_replacement_target_cannot_require_unowned_agents(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config["agentReplacements"] = config["startingAgents"] + 1
    with pytest.raises(ValueError, match="cannot exceed"):
        resolve_episode_config(config)


def test_run_episode_is_deterministic_except_for_timings(tiny_episode_config: dict[str, object]) -> None:
    first, first_replay, first_timings = run_episode(
        tiny_episode_config, [None, None], emit_timing_logs=False
    )
    second, second_replay, second_timings = run_episode(
        tiny_episode_config, [None, None], emit_timing_logs=False
    )

    assert canonical_results_payload(first) == canonical_results_payload(second)
    assert first_replay == second_replay
    assert first_replay
    for timings in (first_timings, second_timings):
        assert timings["clock"] == "perf_counter_ns"
        assert set(timings["phases_ns"]) == {
            "config_resolution",
            "measurement_assembly",
            "replay_serialization",
            "result_assembly",
            "ruleset_compilation",
            "ruleset_validation",
            "scoring",
            "simulation",
            "world_build",
        }
        ticks = timings["simulation"]["ticks"]
        assert len(ticks) == tiny_episode_config["timesteps"]
        assert all(tick["total_ns"] > 0 for tick in ticks)
        expected_subphases = {
            "environment",
            "movement",
            "trade",
            "reproduction",
            "lending",
            "disease",
            "statistics",
            "measurement",
            "replay_frame",
        }
        assert expected_subphases <= set(timings["simulation"]["subphases_ns"])


def test_results_include_scores_details_all_histograms_and_flat_scalars(
    tiny_episode_config: dict[str, object],
) -> None:
    results, replay, timings = run_episode(
        tiny_episode_config,
        [None, None],
        submitted=[False, True],
        emit_timing_logs=False,
    )

    assert len(results["scores"]) == 2
    assert [detail["submitted"] for detail in results["details"]] == [False, True]
    assert set(results["histograms"]) == {"global", "by_seat"}
    assert "age" in results["histograms"]["global"]
    assert all("age" in entry["variables"] for entry in results["histograms"]["by_seat"])
    assert results["score.match_min"] == min(results["scores"])
    assert results["score.match_mean"] == sum(results["scores"]) / 2
    assert results["score.seat_0"] == results["scores"][0]
    assert results["result.replay_compressed_bytes"] == len(replay)
    assert results["timings"] is timings


def test_empty_target_measurement_scores_zero_and_is_flagged(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "targets": ["age-at-death.survivorship", "age-at-death.survivorship"],
            "agentMaxAge": [-1, -1],
            "agentFemaleFertilityAge": [1000, 1000],
            "agentMaleFertilityAge": [1000, 1000],
            "agentSugarMetabolism": [0, 0],
            "agentSpiceMetabolism": [0, 0],
        }
    )
    results, _, _ = run_episode(config, [None, None], emit_timing_logs=False)

    assert results["scores"] == [0.0, 0.0]
    assert all(detail["empty_measurement"] for detail in results["details"])


def test_real_dtl_deaths_are_captured_as_age_events(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "targets": ["age-at-death.survivorship", "age-at-death.survivorship"],
            "agentMaxAge": [1, 1],
            "agentSugarMetabolism": [0, 0],
            "agentSpiceMetabolism": [0, 0],
        }
    )
    results, _, _ = run_episode(config, [None, None], emit_timing_logs=False)

    assert results["histograms"]["global"]["age_at_death"]["sample_count"] == config["startingAgents"]
    assert not results["details"][0]["empty_measurement"]


def test_inline_seat_scope_targets_measure_each_subpopulation(
    tiny_episode_config: dict[str, object],
) -> None:
    target = load_target_catalog().get("wealth.skewed-gini-0.5").as_dict()
    target["scope"] = "seat"
    config = dict(tiny_episode_config)
    config["targets"] = [target, target]
    results, _, _ = run_episode(config, [None, None], emit_timing_logs=False)

    global_count = results["histograms"]["global"]["wealth"]["sample_count"]
    seat_counts = [detail["histogram"]["sample_count"] for detail in results["details"]]
    assert sum(seat_counts) == global_count
    assert all(detail["target_scope"] == "seat" for detail in results["details"])


def test_custom_movement_has_a_separate_ruleset_evaluation_timing(
    tiny_episode_config: dict[str, object],
) -> None:
    movement = {"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]}
    _, _, timings = run_episode(
        tiny_episode_config, [movement, movement], emit_timing_logs=False
    )

    assert timings["simulation"]["subphases_ns"]["ruleset_evaluation"] > 0


def test_reproduction_runs_are_seed_deterministic_with_intentional_newborn_draw(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "timesteps": 2,
            "startingAgents": 40,
            "agentFemaleFertilityAge": [0, 0],
            "agentMaleFertilityAge": [0, 0],
            "agentFemaleInfertilityAge": [100, 100],
            "agentMaleInfertilityAge": [100, 100],
            "agentStartingSugar": [100, 100],
            "agentStartingSpice": [100, 100],
            "agentSugarMetabolism": [0, 0],
            "agentSpiceMetabolism": [0, 0],
            "agentMovement": [0, 0],
            "agentVision": [1, 1],
        }
    )
    first, _, _ = run_episode(config, [None, None], emit_timing_logs=False)
    second, _, _ = run_episode(config, [None, None], emit_timing_logs=False)
    assert first["result.population_final"] > config["startingAgents"]
    assert canonical_results_payload(first) == canonical_results_payload(second)


def test_extinction_before_final_tick_scores_zero(tiny_episode_config: dict[str, object]) -> None:
    """Survival rule (2026-08-11): banked window samples do not count if the
    scope's population is gone at the final tick."""

    config = dict(tiny_episode_config)
    config.update(
        {
            # High metabolism and tiny endowments starve everyone within a few
            # ticks; the window spans the whole episode, so wealth samples
            # exist from the pre-extinction ticks.
            "timesteps": 12,
            "measurement_window": 12,
            "agentStartingSugar": [3, 4],
            "agentStartingSpice": [3, 4],
            # 6+6 metabolism outruns the 4+4 max a fresh cell can yield, so
            # even a perfect scavenger starves within a few ticks.
            "agentSugarMetabolism": [6, 6],
            "agentSpiceMetabolism": [6, 6],
            "agentFertilityFactor": [0, 0],
            "environmentSugarRegrowRate": 0,
            "environmentSpiceRegrowRate": 0,
        }
    )
    results, _replay, _timings = run_episode(config, [None, None], emit_timing_logs=False)

    assert results["result.extinct"] is True
    wealth_hist = results["histograms"]["global"]["wealth"]
    assert wealth_hist["sample_count"] > 0  # samples were banked pre-extinction
    assert results["scores"] == [0.0, 0.0]
    assert all(detail["died_before_end"] for detail in results["details"])
