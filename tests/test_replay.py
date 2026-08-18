from __future__ import annotations

from copy import deepcopy
import zlib

from coworld.config import build_dtl_config, resolve_episode_config
from coworld.episode import run_episode
from coworld.instrumentation import EpisodeInstrumentation
from coworld.replay import decode_replay, quantize_wealth
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape


def test_replay_round_trip_and_deltas_reconstruct_final_grid(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update({"tokens": ["secret-0", "secret-1"], "replay_histogram_interval": 2})
    sink_frames: list[dict[str, object]] = []
    results, replay, _ = run_episode(
        config,
        [None, None],
        emit_timing_logs=False,
        frame_sink=sink_frames.append,
    )
    document = decode_replay(replay)
    header = document["header"]

    assert document["format"] == "sugarscape.replay.v3"
    assert header["seed"] == config["seed"]
    assert header["score_method"] == results["score_method"] == "w1-hyperbolic/1"
    assert "tokens" not in header["config"]
    assert header["scores"] == results["scores"]
    assert len(header["targets"]) == config["seats"]
    assert len(header["rulesets"]) == config["seats"]
    assert header["initial_agents"]
    assert document["frames"] == sink_frames
    assert [
        frame["timestep"] for frame in document["frames"] if "running" in frame
    ] == [2, 4]
    assert len(zlib.decompress(replay)) == results["result.replay_raw_bytes"]

    reconstructed = [cell[:3] for cell in header["initial_grid"]["cells"]]
    reconstructed_agents = {agent[0]: agent for agent in header["initial_agents"]}
    reconstructed_roster = {row[0]: row for row in header["roster"]}
    for frame in document["frames"]:
        for index, sugar, spice, pollution in frame["cell_deltas"]:
            reconstructed[index] = [sugar, spice, pollution]
        for row in frame["agent_deltas"]["births"]:
            assert row[0] not in reconstructed_roster  # statics arrive exactly once
            reconstructed_roster[row[0]] = row
        for agent in frame["agent_deltas"]["upsert"]:
            reconstructed_agents[agent[0]] = agent
        for agent_id in frame["agent_deltas"]["remove"]:
            reconstructed_agents.pop(agent_id)

    resolved = resolve_episode_config(config)
    world = CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(None), compile_ruleset(None)],
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )
    world.updateRuntimeStats()
    for _ in range(config["timesteps"]):
        world.doTimestep()
    expected = [
        [cell.sugar, cell.spice, cell.pollution]
        for column in world.environment.grid
        for cell in column
    ]
    assert reconstructed == expected
    expected_agents = {
        agent.ID: [
            agent.ID,
            agent.cell.x,
            agent.cell.y,
            quantize_wealth(agent.sugar),
            quantize_wealth(agent.spice),
            -1 if agent.tribe is None else agent.tribe,
            len(agent.diseases),
        ]
        for agent in world.agents
    }
    assert reconstructed_agents == expected_agents
    # Every living agent has full static traits in the accumulated roster.
    for agent in world.agents:
        assert reconstructed_roster[agent.ID] == [
            agent.ID,
            agent.seat,
            agent.born,
            1 if agent.sex == "male" else 0,
            agent.vision,
            agent.movement,
            agent.sugarMetabolism,
            agent.spiceMetabolism,
            agent.maxAge,
        ]


def test_decode_replay_rejects_non_replay_bytes() -> None:
    try:
        decode_replay(zlib.compress(b"{}"))
    except ValueError as error:
        assert "format" in str(error)
    else:
        raise AssertionError("invalid replay was accepted")


def test_commonwealth_replay_carries_running_wellness_diagnostics(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config.update(
        {
            "seats": 1,
            "targets": ["wellness.max"],
            "measurement_window": 3,
            "replay_histogram_interval": 2,
        }
    )
    results, replay, _ = run_episode(config, [None], emit_timing_logs=False)
    document = decode_replay(replay)

    assert document["header"]["targets"][0]["kind"] == "maximize"
    assert (
        document["header"]["seat_details"][0]["ruleset_sha256"]
        == (results["details"][0]["ruleset_sha256"])
    )
    running = [
        frame["running"][0] for frame in document["frames"] if "running" in frame
    ]
    assert running
    assert all(reading["score_method"] == "wellness-sum/1" for reading in running)
    assert all(reading["kind"] == "maximize" for reading in running)
    assert all(
        set(reading["component_means"])
        == {"health", "conflict", "social", "family", "wealth"}
        for reading in running
    )
    assert running[-1]["score"] == results["scores"][0]


def test_header_sink_precedes_frames_and_matches_final_initial_header(
    tiny_episode_config: dict[str, object],
) -> None:
    events: list[str] = []
    bootstrap_headers: list[dict[str, object]] = []

    def capture_header(header: dict[str, object]) -> None:
        events.append("header")
        bootstrap_headers.append(deepcopy(header))
        header_config = header["config"]
        assert isinstance(header_config, dict)
        header_config["seed"] = 999

    def capture_frame(_frame: dict[str, object]) -> None:
        events.append("frame")

    _results, replay, _timings = run_episode(
        tiny_episode_config,
        [None, None],
        emit_timing_logs=False,
        header_sink=capture_header,
        frame_sink=capture_frame,
    )
    final_header = decode_replay(replay)["header"]
    initial_header = {
        key: value
        for key, value in final_header.items()
        if key not in {"scores", "seat_details"}
    }

    assert events[0] == "header"
    assert events.count("header") == 1
    assert bootstrap_headers == [initial_header]
    assert set(bootstrap_headers[0]).isdisjoint({"scores", "seat_details"})
    assert final_header["seed"] == tiny_episode_config["seed"]
    assert final_header["config"]["seed"] == tiny_episode_config["seed"]


def _extinction_config(
    tiny_episode_config: dict[str, object],
) -> dict[str, object]:
    config = dict(tiny_episode_config)
    config.update(
        {
            "timesteps": 12,
            "measurement_window": 12,
            "replay_histogram_interval": 10,
            "agentStartingSugar": [3, 4],
            "agentStartingSpice": [3, 4],
            "agentSugarMetabolism": [6, 6],
            "agentSpiceMetabolism": [6, 6],
            "agentFertilityFactor": [0, 0],
            "environmentSugarRegrowRate": 0,
            "environmentSpiceRegrowRate": 0,
        }
    )
    return config


def test_extinction_terminal_frame_gets_current_measurements(
    tiny_episode_config: dict[str, object],
) -> None:
    config = _extinction_config(tiny_episode_config)

    results, replay, _timings = run_episode(
        config, [None, None], emit_timing_logs=False
    )
    document = decode_replay(replay)
    terminal = document["frames"][-1]

    assert results["result.extinct"] is True
    assert terminal["timestep"] < config["timesteps"]
    assert terminal["timestep"] % config["replay_histogram_interval"] != 0
    assert "running" in terminal
    assert "measured" in terminal
    assert document["header"]["scores"] == results["scores"] == [0.0, 0.0]


def test_commonwealth_extinction_terminal_frame_gets_current_wellness(
    tiny_episode_config: dict[str, object],
) -> None:
    config = _extinction_config(tiny_episode_config)
    config.update({"seats": 1, "targets": ["wellness.max"]})

    results, replay, _timings = run_episode(
        config, [None], emit_timing_logs=False
    )
    terminal = decode_replay(replay)["frames"][-1]

    assert results["result.extinct"] is True
    assert terminal["timestep"] % config["replay_histogram_interval"] != 0
    assert terminal["running"][0]["score_method"] == "wellness-sum/1"
    assert terminal["running"][0]["score"] == results["scores"][0]
    assert "measured" in terminal


def test_zero_frame_episode_serializes_without_terminal_measurements(
    tiny_episode_config: dict[str, object],
) -> None:
    config = dict(tiny_episode_config)
    config["timesteps"] = 0

    results, replay, _timings = run_episode(
        config, [None, None], emit_timing_logs=False
    )
    document = decode_replay(replay)

    assert results["timesteps_completed"] == 0
    assert document["frames"] == []
    assert document["header"]["scores"] == results["scores"]
