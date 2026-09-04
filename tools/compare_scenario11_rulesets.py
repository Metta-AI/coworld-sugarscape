#!/usr/bin/env python3
"""Compare simple SugarLang movement rules on current scenario 11.

This is an exact deployed-engine diagnostic, not the historical schema harness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from coworld.episode import run_episode


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "coworld_manifest.json"


RULESETS: dict[str, object] = {
    "stock": {"version": 1, "traits": {"aggression": 0}},
    "welfare": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [{"score": ["get", "cell.welfare"]}],
    },
    "far_stride": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "score": [
                    "+",
                    ["get", "cell.sugar"],
                    ["*", 0.5, ["get", "cell.distance"]],
                ]
            }
        ],
    },
    "sugar_far_tiebreak": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "score": [
                    "+",
                    ["*", 10, ["get", "cell.sugar"]],
                    ["get", "cell.distance"],
                ]
            }
        ],
    },
    "sugar_near_tiebreak": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "score": [
                    "-",
                    ["*", 10, ["get", "cell.sugar"]],
                    ["get", "cell.distance"],
                ]
            }
        ],
    },
    "farthest": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [{"score": ["get", "cell.distance"]}],
    },
    "far_025": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {"score": ["+", ["get", "cell.sugar"], ["*", 0.25, ["get", "cell.distance"]]]}
        ],
    },
    "far_075": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {"score": ["+", ["get", "cell.sugar"], ["*", 0.75, ["get", "cell.distance"]]]}
        ],
    },
    "far_1": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {"score": ["+", ["get", "cell.sugar"], ["get", "cell.distance"]]}
        ],
    },
    "low_reserve_far": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "if": ["<", ["get", "agent.ttl"], 4],
                "score": ["+", ["get", "cell.sugar"], ["*", 0.5, ["get", "cell.distance"]]],
            },
            {"score": ["get", "cell.welfare"]},
        ],
    },
    "young_far": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "if": ["<", ["get", "agent.age"], 15],
                "score": ["+", ["get", "cell.sugar"], ["*", 0.5, ["get", "cell.distance"]]],
            },
            {
                "score": ["-", ["*", 10, ["get", "cell.sugar"]], ["get", "cell.distance"]]
            },
        ],
    },
    "fertile_near": {
        "version": 1,
        "traits": {"aggression": 0, "fertility": 1},
        "movement": [
            {
                "if": [
                    "and",
                    [">=", ["get", "agent.age"], 12],
                    ["<", ["get", "agent.age"], 50],
                    [">=", ["get", "agent.ttl"], 4],
                ],
                "score": ["-", ["*", 10, ["get", "cell.sugar"]], ["get", "cell.distance"]],
            },
            {"score": ["+", ["get", "cell.sugar"], ["*", 0.5, ["get", "cell.distance"]]]},
        ],
    },
    **{
        f"far_then_near_{threshold}": {
            "version": 1,
            "traits": {"aggression": 0, "fertility": 1},
            "movement": [
                {
                    "if": [">", ["get", "world.population"], threshold],
                    "score": [
                        "+",
                        ["get", "cell.sugar"],
                        ["*", 0.5, ["get", "cell.distance"]],
                    ],
                },
                {
                    "score": [
                        "-",
                        ["*", 10, ["get", "cell.sugar"]],
                        ["get", "cell.distance"],
                    ]
                },
            ],
        }
        for threshold in (150, 100, 75, 50, 35, 25, 15)
    },
    **{
        f"near_then_far_{threshold}": {
            "version": 1,
            "traits": {"aggression": 0, "fertility": 1},
            "movement": [
                {
                    "if": [">", ["get", "world.population"], threshold],
                    "score": [
                        "-",
                        ["*", 10, ["get", "cell.sugar"]],
                        ["get", "cell.distance"],
                    ],
                },
                {
                    "score": [
                        "+",
                        ["get", "cell.sugar"],
                        ["*", 0.5, ["get", "cell.distance"]],
                    ]
                },
            ],
        }
        for threshold in (150, 100, 75, 50, 35, 25, 15)
    },
    **{
        f"juvenile_switch_{age}": {
            "version": 1,
            "traits": {"aggression": 0, "fertility": 1},
            "movement": [
                {
                    "if": ["<", ["get", "agent.age"], age],
                    "score": [
                        "+",
                        ["get", "cell.sugar"],
                        ["*", 0.5, ["get", "cell.distance"]],
                    ],
                },
                {
                    "if": ["<", ["get", "agent.age"], 50],
                    "score": [
                        "-",
                        ["*", 10, ["get", "cell.sugar"]],
                        ["get", "cell.distance"],
                    ],
                },
                {
                    "score": [
                        "+",
                        ["get", "cell.sugar"],
                        ["*", 0.5, ["get", "cell.distance"]],
                    ]
                },
            ],
        }
        for age in (5, 8, 10, 12, 15, 18, 25)
    },
}


def solo_config(seed: int) -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    variant = next(item for item in manifest["variants"] if item["id"] == "solo-ladder")
    config = dict(variant["game_config"])
    config["seed"] = seed
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--rules", nargs="+", choices=tuple(RULESETS), default=tuple(RULESETS))
    args = parser.parse_args()

    for seed in args.seeds:
        if seed % 80 != 11:
            raise SystemExit(f"seed {seed} does not draw scenario 11")
        for name in args.rules:
            births = deaths = starvation = aging = 0

            def collect(frame: dict[str, object]) -> None:
                nonlocal births, deaths, starvation, aging
                stats = frame["runtimeStats"]
                births += int(stats["agentsBorn"])
                deaths += int(stats["agentDeaths"])
                starvation += int(stats["agentStarvationDeaths"])
                aging += int(stats["agentAgingDeaths"])

            results, _replay, _timings = run_episode(
                solo_config(seed),
                [RULESETS[name]],
                emit_timing_logs=False,
                frame_sink=collect,
            )
            detail = results["details"][0]
            print(
                json.dumps(
                    {
                        "seed": seed,
                        "rule": name,
                        "score": results["scores"][0],
                        "ticks": results["timesteps_completed"],
                        "population_final": results["result.population_final"],
                        "births": births,
                        "deaths": deaths,
                        "starvation": starvation,
                        "aging": aging,
                        "raw_w1": detail["raw_w1"],
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
