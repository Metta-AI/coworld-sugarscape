from __future__ import annotations

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
    assert "tokens" not in header["config"]
    assert header["scores"] == results["scores"]
    assert len(header["targets"]) == config["seats"]
    assert len(header["rulesets"]) == config["seats"]
    assert header["initial_agents"]
    assert document["frames"] == sink_frames
    assert [frame["timestep"] for frame in document["frames"] if "running" in frame] == [2, 4]
    assert len(zlib.decompress(replay)) == results["result.replay_raw_bytes"]

    reconstructed = [cell[:3] for cell in header["initial_grid"]["cells"]]
    reconstructed_agents = {agent[0]: agent for agent in header["initial_agents"]}
    for frame in document["frames"]:
        for index, sugar, spice, pollution in frame["cell_deltas"]:
            reconstructed[index] = [sugar, spice, pollution]
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
            agent.seat,
            agent.cell.x,
            agent.cell.y,
            quantize_wealth(agent.sugar + agent.spice),
        ]
        for agent in world.agents
    }
    assert reconstructed_agents == expected_agents


def test_decode_replay_rejects_non_replay_bytes() -> None:
    try:
        decode_replay(zlib.compress(b'{}'))
    except ValueError as error:
        assert "format" in str(error)
    else:
        raise AssertionError("invalid replay was accepted")
