#!/usr/bin/env python3
"""Compare Python and Nim implementations of the same reduced simulation loop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coworld.native_fixture import build_native_v6_reference_world  # noqa: E402
from coworld.native_oracle import snapshot_world  # noqa: E402
from coworld.native_simulator import (  # noqa: E402
    benchmark_native,
    benchmark_python,
    build_native_simulator,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.ticks <= 0:
        parser.error("--ticks must be positive")
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
    if args.output is not None and args.output.exists():
        parser.error("--output must not already exist")

    binary = build_native_simulator()
    initial = snapshot_world(
        build_native_v6_reference_world(seed=args.seed, timesteps=args.ticks)
    )
    benchmark_python(initial, 1)
    benchmark_native(initial, 1, binary=binary)
    python_runs = []
    native_runs = []
    for _ in range(args.repeats):
        python = benchmark_python(initial, args.ticks)
        native = benchmark_native(initial, args.ticks, binary=binary)
        if python.snapshot != native.snapshot:
            raise RuntimeError("Python and Nim benchmark runs produced different states")
        if python.ticks != native.ticks:
            raise RuntimeError("Python and Nim completed different tick counts")
        python_runs.append(python.elapsed_ns)
        native_runs.append(native.elapsed_ns)
    python_median = median(python_runs)
    native_median = median(native_runs)
    report = {
        "mode": "reduced_two_resource_v6",
        "scope": "simulation_only",
        "worlds": 1,
        "ticks_per_run": args.ticks,
        "completed_ticks_per_run": python.ticks,
        "repeats": args.repeats,
        "python": {
            "elapsed_ns": python_runs,
            "median_elapsed_seconds": python_median / 1_000_000_000,
            "median_world_ticks_per_second": python.ticks * 1_000_000_000 / python_median,
        },
        "nim": {
            "elapsed_ns": native_runs,
            "median_elapsed_seconds": native_median / 1_000_000_000,
            "median_world_ticks_per_second": native.ticks * 1_000_000_000 / native_median,
        },
        "nim_speedup": python_median / native_median,
        "final_state_parity": True,
        "process_startup_included": False,
        "input_parsing_included": False,
        "output_serialization_included": False,
        "replay_included": False,
        "seed": args.seed,
        "source_pin": initial.as_json()["sourcePin"],
        "initial_population": len(initial.agents),
        "world": {"width": initial.width, "height": initial.height},
        "final_timestep": python.snapshot.timestep,
    }
    encoded = json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
