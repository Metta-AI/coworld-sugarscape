"""Synchronous, monotonic timing instrumentation for an episode."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import json
import logging
from time import perf_counter_ns
from typing import Iterator


_LOGGER = logging.getLogger("coworld.timings")


class EpisodeInstrumentation:
    """Collect phase and per-tick timings without touching the simulation RNG."""

    def __init__(self, *, enabled: bool = True, emit_logs: bool = True) -> None:
        self.enabled = enabled
        self.emit_logs = emit_logs
        self.current_tick: int | None = None
        self._phase_ns: dict[str, int] = defaultdict(int)
        self._subphase_ns: dict[str, int] = defaultdict(int)
        self._ticks: list[dict[str, object]] = []
        self._current_subphases: dict[str, int] | None = None

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Measure and aggregate one named episode phase."""

        if not self.enabled:
            yield
            return
        started = perf_counter_ns()
        try:
            yield
        finally:
            duration = perf_counter_ns() - started
            self._phase_ns[name] += duration
            self._log({"event": "phase_timing", "phase": name, "duration_ns": duration})

    def begin_tick(self, tick: int) -> int:
        """Open the timing record for one simulation tick."""

        self.current_tick = tick
        self._current_subphases = defaultdict(int)
        return perf_counter_ns() if self.enabled else 0

    def record_subphase(self, name: str, duration_ns: int) -> None:
        """Add elapsed nanoseconds to a tick sub-phase and its aggregate."""

        if not self.enabled:
            return
        self._subphase_ns[name] += duration_ns
        if self._current_subphases is not None:
            self._current_subphases[name] += duration_ns

    def end_tick(self, started_ns: int) -> None:
        """Close the current tick and emit one structured timing log line."""

        if not self.enabled:
            self.current_tick = None
            self._current_subphases = None
            return
        duration = perf_counter_ns() - started_ns
        record: dict[str, object] = {
            "timestep": self.current_tick,
            "total_ns": duration,
            "subphases_ns": dict(sorted((self._current_subphases or {}).items())),
        }
        self._ticks.append(record)
        self._log({"event": "tick_timing", **record})
        self.current_tick = None
        self._current_subphases = None

    def as_dict(self) -> dict[str, object]:
        """Return the JSON-ready aggregate timing block."""

        return {
            "clock": "perf_counter_ns",
            "phases_ns": dict(sorted(self._phase_ns.items())),
            "simulation": {
                "subphases_ns": dict(sorted(self._subphase_ns.items())),
                "ticks": list(self._ticks),
            },
        }

    def _log(self, event: dict[str, object]) -> None:
        if self.emit_logs:
            _LOGGER.info(json.dumps(event, sort_keys=True, separators=(",", ":")))


@contextmanager
def timed_subphase(instrumentation: EpisodeInstrumentation, name: str) -> Iterator[None]:
    """Measure a hot-path sub-phase, becoming a no-op when disabled."""

    if not instrumentation.enabled:
        yield
        return
    started = perf_counter_ns()
    try:
        yield
    finally:
        instrumentation.record_subphase(name, perf_counter_ns() - started)
