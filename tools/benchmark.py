#!/usr/bin/env python3
"""Benchmark the native release binary against the pinned CPython oracle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "reference" / "dtl-python" / "sugarscape.py"


def timed(command: list[str], cwd: Path, repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        samples.append(time.perf_counter() - started)
    return min(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument(
        "--example",
        default="all_features",
        help="name under reference/dtl-python/examples",
    )
    parser.add_argument("--timesteps", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    source = ROOT / "reference" / "dtl-python" / "examples" / f"{args.example}.json"
    raw = json.loads(source.read_text())
    options = raw.get("sugarscapeOptions", raw)
    options["agentLogfile"] = None
    options["headlessMode"] = True
    options["logfile"] = None
    options["timesteps"] = args.timesteps

    with tempfile.TemporaryDirectory(prefix="sugarscape-benchmark-") as temp:
        workspace = Path(temp)
        config = workspace / "config.json"
        config.write_text(json.dumps(raw))
        python_seconds = timed(
            [str(args.python.resolve()), str(ORACLE), "--conf", str(config)],
            workspace,
            args.repeats,
        )
        native_seconds = timed(
            [str(args.binary.resolve()), "--conf", str(config)],
            workspace,
            args.repeats,
        )

    print(
        json.dumps(
            {
                "example": args.example,
                "timesteps": args.timesteps,
                "repeats": args.repeats,
                "pythonSeconds": python_seconds,
                "nativeSeconds": native_seconds,
                "speedup": python_seconds / native_seconds,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
