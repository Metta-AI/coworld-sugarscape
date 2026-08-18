#!/usr/bin/env python3
"""Measure the local Studio Play pipeline without wall-clock CI assertions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from players.baseline.player import choose_ruleset

from coworld.config import ruleset_limits
from coworld.episode import run_episode
from coworld.ruleset import validate_ruleset
from coworld.studio import StudioVariantCatalog, compose_run_config
from coworld.studio_runs import ArtifactStore, SampledLiveRun


DEFAULT_OUTPUT = ROOT / "build" / "studio" / "benchmark.json"


def benchmark_case(*, ranked: bool, artifact_root: Path) -> dict[str, object]:
    catalog = StudioVariantCatalog.load()
    variant = catalog.variant("solo-ladder")
    scenario = None if ranked else str(variant.scenarios[0]["id"])
    mode = "ranked-preview" if ranked else "exploration"
    started = perf_counter_ns()
    config_started = perf_counter_ns()
    config = compose_run_config(
        catalog,
        variant_id="solo-ladder",
        mode=mode,
        scenario_id=scenario,
        seed="17",
        timesteps=None if ranked else 100,
    )
    config_ns = perf_counter_ns() - config_started
    source = json.loads((ROOT / "rulesets" / "worked-example.json").read_text())
    validation_started = perf_counter_ns()
    validation = validate_ruleset(source, ruleset_limits(config.resolved_config))
    validation_ns = perf_counter_ns() - validation_started
    if not validation.valid:
        raise RuntimeError("benchmark ruleset is invalid")
    rulesets = (validation.normalized,) + tuple(
        choose_ruleset(target.as_dict()) for target in config.resolved_targets[1:]
    )
    frames: list[bytes] = []
    live = SampledLiveRun(
        "0" * 32,
        timesteps=int(config.resolved_config["timesteps"]),
        publisher=lambda _run_id, payload: frames.append(payload),
        progress=lambda _tick, _scores: None,
        cancelled=lambda: False,
    )
    engine_started = perf_counter_ns()
    results, replay, timings = run_episode(
        config.engine_config,
        rulesets,
        emit_timing_logs=False,
        submitted=(True,) + (False,) * (len(rulesets) - 1),
        header_sink=live.header_sink,
        frame_sink=live.frame_sink,
    )
    engine_ns = perf_counter_ns() - engine_started
    finalize_started = perf_counter_ns()
    live.finalize(results)
    finalize_ns = perf_counter_ns() - finalize_started
    store = ArtifactStore(artifact_root)
    artifact_started = perf_counter_ns()
    store.publish("0" * 32, replay=replay, results=results, studio={"seed": config.seed})
    artifact_ns = perf_counter_ns() - artifact_started
    total_ns = perf_counter_ns() - started
    wire_bytes = sum(map(len, frames))
    return {
        "name": "ranked-1000" if ranked else "quick-100",
        "mode": mode,
        "scenario_id": config.scenario_id,
        "timesteps_completed": results["timesteps_completed"],
        "timing_ns": {
            "config": config_ns,
            "validation": validation_ns,
            "engine_with_observers": engine_ns,
            "live_finalization": finalize_ns,
            "artifact_publish": artifact_ns,
            "total": total_ns,
            "engine_reported_phases": sum(timings["phases_ns"].values()),
        },
        "live": {
            "sample_interval": live.sample_interval,
            "frames": len(frames),
            "wire_bytes": wire_bytes,
            "wire_ceiling_bytes": 24 * 1024 * 1024,
            "max_frame_bytes": max(map(len, frames)),
            "per_frame_ceiling_bytes": 8 * 1024 * 1024,
        },
        "artifacts": {
            "replay_compressed_bytes": len(replay),
            "replay_raw_bytes": results["result.replay_raw_bytes"],
            "results_json_bytes": len(store.read_artifact("0" * 32, "results.json")),
            "studio_json_bytes": len(store.read_artifact("0" * 32, "studio.json")),
        },
        "acceptance": {
            "wire_within_ceiling": wire_bytes <= 24 * 1024 * 1024,
            "frames_within_ceiling": max(map(len, frames)) <= 8 * 1024 * 1024,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranked", action="store_true", help="also run the ranked-fidelity fixture")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ruleset-studio-benchmark-") as temporary:
        cases = [benchmark_case(ranked=False, artifact_root=Path(temporary) / "quick")]
        if arguments.ranked:
            cases.append(benchmark_case(ranked=True, artifact_root=Path(temporary) / "ranked"))
    report = {"clock": "perf_counter_ns", "wall_clock_assertions": False, "ranked_included": arguments.ranked, "cases": cases}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
