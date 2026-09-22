"""Build and invoke the native Sugarscape simulator."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Mapping

from .native_oracle import NativeSnapshot, step_python


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "native" / "sugarscape_native.nim"
DEFAULT_BINARY = ROOT / "native" / "bin" / "sugarscape-native"


@dataclass(frozen=True)
class NativeBenchmark:
    ticks: int
    elapsed_ns: int
    snapshot: NativeSnapshot


@dataclass(frozen=True)
class PythonBenchmark:
    ticks: int
    elapsed_ns: int
    snapshot: NativeSnapshot


def build_native_simulator(
    *, source: Path = DEFAULT_SOURCE, binary: Path = DEFAULT_BINARY
) -> Path:
    """Compile the checked-in Nim source into a task-owned binary."""

    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["nim", "c", "-d:release", f"-o:{binary}", str(source)],
        check=True,
        cwd=ROOT,
    )
    return binary


def step_native(
    snapshot: NativeSnapshot,
    ticks: int,
    *,
    binary: Path = DEFAULT_BINARY,
) -> NativeSnapshot:
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
        raise ValueError("ticks must be a non-negative integer")
    completed = subprocess.run(
        [str(binary), "step", "--ticks", str(ticks)],
        check=True,
        cwd=ROOT,
        input=json.dumps(snapshot.as_json(), allow_nan=False, separators=(",", ":")),
        capture_output=True,
        text=True,
    )
    return NativeSnapshot.from_json(json.loads(completed.stdout))


def benchmark_native(
    snapshot: NativeSnapshot,
    ticks: int,
    *,
    binary: Path = DEFAULT_BINARY,
) -> NativeBenchmark:
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
        raise ValueError("ticks must be a positive integer")
    completed = subprocess.run(
        [str(binary), "bench", "--ticks", str(ticks)],
        check=True,
        cwd=ROOT,
        input=json.dumps(snapshot.as_json(), allow_nan=False, separators=(",", ":")),
        capture_output=True,
        text=True,
    )
    raw = json.loads(completed.stdout)
    if not isinstance(raw, Mapping) or set(raw) != {"ticks", "elapsedNs", "snapshot"}:
        raise ValueError("native benchmark result has an invalid schema")
    completed_ticks = raw["ticks"]
    if (
        isinstance(completed_ticks, bool)
        or not isinstance(completed_ticks, int)
        or not 0 <= completed_ticks <= ticks
    ):
        raise ValueError("native benchmark reported an invalid completed tick count")
    elapsed_ns = raw["elapsedNs"]
    if (
        isinstance(elapsed_ns, bool)
        or not isinstance(elapsed_ns, int)
        or elapsed_ns <= 0
    ):
        raise ValueError("native benchmark elapsedNs must be a positive integer")
    return NativeBenchmark(
        completed_ticks,
        elapsed_ns,
        NativeSnapshot.from_json(raw["snapshot"]),
    )


def benchmark_python(snapshot: NativeSnapshot, ticks: int) -> PythonBenchmark:
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
        raise ValueError("ticks must be a positive integer")
    started = time.perf_counter_ns()
    final = step_python(snapshot, ticks)
    elapsed_ns = time.perf_counter_ns() - started
    return PythonBenchmark(final.timestep - snapshot.timestep, elapsed_ns, final)
