"""Pure-data entry point for one synchronous Sugarscape episode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .config import build_dtl_config, resolve_episode_config, ruleset_limits
from .instrumentation import EpisodeInstrumentation
from .measurement import RollingMeasurements
from .replay import FrameSink, ReplayWriter
from .ruleset import CompiledRuleset, compile_ruleset, validate_ruleset
from .scoring import score_histogram
from .seats import parse_trait_ranges
from .simulation import CoworldSugarscape
from .targets import DEFAULT_CATALOG_PATH, load_target_catalog, resolve_seat_targets


def run_episode(
    config: Mapping[str, object],
    rulesets: Sequence[object],
    *,
    seed_source: Callable[[], int] | None = None,
    emit_timing_logs: bool = True,
    submitted: Sequence[bool] | None = None,
    frame_sink: FrameSink | None = None,
    target_catalog_path: Path | str = DEFAULT_CATALOG_PATH,
) -> tuple[dict[str, object], bytes, dict[str, object]]:
    """Run an episode and return complete results, replay bytes, and timings."""

    instrumentation = EpisodeInstrumentation(emit_logs=emit_timing_logs)
    with instrumentation.phase("config_resolution"):
        resolved = resolve_episode_config(config, seed_source=seed_source)
        limits = ruleset_limits(resolved)
        catalog = load_target_catalog(target_catalog_path)
        seat_count = int(resolved["seats"])
        targets = resolve_seat_targets(
            resolved.get("targets"),
            seats=seat_count,
            measurement_window=int(resolved["measurement_window"]),
            catalog=catalog,
        )
    if len(rulesets) != seat_count:
        raise ValueError("one ruleset submission is required for each seat")
    submitted_flags = tuple(submitted) if submitted is not None else (True,) * seat_count
    if len(submitted_flags) != seat_count or not all(isinstance(flag, bool) for flag in submitted_flags):
        raise ValueError("submitted must contain one boolean per seat")

    compiled: list[CompiledRuleset] = []
    for seat, raw_ruleset in enumerate(rulesets):
        with instrumentation.phase("ruleset_validation"):
            validation = validate_ruleset(raw_ruleset, limits=limits)
        if not validation.valid:
            details = "; ".join(str(error) for error in validation.errors)
            raise ValueError(f"seat {seat} ruleset is invalid: {details}")
        with instrumentation.phase("ruleset_compilation"):
            compiled.append(compile_ruleset(validation, limits=limits))

    with instrumentation.phase("world_build"):
        dtl_config = build_dtl_config(resolved)
        measurements = RollingMeasurements(
            seat_count,
            int(resolved["measurement_window"]),
            catalog,
        )
        world = CoworldSugarscape(
            dtl_config,
            compiled,
            parse_trait_ranges(resolved.get("trait_ranges")),
            instrumentation=instrumentation,
            measurements=measurements,
        )
        world.updateRuntimeStats()
        replay_writer = ReplayWriter(
            world,
            config=resolved,
            targets=targets,
            rulesets=compiled,
            measurements=measurements,
            histogram_interval=int(resolved["replay_histogram_interval"]),
            frame_sink=frame_sink,
        )
        world.replay_writer = replay_writer

    with instrumentation.phase("simulation"):
        for _ in range(dtl_config["timesteps"]):
            if not world.agents and not world.keepAlive:
                break
            world.doTimestep()

    with instrumentation.phase("measurement_assembly"):
        histograms = measurements.all_histograms()

    with instrumentation.phase("scoring"):
        seat_population = [0] * seat_count
        for agent in world.agents:
            seat_population[agent.seat] += 1
        scores: list[float] = []
        details: list[dict[str, object]] = []
        for seat, target in enumerate(targets):
            histogram = measurements.histogram(
                target.variable,
                scope=target.scope,
                seat=seat if target.scope == "seat" else None,
            )
            distribution_score = score_histogram(histogram, target.probs)
            scores.append(distribution_score.score)
            details.append(
                {
                    "seat": seat,
                    "target_id": target.id,
                    "target_scope": target.scope,
                    "target_variable": target.variable,
                    "score": distribution_score.score,
                    "w1": distribution_score.w1,
                    "js_divergence": distribution_score.js_divergence,
                    "submitted": submitted_flags[seat],
                    "ruleset_nodes": compiled[seat].node_count,
                    "agents_final": seat_population[seat],
                    "empty_measurement": distribution_score.empty_measurement,
                    "histogram": histogram.as_dict(),
                }
            )

    with instrumentation.phase("replay_serialization"):
        replay = replay_writer.finish(scores=scores, seat_details=details)

    with instrumentation.phase("result_assembly"):
        stats = world.runtimeStats
        results: dict[str, object] = {
            "seed": resolved["seed"],
            "scenario_index": resolved["scenario_index"],
            "timesteps_completed": world.timestep,
            "scores": scores,
            "details": details,
            "histograms": histograms,
            "targets": [target.as_dict() for target in targets],
            "score.match_mean": sum(scores) / len(scores),
            "score.match_min": min(scores),
            "result.population_final": len(world.agents),
            "result.gini_final": stats["giniCoefficient"],
            "result.mean_wealth_final": stats["meanWealth"],
            "result.extinct": len(world.agents) == 0,
            "result.timesteps_completed": world.timestep,
            "result.replay_raw_bytes": replay.raw_size_bytes,
            "result.replay_compressed_bytes": replay.compressed_size_bytes,
        }
        for seat, score in enumerate(scores):
            results[f"score.seat_{seat}"] = score
    timings = instrumentation.as_dict()
    results["timings"] = timings
    return results, replay.data, timings


def canonical_results_payload(results: Mapping[str, object]) -> bytes:
    """Serialize deterministic result content, excluding wall-clock timings."""

    stable = {key: value for key, value in results.items() if key != "timings"}
    return json.dumps(
        stable,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
