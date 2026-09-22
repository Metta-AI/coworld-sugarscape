#!/usr/bin/env python3
"""Run archived Blueprints homogeneous-society configurations on their paper engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zipfile import ZipFile

ARCHIVE_SHA256 = "319c38c77cdeb9f3bd618ce6c57e14e93c35e2be282c01332d42cff58327f525"
PAPER_ENGINE = "b9ca671ab7591c7b3606f2d76c33eda344d626d1"
MODELS = (
    "altruisticHalfLookaheadBinary",
    "benthamHalfLookaheadBinary",
    "egoisticHalfLookaheadBinary",
    "rawSugarscape",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True, help="clean Glucose/v2024.1 checkout")
    parser.add_argument("--archive", type=Path, required=True, help="authors' blueprints-homogeneous.zip")
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--timesteps", type=int, help="shortened smoke duration; omitted preserves the paper's 5000 ticks")
    parser.add_argument("--timeout-seconds", type=int, default=3600, help="per model subprocess budget")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("PYTHONHASHSEED") != "0":
        parser.error("run with PYTHONHASHSEED=0")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must be unique")
    if args.timesteps is not None and not 0 < args.timesteps <= 5000:
        parser.error("--timesteps must be between 1 and 5000")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    engine = args.engine.resolve()
    revision = subprocess.check_output(["git", "-C", str(engine), "rev-parse", "HEAD"], text=True).strip()
    if revision != PAPER_ENGINE:
        parser.error(f"paper requires Glucose/v2024.1 at {PAPER_ENGINE}, got {revision}")
    dirty = subprocess.check_output(
        ["git", "-C", str(engine), "status", "--porcelain", "--untracked-files=all"], text=True
    )
    if dirty:
        parser.error("paper engine must have no local edits or untracked files")
    archive_sha256 = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if archive_sha256 != ARCHIVE_SHA256:
        parser.error("archive differs from the authors' pinned blueprints-homogeneous.zip")
    with ZipFile(args.archive) as archive:
        # Read JSON directly: never extract archive paths onto the filesystem.
        configurations = [
            (name, archive.read(name), json.loads(archive.read(name)))
            for name in archive.namelist() if name.endswith(".config")
        ]
    selected = []
    for seed in args.seeds:
        for model in MODELS:
            matches = [
                (name, raw, config) for name, raw, config in configurations
                if config["seed"] == seed and config["agentDecisionModels"] == [model]
            ]
            if len(matches) != 1:
                parser.error(f"expected one archived configuration for seed {seed}, model {model}")
            if matches[0][2]["timesteps"] != 5000:
                parser.error("archived paper configurations must request 5000 timesteps")
            selected.append(matches[0])
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "paper": "https://doi.org/10.1109/ACCESS.2024.3519139",
        "experiment": "Section VII-A / Table 3: homogeneous societies",
        "engine_commit": revision,
        "archive_sha256": archive_sha256,
        "seeds": args.seeds,
        "models": list(MODELS),
        "timeout_seconds_per_model": args.timeout_seconds,
        "timesteps_override": args.timesteps,
        "planned_runs": len(selected),
        "python": sys.version,
        "pythonhashseed": "0",
        "duration": "paper" if args.timesteps is None or args.timesteps == 5000 else "shortened smoke",
        "runs": [],
    }
    (output / "request.json").write_text(json.dumps(report, indent=2) + "\n")
    for name, raw, original in selected:
        model = original["agentDecisionModels"][0]
        directory = output / str(original["seed"]) / model
        directory.mkdir(parents=True)
        (directory / "archived.config.json").write_bytes(raw)
        config = {**original, "logfile": str(directory / "trajectory.json")}
        if args.timesteps is not None:
            config["timesteps"] = args.timesteps
        config_path = directory / "run.config.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        started = time.perf_counter()
        with (directory / "stdout.txt").open("w") as stdout, (directory / "stderr.txt").open("w") as stderr:
            subprocess.run(
                [sys.executable, str(engine / "sugarscape.py"), "-c", str(config_path)],
                cwd=engine, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                stdout=stdout, stderr=stderr, check=True, timeout=args.timeout_seconds,
            )
        elapsed_seconds = time.perf_counter() - started
        trajectory = json.loads((directory / "trajectory.json").read_text())
        final = trajectory[-1]
        if final["timestep"] != config["timesteps"] and final["population"] != 0:
            raise ValueError(f"incomplete simulation for {name}")
        report["runs"].append({
            "archived_name": name,
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "seed": original["seed"],
            "model": model,
            "requested_timesteps": config["timesteps"],
            "completed_timesteps": final["timestep"],
            "wall_seconds": elapsed_seconds,
            "world_ticks_per_second": (final["timestep"] - trajectory[0]["timestep"]) / elapsed_seconds,
            "population_initial": trajectory[0]["population"],
            "population_final": final["population"],
            "trajectory_sha256": hashlib.sha256((directory / "trajectory.json").read_bytes()).hexdigest(),
        })
        print(f"{model} seed={original['seed']}: tick={final['timestep']}, population={final['population']}", flush=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
