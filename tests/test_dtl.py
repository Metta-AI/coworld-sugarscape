from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from coworld import dtl


ROOT = Path(__file__).resolve().parents[1]
SUBMODULE = ROOT / "src" / "sugarscape"

EXPECTED_TRAJECTORY_HASH = "240db84051c7c67f5519653dfcdbfbb4c05f142a437d651993edb1442b4cfbce"


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class PassthroughAgent(dtl.Agent):
    pass


def _configuration() -> dict[str, object]:
    with (SUBMODULE / "config.json").open(encoding="utf-8") as file:
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


def _trajectory_hash(agent_cls: type[dtl.Agent] = dtl.Agent) -> str:
    configuration = _configuration()
    dtl.verifyRandomSeed(configuration)
    dtl.verifyConfiguration(configuration)
    with dtl.agent_class(agent_cls):
        world = dtl.Sugarscape(configuration)
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


def test_submodule_is_checked_out_at_the_recorded_pin_without_local_edits() -> None:
    """The gitlink is the only pin; upstream code must stay byte-identical to it."""

    mode, recorded, _stage, _path = _git("ls-files", "--stage", "src/sugarscape").split()
    assert mode == "160000", "src/sugarscape must be a git submodule, not a vendored tree"
    assert _git("rev-parse", "HEAD", cwd=SUBMODULE) == recorded
    assert _git("status", "--porcelain", cwd=SUBMODULE) == ""


def test_headless_import_does_not_load_tkinter() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", "import sys; import coworld.dtl; assert 'tkinter' not in sys.modules"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_agent_class_swap_covers_initial_agents_and_replacements() -> None:
    configuration = _configuration()
    configuration["agentReplacements"] = configuration["startingAgents"]
    dtl.verifyRandomSeed(configuration)
    dtl.verifyConfiguration(configuration)
    with dtl.agent_class(PassthroughAgent):
        world = dtl.Sugarscape(configuration)
        assert all(isinstance(agent, PassthroughAgent) for agent in world.agents)

        world.agents[0].doDeath("test")
        world.removeDeadAgents()
        world.replaceDeadAgents()
    assert dtl.Agent.__name__ == "Agent"

    assert len(world.agents) == configuration["startingAgents"]
    assert all(isinstance(agent, PassthroughAgent) for agent in world.agents)


def test_agent_class_swap_preserves_stock_dtl_trajectory() -> None:
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
