#!/usr/bin/env python3
"""Verify that canonical Commonwealth episodes exercise every wellness component.

The probe uses the manifest's real ``commonwealth`` variant and the bundled
baseline constitution. It samples the engine's running, final-window component
diagnostics every tick; changing the replay interval does not change simulation
behavior.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

run_episode = importlib.import_module("coworld.episode").run_episode
WELLNESS_COMPONENTS = importlib.import_module("coworld.scoring").WELLNESS_COMPONENTS
choose_ruleset = importlib.import_module("players.baseline.player").choose_ruleset


def summarize_component_frames(
    frames: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, float | int | None]]:
    """Summarize running component means without duplicating DTL formulas."""

    observed: dict[str, list[float]] = {name: [] for name in WELLNESS_COMPONENTS}
    for frame in frames:
        running = frame.get("running")
        if not isinstance(running, list) or not running:
            continue
        reading = running[0]
        if not isinstance(reading, Mapping):
            continue
        components = reading.get("component_means")
        if not isinstance(components, Mapping):
            continue
        for name in WELLNESS_COMPONENTS:
            value = components.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                observed[name].append(float(value))
    return {
        name: {
            "samples": len(values),
            "nonzero_count": sum(value != 0 for value in values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
        }
        for name, values in observed.items()
    }


def commonwealth_config(
    *, seed: int, timesteps: int | None = None
) -> dict[str, object]:
    """Load the manifest's canonical variant with a reproducible drawn seed."""

    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    variant = next(
        item for item in manifest["variants"] if item["id"] == "commonwealth"
    )
    config = dict(variant["game_config"])
    config["seed"] = seed
    config["replay_histogram_interval"] = 1
    if timesteps is not None:
        config["timesteps"] = timesteps
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--timesteps", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    config = commonwealth_config(seed=args.seed, timesteps=args.timesteps)
    target = {"id": "wellness.max", "kind": "maximize", "variable": "wellness"}
    frames: list[dict[str, object]] = []
    results, _replay, _timings = run_episode(
        config,
        [choose_ruleset(target)],
        emit_timing_logs=False,
        frame_sink=frames.append,
    )
    report = {
        "variant": "commonwealth",
        "seed": args.seed,
        "timesteps_requested": config["timesteps"],
        "timesteps_completed": results["timesteps_completed"],
        "score": results["scores"][0],
        "components": summarize_component_frames(frames),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    missing = [
        name
        for name, stats in report["components"].items()
        if stats["nonzero_count"] == 0
    ]
    if missing:
        print(
            f"wellness components never nonzero: {', '.join(missing)}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
