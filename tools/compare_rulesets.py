#!/usr/bin/env python3
"""Compare a saved Studio ruleset with the bundled baseline using paired seeds."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from coworld.config import resolve_episode_config  # noqa: E402
from coworld.episode import canonical_results_payload, run_episode  # noqa: E402
from coworld.targets import load_target_catalog, resolve_seat_targets  # noqa: E402
from players.baseline.player import choose_ruleset  # noqa: E402

METRICS = (
    "score.match_mean",
    "result.population_final",
    "result.gini_final",
    "result.mean_wealth_final",
)


@dataclass(frozen=True)
class PairedMeasurement:
    seed: int
    metric: str
    baseline: float
    candidate: float
    delta: float


def compare_rulesets(
    config: dict[str, object], candidate: object, seeds: list[int], output: Path
) -> dict[str, object]:
    """Write complete paired episodes and return their deterministic summary.

    Each arm is a separate world. In multi-seat variants the candidate controls
    every seat; baseline seats each use their assigned target's canned policy.
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("run with PYTHONHASHSEED=0 for reproducible experiments")
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError("seeds must be non-negative integers")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be unique; repeats are not independent samples")
    # Refuse to overwrite earlier experiment evidence.
    output.mkdir(parents=True, exist_ok=False)
    measurements: list[PairedMeasurement] = []
    for seed in seeds:
        episode_config = {**config, "seed": seed}
        resolved = resolve_episode_config(episode_config)
        targets = resolve_seat_targets(
            resolved.get("targets"),
            seats=int(resolved["seats"]),
            measurement_window=int(resolved["measurement_window"]),
            catalog=load_target_catalog(),
        )
        seed_dir = output / str(seed)
        seed_dir.mkdir()
        (seed_dir / "config.json").write_text(
            json.dumps(resolved, indent=2, sort_keys=True) + "\n"
        )
        arms = {
            "baseline": [choose_ruleset(target.as_dict()) for target in targets],
            "candidate": [candidate for _ in targets],
        }
        results = {}
        for arm, rulesets in arms.items():
            result, replay, _timings = run_episode(
                episode_config, rulesets, emit_timing_logs=False
            )
            results[arm] = result
            (seed_dir / f"{arm}.rulesets.json").write_text(
                json.dumps(rulesets, indent=2, sort_keys=True) + "\n"
            )
            (seed_dir / f"{arm}.results.json").write_bytes(
                canonical_results_payload(result) + b"\n"
            )
            (seed_dir / f"{arm}.replay").write_bytes(replay)
        for metric in METRICS:
            baseline = float(results["baseline"][metric])
            changed = float(results["candidate"][metric])
            measurements.append(
                PairedMeasurement(seed, metric, baseline, changed, changed - baseline)
            )
    summaries = {}
    for metric in METRICS:
        rows = [row for row in measurements if row.metric == metric]
        deltas = [row.delta for row in rows]
        summaries[metric] = {
            "pairs": len(rows),
            "baseline_mean": statistics.mean(row.baseline for row in rows),
            "candidate_mean": statistics.mean(row.candidate for row in rows),
            "paired_delta_mean": statistics.mean(deltas),
            "paired_delta_min": min(deltas),
            "paired_delta_max": max(deltas),
            "paired_delta_stdev": statistics.stdev(deltas) if len(rows) > 1 else None,
        }
    report = {
        "schema_version": 1,
        "config": config,
        "candidate": candidate,
        "seeds": seeds,
        "metrics": summaries,
        "measurements": [asdict(row) for row in measurements],
    }
    (output / "comparison.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text())
    variants = {variant["id"]: variant["game_config"] for variant in manifest["variants"]}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=variants, default="commonwealth")
    parser.add_argument("--ruleset", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--timesteps", type=int, help="override duration (a smoke run, not the ranked preset)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    config = dict(variants[args.variant])
    if args.timesteps is not None:
        if args.timesteps <= 0:
            parser.error("--timesteps must be positive")
        # Scenario overrides are applied after the top-level configuration.
        config["timesteps"] = args.timesteps
        for scenario in config.get("scenario_pool", []):
            scenario.setdefault("config_overrides", {})["timesteps"] = args.timesteps
    candidate = json.loads(args.ruleset.read_text())
    source_files = [
        *sorted((ROOT / "src" / "coworld").rglob("*.py")),
        *sorted((ROOT / "src" / "sugarscape").rglob("*.py")),
        *sorted((ROOT / "targets").glob("*.json")),
        ROOT / "src" / "sugarscape" / "config.json",
        ROOT / "players" / "baseline" / "player.py",
        ROOT / "tools" / "compare_rulesets.py",
        ROOT / "coworld_manifest.json",
    ]
    provenance = {
        "variant": args.variant,
        "python": sys.version,
        "platform": platform.platform(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "coworld_commit": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "upstream_commit": subprocess.check_output(
            ["git", "-C", str(ROOT / "src" / "sugarscape"), "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files
        },
    }
    report = compare_rulesets(config, candidate, args.seeds, args.out)
    (args.out / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report["metrics"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
