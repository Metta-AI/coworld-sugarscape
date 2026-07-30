#!/usr/bin/env python3
"""Locate the first per-agent state difference from the pinned Python oracle."""

from __future__ import annotations

import argparse
import importlib
import json
import random
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference" / "dtl-python"


def python_state(binary: Path, config_path: Path, timesteps: int) -> dict:
    normalized = json.loads(
        subprocess.run(
            [str(binary), "--conf", str(config_path), "--dump-config"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    normalized["agentLogfile"] = None
    normalized["headlessMode"] = True
    normalized["logfile"] = None
    random.seed(normalized["seed"])
    sys.path.insert(0, str(REFERENCE))
    sugarscape = importlib.import_module("sugarscape")
    simulation = sugarscape.Sugarscape(normalized)
    simulation.updateRuntimeStats()
    for _ in range(timesteps):
        simulation.doTimestep()
    agents = []
    for agent in sorted(simulation.agents, key=lambda item: item.ID):
        agents.append(
            {
                "id": agent.ID,
                "cell": agent.cell.x * simulation.environment.height + agent.cell.y,
                "sugar": agent.sugar,
                "spice": agent.spice,
                "happiness": agent.happiness,
                "conflictHappiness": agent.conflictHappiness,
                "familyHappiness": agent.familyHappiness,
                "healthHappiness": agent.healthHappiness,
                "socialHappiness": agent.socialHappiness,
                "wealthHappiness": agent.wealthHappiness,
                "lastSugar": agent.lastSugar,
                "lastSpice": agent.lastSpice,
                "age": agent.age,
                "friends": len(agent.socialNetwork["friends"]),
                "maxFriends": agent.maxFriends,
                "movement": agent.movement,
                "vision": agent.vision,
                "sex": agent.sex,
                "depressed": agent.depressed,
                "movementNeighbors": len(agent.neighborhood),
                "movementStatsNeighbors": len(agent.movementNeighborhood),
                "validMoves": len(agent.validMoves),
                "validMoveRecords": [
                    {
                        "cell": option["cell"].x * simulation.environment.height
                        + option["cell"].y,
                        "welfare": option["wealth"],
                    }
                    for option in agent.validMoves
                ],
                "race": -1 if agent.race is None else agent.race,
                "racialTags": [] if agent.racialTags is None else agent.racialTags,
                "tribe": -1 if agent.tribe is None else agent.tribe,
                "tags": [] if agent.tags is None else agent.tags,
                "tradeVolume": agent.tradeVolume,
                "sugarPrice": agent.sugarPrice,
                "spicePrice": agent.spicePrice,
                "timeToLive": agent.timeToLive,
                "lastTimeToLive": agent.lastTimeToLive,
                "sugarMetabolism": agent.sugarMetabolism,
                "spiceMetabolism": agent.spiceMetabolism,
                "sugarMetabolismModifier": agent.sugarMetabolismModifier,
                "spiceMetabolismModifier": agent.spiceMetabolismModifier,
                "decisionModel": agent.decisionModel,
                "decisionModelFactor": agent.decisionModelFactor,
                "selfishnessFactor": agent.selfishnessFactor,
                "diseases": [
                    infection["disease"].ID for infection in agent.diseases
                ],
            }
        )
    pollution = [
        simulation.environment.grid[x][y].pollution
        for x in range(simulation.environment.width)
        for y in range(simulation.environment.height)
    ]
    return {
        "order": [agent.ID for agent in simulation.agents],
        "agents": agents,
        "pollution": pollution,
    }


def native_state(dump_binary: Path, config_path: Path, timesteps: int) -> dict:
    return json.loads(
        subprocess.run(
            [str(dump_binary), str(config_path), str(timesteps)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("dump_binary", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("timesteps", type=int)
    args = parser.parse_args()
    expected = python_state(
        args.binary.resolve(),
        args.config.resolve(),
        args.timesteps,
    )
    actual = native_state(
        args.dump_binary.resolve(),
        args.config.resolve(),
        args.timesteps,
    )
    if expected["order"] != actual["order"]:
        print(f"order: {expected['order']} != {actual['order']}")
    pollution_differences = [
        (index, left, right)
        for index, (left, right) in enumerate(
            zip(expected["pollution"], actual["pollution"])
        )
        if left != right
    ]
    if pollution_differences:
        print(
            f"pollution differences ({len(pollution_differences)}): "
            f"{pollution_differences[:20]}"
        )
    expected_agents = {agent["id"]: agent for agent in expected["agents"]}
    actual_agents = {agent["id"]: agent for agent in actual["agents"]}
    for agent_id in sorted(expected_agents.keys() | actual_agents.keys()):
        left = expected_agents.get(agent_id)
        right = actual_agents.get(agent_id)
        if left is None or right is None:
            print(f"agent {agent_id}")
            print(f"  python={left!r}")
            print(f"  nim={right!r}")
            continue
        differences = [
            key for key in left if left.get(key) != right.get(key)
        ]
        if not differences:
            continue
        print(f"agent {agent_id}")
        for key in differences:
            print(f"  {key}: {left.get(key)!r} != {right.get(key)!r}")
            if key == "socialHappiness":
                print(
                    "    inputs: "
                    f"friends={left['friends']}, maxFriends={left['maxFriends']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
