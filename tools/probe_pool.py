#!/usr/bin/env python3
"""Probe every solo-ladder scenario and aggregate the reachability reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from coworld.episode import run_episode  # noqa: E402
from generate_scenario_pool import DEFAULT_CONFIG_DIR, SCENARIOS, emit_configs  # noqa: E402
from probe_reachability import GREEDY_RULESET  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "probe-pool"
CEILING_THRESHOLD = 0.5
GRADIENT_THRESHOLD = 0.05


def parse_seeds(value: str) -> list[int]:
    try:
        seeds = [int(part) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from error
    if not seeds or any(seed < 0 for seed in seeds):
        raise argparse.ArgumentTypeError("seeds must be non-negative integers")
    return seeds


def greedy_score(config_path: Path, seeds: list[int]) -> float:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    scores = []
    for seed in seeds:
        episode_config = dict(config)
        episode_config["seed"] = seed
        results, _replay, _timings = run_episode(
            episode_config,
            [GREEDY_RULESET],
            emit_timing_logs=False,
        )
        scores.append(float(results["scores"][0]))
    return sum(scores) / len(scores)


def run_probe(
    scenario_id: str,
    config_path: Path,
    output_dir: Path,
    *,
    population: int,
    generations: int,
    seeds: str,
    jobs: int,
    rng_seed: int,
) -> dict[str, object]:
    scenario_output = output_dir / scenario_id
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "probe_reachability.py"),
        "--config",
        str(config_path),
        "--population",
        str(population),
        "--generations",
        str(generations),
        "--seeds",
        seeds,
        "--jobs",
        str(jobs),
        "--rng-seed",
        str(rng_seed),
        "--out",
        str(scenario_output),
    ]
    print(f"\nprobing {scenario_id}...", flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"probe failed for {scenario_id!r} with exit code {completed.returncode}")
    report_path = scenario_output / "report.json"
    if not report_path.is_file():
        raise RuntimeError(f"probe for {scenario_id!r} did not write {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def render_table(results: list[dict[str, object]]) -> str:
    lines = [
        "| scenario | target | null floor | greedy | ceiling | gradient | result |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result['scenario_id']}` | `{result['target']}` "
            f"| {result['null_floor']:.4f} | {result['greedy_score']:.4f} "
            f"| {result['ceiling']:.4f} | {result['gradient']:+.4f} "
            f"| {'PASS' if result['passed'] else 'FAIL'} |"
        )
    return "\n".join(lines)


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative_integer(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID")
    parser.add_argument("--population", type=positive_integer, default=24)
    parser.add_argument("--generations", type=nonnegative_integer, default=12)
    parser.add_argument("--seeds", default="11,42")
    parser.add_argument("--jobs", type=positive_integer, default=8)
    parser.add_argument("--rng-seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args()

    if args.population < 2:
        parser.error("--population must be at least 2 so null and greedy baselines are included")
    try:
        seeds = parse_seeds(args.seeds)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    known_ids = {str(scenario["id"]) for scenario in SCENARIOS}
    unknown = sorted(set(args.only) - known_ids)
    if unknown:
        parser.error(f"unknown scenario id(s): {', '.join(unknown)}")
    selected = [scenario for scenario in SCENARIOS if not args.only or scenario["id"] in args.only]

    config_paths = {path.stem: path for path in emit_configs(args.config_dir)}
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for scenario in selected:
            scenario_id = str(scenario["id"])
            probe_report = run_probe(
                scenario_id,
                config_paths[scenario_id],
                args.out,
                population=args.population,
                generations=args.generations,
                seeds=args.seeds,
                jobs=args.jobs,
                rng_seed=args.rng_seed,
            )
            null_floor = float(probe_report["baseline_null"])
            ceiling = float(probe_report["ceiling_lower_bound"])
            gradient = ceiling - null_floor
            result = {
                "scenario_id": scenario_id,
                "target": scenario["targets"][0],
                "null_floor": null_floor,
                "greedy_score": greedy_score(config_paths[scenario_id], seeds),
                "ceiling": ceiling,
                "gradient": gradient,
                "passed": ceiling >= CEILING_THRESHOLD and gradient >= GRADIENT_THRESHOLD,
                "probe_report": probe_report,
            }
            results.append(result)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    combined = {
        "thresholds": {
            "ceiling_minimum": CEILING_THRESHOLD,
            "gradient_minimum": GRADIENT_THRESHOLD,
        },
        "budget": {
            "population": args.population,
            "generations": args.generations,
            "seeds": seeds,
            "jobs": args.jobs,
            "rng_seed": args.rng_seed,
        },
        "scenarios": results,
        "passed": all(bool(result["passed"]) for result in results),
    }
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    print(f"\n{render_table(results)}\n\nreport: {report_path}")
    if not combined["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
