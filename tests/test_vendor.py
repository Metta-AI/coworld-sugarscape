from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from sugarscape import UPSTREAM_COMMIT
from sugarscape import agent as dtl_agent
from sugarscape import sugarscape as dtl


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "sugarscape"

UPSTREAM_CORE_HASHES = {
    "agent.py": "14856d0a7703c256d9328f56df98dcbbe274eb6cff7f71bb04eae4374e3176c6",
    "cell.py": "ea720ff1225b3a6f300e1acbc9698c9538abf2091fa4f1ef941506af30b9e572",
    "condition.py": "b167c8547374adca884923f259b5aa9700384ee889eade3f3a51ca9812b20906",
    "config.json": "f6dec169d8c7cb080989a023e61649611508f34fd676e28c766792571ef12743",
    "environment.py": "3046e7402631f81b2f1168784db13f31cea9bf8e4ea76151cbc44e12120b68a6",
    "gui.py": "1f8fff6f0c949a7eaa015e511926b1413224f67a214f23cbb8335a87e610639a",
}
EXPECTED_LOCAL_HASHES = {
    "ethics.py": "5b4dc9f4d53a99ef37c079c09d8d547675e0a0fabe86ed3597ecbd1792ab1549",
    "sugarscape.py": "7a7b20f89da2b3e54b0b2161778f159d41c5696abb551117160f466a34a961d5",
}
EXPECTED_TRAJECTORY_HASH = "240db84051c7c67f5519653dfcdbfbb4c05f142a437d651993edb1442b4cfbce"


class PassthroughAgent(dtl_agent.Agent):
    pass


def _configuration() -> dict[str, object]:
    with (VENDOR / "config.json").open(encoding="utf-8") as file:
        configuration = copy.deepcopy(json.load(file)["sugarscapeOptions"])
    configuration.update(
        {
            "agentDecisionModels": ["ruleset"],
            "agentDecisionModel": None,
            "agentDecisionModelFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentReplacements": 0,
            "agentTagging": False,
            "debugMode": ["none"],
            "environmentHeight": 12,
            "environmentSpicePeaks": [[3, 3, 4], [8, 8, 4]],
            "environmentSugarPeaks": [[3, 8, 4], [8, 3, 4]],
            "environmentWidth": 12,
            "headlessMode": True,
            "logfile": None,
            "seed": 1729,
            "startingAgents": 16,
            "startingDiseases": 0,
            "timesteps": 8,
        }
    )
    return configuration


def _trajectory_hash(agent_factory: type[dtl_agent.Agent] | None = None) -> str:
    configuration = _configuration()
    dtl.verifyRandomSeed(configuration)
    dtl.verifyConfiguration(configuration)
    world = dtl.Sugarscape(configuration, agent_factory=agent_factory)
    world.updateRuntimeStats()

    trajectory: list[dict[str, object]] = []
    for _ in range(configuration["timesteps"]):
        trajectory.append(_snapshot(world))
        world.doTimestep()
    trajectory.append(_snapshot(world))
    encoded = json.dumps(trajectory, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(world: dtl.Sugarscape) -> dict[str, object]:
    agents = []
    for agent in sorted(world.agents, key=lambda item: item.ID):
        agents.append(
            {
                "age": agent.age,
                "alive": agent.alive,
                "id": agent.ID,
                "spice": agent.spice,
                "sugar": agent.sugar,
                "x": agent.cell.x,
                "y": agent.cell.y,
            }
        )
    cells = []
    for x in range(world.environment.width):
        for y in range(world.environment.height):
            cell = world.environment.grid[x][y]
            cells.append((cell.sugar, cell.spice, cell.pollution, cell.agent.ID if cell.agent else None))
    return {
        "agents": agents,
        "cells": cells,
        "runtime_stats": world.runtimeStats,
        "timestep": world.timestep,
    }


def test_upstream_pin_and_vendor_delta_are_exact() -> None:
    assert UPSTREAM_COMMIT == "a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8"
    for relative_path, expected_hash in (UPSTREAM_CORE_HASHES | EXPECTED_LOCAL_HASHES).items():
        assert hashlib.sha256((VENDOR / relative_path).read_bytes()).hexdigest() == expected_hash


def test_headless_import_does_not_load_tkinter() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", "import sys; import sugarscape.sugarscape; assert 'tkinter' not in sys.modules"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_agent_factory_covers_initial_agents_and_replacements() -> None:
    configuration = _configuration()
    configuration["agentReplacements"] = configuration["startingAgents"]
    dtl.verifyRandomSeed(configuration)
    dtl.verifyConfiguration(configuration)
    world = dtl.Sugarscape(configuration, agent_factory=PassthroughAgent)
    assert all(isinstance(agent, PassthroughAgent) for agent in world.agents)

    world.agents[0].doDeath("test")
    world.removeDeadAgents()
    world.replaceDeadAgents()

    assert len(world.agents) == configuration["startingAgents"]
    assert all(isinstance(agent, PassthroughAgent) for agent in world.agents)


def test_passthrough_factory_preserves_stock_dtl_trajectory() -> None:
    stock_hash = _trajectory_hash()
    passthrough_hash = _trajectory_hash(PassthroughAgent)
    assert stock_hash == EXPECTED_TRAJECTORY_HASH
    assert passthrough_hash == stock_hash


def test_trajectory_fixture_does_not_leave_rng_at_an_unchecked_state() -> None:
    first = _trajectory_hash()
    state_after_first = random.getstate()
    second = _trajectory_hash()
    state_after_second = random.getstate()
    assert first == second
    assert state_after_first == state_after_second
