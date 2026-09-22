"""Build and invoke the native Sugarscape simulator."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Mapping

from .measurement import MeasurementTick
from .native_oracle import NativeSnapshot, step_python


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "native" / "sugarscape_native.nim"
DEFAULT_BINARY_ROOT = Path(tempfile.gettempdir()) / "coworld-sugarscape-native"


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


@dataclass(frozen=True)
class NativeEpisodeTick:
    tick: int
    snapshot: NativeSnapshot
    measurements: MeasurementTick


@dataclass(frozen=True)
class NativeEpisodeTerminal:
    reason: str
    ticks: int
    timestep: int
    population: int


NativeEpisodeEvent = NativeEpisodeTick | NativeEpisodeTerminal


class NativeEpisodeStream:
    """Validate the ordered JSONL events from one native episode process."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        initial: NativeSnapshot,
        tick_limit: int,
    ) -> None:
        self._process = process
        self._initial_timestep = initial.timestep
        self._latest_snapshot = initial
        self._configuration_sha256 = initial.config_sha256
        self._ruleset_sha256 = initial.ruleset_sha256
        self._rulesets = initial.rulesets
        self._tick_limit = tick_limit
        self._ticks = 0
        self._terminal = False

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    def __iter__(self) -> NativeEpisodeStream:
        return self

    def __next__(self) -> NativeEpisodeEvent:
        if self._terminal:
            raise StopIteration
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            returncode = self._process.wait()
            assert self._process.stderr is not None
            stderr = self._process.stderr.read()
            raise RuntimeError(
                f"native episode ended before terminal event ({returncode}): {stderr}"
            )
        raw = json.loads(line)
        if not isinstance(raw, Mapping) or "kind" not in raw:
            raise ValueError("native episode event must be an object with kind")
        if raw["kind"] == "tick":
            if set(raw) != {"kind", "tick", "snapshot"}:
                raise ValueError("native episode tick has an invalid schema")
            tick = raw["tick"]
            if (
                isinstance(tick, bool)
                or not isinstance(tick, int)
                or tick != self._ticks + 1
                or tick > self._tick_limit
            ):
                raise ValueError("native episode tick is out of sequence")
            snapshot = NativeSnapshot.from_json(raw["snapshot"])
            if snapshot.timestep != self._initial_timestep + tick:
                raise ValueError("native episode snapshot timestep is out of sequence")
            if (
                snapshot.config_sha256 != self._configuration_sha256
                or snapshot.ruleset_sha256 != self._ruleset_sha256
                or snapshot.rulesets != self._rulesets
            ):
                raise ValueError("native episode snapshot contract changed")
            self._ticks = tick
            self._latest_snapshot = snapshot
            return NativeEpisodeTick(tick, snapshot, snapshot.measurement_tick())
        if raw["kind"] != "terminal" or set(raw) != {
            "kind",
            "reason",
            "ticks",
            "timestep",
            "population",
        }:
            raise ValueError("native episode terminal has an invalid schema")
        reason = raw["reason"]
        ticks = raw["ticks"]
        timestep = raw["timestep"]
        population = raw["population"]
        if reason not in {"tick_limit", "extinct"}:
            raise ValueError("native episode terminal has an invalid reason")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (ticks, timestep, population)
        ):
            raise ValueError("native episode terminal counters must be integers")
        if (
            ticks != self._ticks
            or timestep != self._latest_snapshot.timestep
            or population != len(self._latest_snapshot.agents)
            or population < 0
            or (reason == "extinct") != (population == 0)
            or (reason == "tick_limit" and ticks != self._tick_limit)
        ):
            raise ValueError("native episode terminal is inconsistent with tick events")
        self._terminal = True
        returncode = self._process.wait()
        if returncode != 0:
            assert self._process.stderr is not None
            raise RuntimeError(
                f"native episode failed after terminal event ({returncode}): "
                f"{self._process.stderr.read()}"
            )
        return NativeEpisodeTerminal(reason, ticks, timestep, population)


@contextmanager
def native_episode(
    snapshot: NativeSnapshot,
    ticks: int,
    *,
    binary: Path,
) -> Iterator[NativeEpisodeStream]:
    """Start one persistent native process and clean it up on every exit path."""

    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
        raise ValueError("ticks must be a non-negative integer")
    process = subprocess.Popen(
        [str(binary), "episode", "--ticks", str(ticks)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(
            json.dumps(snapshot.as_json(), allow_nan=False, separators=(",", ":"))
            + "\n"
        )
        process.stdin.close()
        yield NativeEpisodeStream(process, snapshot, ticks)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        assert process.stdout is not None and process.stderr is not None
        process.stdout.close()
        process.stderr.close()


def build_native_simulator(
    *, source: Path = DEFAULT_SOURCE, binary: Path | None = None
) -> Path:
    """Compile the checked-in Nim source into a task-owned binary."""

    if binary is None:
        binary = DEFAULT_BINARY_ROOT / str(os.getpid()) / "simulator"
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "nim",
            "c",
            "-d:release",
            f"--nimcache:{binary.parent / 'nimcache'}",
            f"-o:{binary}",
            str(source),
        ],
        check=True,
        cwd=ROOT,
    )
    return binary


def step_native(
    snapshot: NativeSnapshot,
    ticks: int,
    *,
    binary: Path,
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
    binary: Path,
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
