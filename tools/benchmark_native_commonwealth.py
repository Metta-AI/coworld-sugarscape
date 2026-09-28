#!/usr/bin/env python3
"""Measure full Commonwealth world ticks in synchronized native processes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import subprocess
import sys
import time
from typing import Mapping, TextIO


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from coworld.config import build_dtl_config, resolve_episode_config, ruleset_limits  # noqa: E402
from coworld.instrumentation import EpisodeInstrumentation  # noqa: E402
from coworld.native_fixture import NativeReferenceWorld  # noqa: E402
from coworld.native_oracle import NativeSnapshot, snapshot_world  # noqa: E402
from coworld.native_simulator import build_native_simulator  # noqa: E402
from coworld.ruleset import compile_ruleset  # noqa: E402
from coworld.seats import parse_trait_ranges  # noqa: E402
from coworld.targets import load_target_catalog, resolve_seat_targets  # noqa: E402
from players.baseline.player import choose_ruleset  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _gpu_inventory() -> list[dict[str, str]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    completed = subprocess.run(
        [
            executable,
            "--query-gpu=name,uuid",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    inventory = []
    for line in completed.stdout.splitlines():
        name, uuid = (value.strip() for value in line.split(",", 1))
        inventory.append({"name": name, "uuid": uuid})
    return inventory


def parse_seeds(raw: str, worlds: int) -> list[int]:
    if worlds < 1:
        raise ValueError("worlds must be positive")
    values = [int(value) for value in raw.split(",")]
    if any(seed < 0 for seed in values):
        raise ValueError("seeds must be non-negative")
    if len(values) == 1:
        return list(range(values[0], values[0] + worlds))
    if len(values) != worlds:
        raise ValueError("--seeds must contain one base seed or one seed per world")
    return values


def prepare_commonwealth(seed: int, ticks: int) -> tuple[NativeSnapshot, dict[str, object], list[dict[str, object]]]:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text(encoding="utf-8"))
    variant = next(item for item in manifest["variants"] if item["id"] == "commonwealth")
    config = variant["game_config"] | {"seed": seed, "timesteps": ticks}
    resolved = resolve_episode_config(config)
    targets = resolve_seat_targets(
        resolved["targets"],
        seats=int(resolved["seats"]),
        measurement_window=int(resolved["measurement_window"]),
        catalog=load_target_catalog(),
    )
    rulesets = [choose_ruleset(target.as_dict()) for target in targets]
    compiled = [
        compile_ruleset(ruleset, limits=ruleset_limits(resolved))
        for ruleset in rulesets
    ]
    world = NativeReferenceWorld(
        build_dtl_config(resolved),
        compiled,
        parse_trait_ranges(resolved.get("trait_ranges")),
        instrumentation=EpisodeInstrumentation(enabled=False),
    )
    return snapshot_world(world), resolved, rulesets


def _read_message(
    stream: TextIO, expected: str
) -> tuple[Mapping[str, object], int]:
    line = stream.readline()
    received_ns = time.monotonic_ns()
    if not line:
        raise RuntimeError(f"native benchmark worker exited before {expected}")
    value = json.loads(line)
    if not isinstance(value, Mapping) or value.get("phase") != expected:
        raise RuntimeError(f"expected native phase {expected}, got {value}")
    return value, received_ns


def _read_all(
    processes: list[subprocess.Popen[str]], expected: str, timeout: float
) -> tuple[list[Mapping[str, object]], int]:
    selector = selectors.DefaultSelector()
    messages: dict[int, Mapping[str, object]] = {}
    final_received_ns = 0
    for index, process in enumerate(processes):
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ, index)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"native workers did not reach {expected}")
            events = selector.select(remaining)
            if not events:
                raise TimeoutError(f"native workers did not reach {expected}")
            for key, _ in events:
                message, received_ns = _read_message(key.fileobj, expected)
                messages[key.data] = message
                final_received_ns = max(final_received_ns, received_ns)
                selector.unregister(key.fileobj)
    finally:
        selector.close()
    return [messages[index] for index in range(len(processes))], final_received_ns


def run_wave(
    snapshots: list[NativeSnapshot], *, ticks: int, binary: Path, timeout: float
) -> tuple[list[dict[str, object]], int]:
    processes: list[subprocess.Popen[str]] = []
    try:
        for snapshot in snapshots:
            process = subprocess.Popen(
                [str(binary), "bench-worker", "--ticks", str(ticks)],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdin is not None
            process.stdin.write(_canonical_json(snapshot.as_json()).decode("utf-8") + "\n")
            process.stdin.flush()
            processes.append(process)
        _read_all(processes, "ready", timeout)
        wave_started_ns = time.monotonic_ns()
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("start\n")
            process.stdin.flush()
        finished, wave_finished_ns = _read_all(processes, "finished", timeout)
        wave_elapsed_ns = wave_finished_ns - wave_started_ns
        elapsed_ns = []
        completed_ticks = []
        for message in finished:
            elapsed = message.get("elapsedNs")
            completed = message.get("ticks")
            if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed <= 0:
                raise RuntimeError("native worker reported an invalid elapsedNs")
            if (
                isinstance(completed, bool)
                or not isinstance(completed, int)
                or not 0 <= completed <= ticks
            ):
                raise RuntimeError("native worker reported an invalid tick count")
            elapsed_ns.append(elapsed)
            completed_ticks.append(completed)
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("collect\n")
            process.stdin.flush()
        collected, _ = _read_all(processes, "result", timeout)
        worlds = []
        for initial, completed, elapsed, message in zip(
            snapshots, completed_ticks, elapsed_ns, collected, strict=True
        ):
            final = NativeSnapshot.from_json(message["snapshot"])
            worlds.append(
                {
                    "seed": None,
                    "configuration_sha256": initial.config_sha256,
                    "ruleset_sha256": list(initial.ruleset_sha256),
                    "requested_ticks": ticks,
                    "completed_ticks": completed,
                    "worker_elapsed_ns": elapsed,
                    "initial_population": len(initial.agents),
                    "final_population": len(final.agents),
                    "final_timestep": final.timestep,
                    "final_state_sha256": _sha256(_canonical_json(final.as_json())),
                }
            )
        for process in processes:
            process.wait(timeout=timeout)
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(f"native worker failed: {stderr}")
        return worlds, wave_elapsed_ns
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()


def benchmark(
    *,
    seeds: list[int],
    workers: int,
    ticks: int,
    binary: Path,
    timeout: float = 600,
) -> dict[str, object]:
    if (
        not seeds
        or any(seed < 0 for seed in seeds)
        or workers < 1
        or ticks < 1
        or timeout <= 0
    ):
        raise ValueError("seeds, workers, ticks, and timeout must be positive")
    prepared = [prepare_commonwealth(seed, ticks) for seed in seeds]
    snapshots = [item[0] for item in prepared]
    worlds = []
    elapsed_ns = 0
    wave_elapsed_ns = []
    for offset in range(0, len(snapshots), workers):
        wave, wave_elapsed = run_wave(
            snapshots[offset : offset + workers],
            ticks=ticks,
            binary=binary,
            timeout=timeout,
        )
        for seed, world in zip(
            seeds[offset : offset + workers], wave, strict=True
        ):
            world["seed"] = seed
        worlds.extend(wave)
        wave_elapsed_ns.append(wave_elapsed)
        elapsed_ns += wave_elapsed
    completed = sum(int(world["completed_ticks"]) for world in worlds)
    rate = completed * 1_000_000_000 / elapsed_ns
    manifest_bytes = (ROOT / "coworld_manifest.json").read_bytes()
    native_bytes = (ROOT / "native" / "sugarscape_native.nim").read_bytes()
    provenance_paths = {
        "benchmark_driver": ROOT / "tools" / "benchmark_native_commonwealth.py",
        "native_oracle": ROOT / "src" / "coworld" / "native_oracle.py",
        "native_fixture": ROOT / "src" / "coworld" / "native_fixture.py",
        "native_simulator": ROOT / "src" / "coworld" / "native_simulator.py",
        "config": ROOT / "src" / "coworld" / "config.py",
        "ruleset": ROOT / "src" / "coworld" / "ruleset.py",
        "baseline_player": ROOT / "players" / "baseline" / "player.py",
    }
    resolved = prepared[0][1]
    rulesets = prepared[0][2]
    resolved_without_seed = {
        key: value for key, value in resolved.items() if key != "seed"
    }
    return {
        "backend": "nim_cpu",
        "mode": "full_commonwealth_v7",
        "metric": "completed_whole_world_ticks_per_second",
        "replay_enabled": False,
        "compression_enabled": False,
        "measurement_enabled": False,
        "instrumentation_enabled": False,
        "timing_scope": "sum of parent-observed synchronized wave windows, from immediately before the first start dispatch through receipt of the final finished line",
        "timing_excludes": [
            "world construction",
            "process startup",
            "snapshot parsing",
            "final snapshot serialization",
            "replay",
            "compression",
        ],
        "workers": workers,
        "world_count": len(seeds),
        "seeds": seeds,
        "requested_ticks_per_world": ticks,
        "completed_world_ticks": completed,
        "elapsed_ns": elapsed_ns,
        "wave_elapsed_ns": wave_elapsed_ns,
        "world_ticks_per_second": rate,
        "target_world_ticks_per_second": 30_000,
        "target_met": rate >= 30_000,
        "worlds": worlds,
        "configuration": {
            "variant": "commonwealth",
            "manifest_game_config": next(
                item["game_config"]
                for item in json.loads(manifest_bytes)["variants"]
                if item["id"] == "commonwealth"
            ),
            "resolved_config_without_seed": resolved_without_seed,
            "resolved_without_seed_sha256": _sha256(
                _canonical_json(resolved_without_seed)
            ),
            "rulesets": rulesets,
            "width": snapshots[0].width,
            "height": snapshots[0].height,
            "initial_population": len(snapshots[0].agents),
        },
        "source": {
            "schema_version": snapshots[0].as_json()["schemaVersion"],
            "dtl_commit": snapshots[0].as_json()["sourcePin"],
            "manifest_sha256": _sha256(manifest_bytes),
            "native_source_sha256": _sha256(native_bytes),
            "binary_sha256": _sha256(binary.read_bytes()),
            "provenance_sha256": {
                name: _sha256(path.read_bytes())
                for name, path in provenance_paths.items()
            },
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "git_status": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).splitlines(),
        },
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "cpu_affinity": (
                sorted(os.sched_getaffinity(0))
                if hasattr(os, "sched_getaffinity")
                else None
            ),
            "slurm": {
                name: os.environ.get(name)
                for name in (
                    "SLURM_JOB_ID",
                    "SLURM_JOB_NAME",
                    "SLURM_JOB_PARTITION",
                    "SLURM_NODELIST",
                    "SLURM_NTASKS",
                    "SLURM_PROCID",
                    "SLURM_CPUS_ON_NODE",
                    "SLURM_CPUS_PER_TASK",
                    "SLURM_JOB_GPUS",
                    "SLURM_GPUS",
                    "CUDA_VISIBLE_DEVICES",
                )
            },
            "gpus": _gpu_inventory(),
            "python": sys.version,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=1_000)
    parser.add_argument("--worlds", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seeds", default="1729")
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must not already exist")
    try:
        seeds = parse_seeds(args.seeds, args.worlds)
        binary = build_native_simulator()
        report = benchmark(
            seeds=seeds,
            workers=args.workers,
            ticks=args.ticks,
            binary=binary,
            timeout=args.timeout_seconds,
        )
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(args.output),
                "world_ticks_per_second": report["world_ticks_per_second"],
                "target_met": report["target_met"],
            }
        )
    )


if __name__ == "__main__":
    main()
