#!/usr/bin/env python3
"""Compare stock and the candidate on exact current scenario-35 seeds."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from coworld.episode import run_episode
from coworld.replay import decode_replay


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path(__file__).resolve().parents[4]
MANIFEST = SOURCE_ROOT / "coworld_manifest.json"
PLAYER = (
    MAIN_ROOT
    / "players/users/relh/co-gas/sugarscape/sugarscape_policy/player.py"
)
SEEDS = (756713795, 862747795, 205987395, 1147882755, 1404672355)


def load_player():
    spec = importlib.util.spec_from_file_location("capacity_candidate", PLAYER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def solo_config(seed: int) -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    variant = next(item for item in manifest["variants"] if item["id"] == "solo-ladder")
    config = dict(variant["game_config"])
    config["seed"] = seed
    return config


def main() -> int:
    player = load_player()
    rulesets = {
        "stock": {"version": 1, "traits": {"aggression": 0}},
        "candidate": player.V3_CAPACITY_SPARSE_RULESET,
    }
    rows = []
    for seed in SEEDS:
        if seed % 80 != 35:
            raise SystemExit(f"seed {seed} does not draw scenario 35")
        for name, ruleset in rulesets.items():
            results, replay, _timings = run_episode(
                solo_config(seed), [ruleset], emit_timing_logs=False
            )
            config = decode_replay(replay)["header"]["config"]
            dispatched = player.choose_v3_ruleset(
                {
                    "protocol": player.V3_PROTOCOL,
                    "target": {"id": player.V3_CAPACITY_TARGET},
                    "ruleset_schema": {"version": 1},
                    "config": config,
                }
            )
            if dispatched != player.V3_CAPACITY_SPARSE_RULESET:
                raise SystemExit("candidate did not dispatch on exact engine config")
            rows.append(
                {
                    "seed": seed,
                    "rule": name,
                    "score": results["scores"][0],
                    "population_final": results["result.population_final"],
                    "ticks": results["timesteps_completed"],
                    "raw_w1": results["details"][0]["raw_w1"],
                }
            )
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    for name in rulesets:
        selected = [row for row in rows if row["rule"] == name]
        print(
            json.dumps(
                {
                    "rule": name,
                    "episodes": len(selected),
                    "mean_score": sum(row["score"] for row in selected) / len(selected),
                    "mean_population_final": sum(
                        row["population_final"] for row in selected
                    )
                    / len(selected),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
