#!/usr/bin/env python3
"""Measure the reduced native v1 simulation loop without replay or process I/O."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coworld.native_fixture import build_native_v1_reference_world  # noqa: E402
from coworld.native_oracle import snapshot_world  # noqa: E402
from coworld.native_simulator import benchmark_native, build_native_simulator  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.ticks <= 0:
        parser.error("--ticks must be positive")
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    if args.output is not None and args.output.exists():
        parser.error("--output must not already exist")

    binary = build_native_simulator()
    initial = snapshot_world(
        build_native_v1_reference_world(seed=args.seed, timesteps=args.ticks)
    )
    result = benchmark_native(initial, args.ticks, binary=binary)
    report = {
        "mode": "reduced_fixed_population_v1",
        "scope": "simulation_only",
        "worlds": 1,
        "completed_world_ticks": result.ticks,
        "elapsed_seconds": result.elapsed_ns / 1_000_000_000,
        "whole_world_ticks_per_second": result.ticks * 1_000_000_000 / result.elapsed_ns,
        "process_startup_included": False,
        "input_parsing_included": False,
        "output_serialization_included": False,
        "replay_included": False,
        "seed": args.seed,
        "source_pin": initial.as_json()["sourcePin"],
        "initial_population": len(initial.agents),
        "world": {"width": initial.width, "height": initial.height},
        "final_timestep": result.snapshot.timestep,
    }
    encoded = json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
