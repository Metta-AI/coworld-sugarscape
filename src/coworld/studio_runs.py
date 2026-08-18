"""Ruleset Studio run lifecycle, live-frame sampling, and local artifacts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from threading import Event, Lock, Thread
import time
from typing import Callable, Literal, Mapping, Sequence
from uuid import uuid4

from players.baseline.player import choose_ruleset

from .config import ruleset_limits
from .episode import run_episode
from .studio import (
    StudioRunConfig,
    StudioVariantCatalog,
    compose_run_config,
)
from .ruleset import ValidationResult, validate_ruleset
from .targets import DEFAULT_CATALOG_PATH
from .v1_frames import V1FrameMaterializer


DEFAULT_RUNS_PATH = Path(__file__).resolve().parents[2] / "build" / "studio" / "runs"
MAX_STORED_RUNS = 20
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_TERMINAL_STATES = {"done", "error", "cancelled"}
_LOGGER = logging.getLogger(__name__)

FramePublisher = Callable[[str, bytes], None]
EpisodeRunner = Callable[..., tuple[dict[str, object], bytes, dict[str, object]]]


class RunCancelled(Exception):
    """Abort an episode at its next frame-observer boundary."""


class RunBusy(RuntimeError):
    """Raised when the global-RNG run slot still has a worker."""


class RunServerStopping(RuntimeError):
    """Raised after shutdown has made the coordinator non-accepting."""


class StudioRunNotFound(KeyError):
    """Raised for an unknown run identifier."""


class StudioCompileError(ValueError):
    """Carry structured SugarLang validation errors to the API edge."""

    def __init__(self, validation: dict[str, object]) -> None:
        self.validation = validation
        super().__init__("compile failed")


@dataclass(slots=True)
class StudioRun:
    """Mutable state for one reserved Studio worker."""

    run_id: str
    config: StudioRunConfig
    rulesets: tuple[object, ...]
    submitted: tuple[bool, ...]
    opponents: tuple[dict[str, object], ...]
    studio_metadata: dict[str, object]
    state: Literal["running", "done", "error", "cancelling", "cancelled"] = "running"
    tick: int = 0
    running_scores: list[float | None] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    results: dict[str, object] | None = None
    error: str | None = None
    transport_error: str | None = None
    worker: Thread | None = field(default=None, repr=False)
    cancel_requested: Event = field(default_factory=Event, repr=False)

    @property
    def total(self) -> int:
        return int(self.config.resolved_config["timesteps"])


@dataclass(frozen=True, slots=True)
class RunWorkerSnapshot:
    run_id: str
    state: str
    worker: Thread | None


class RunRegistry:
    """Serialize Studio run state without holding locks around expensive work."""

    def __init__(self, *, max_runs: int = MAX_STORED_RUNS) -> None:
        if max_runs < 1:
            raise ValueError("max_runs must be positive")
        self._lock = Lock()
        self._max_runs = max_runs
        self._runs: dict[str, StudioRun] = {}
        self._active_run_id: str | None = None
        self._displayed_run_id: str | None = None
        self._accepting = True

    def reserve(self, run: StudioRun) -> None:
        with self._lock:
            if not self._accepting:
                raise RunServerStopping("studio run service is stopping")
            self._reap_terminal_locked()
            if self._active_run_id is not None:
                raise RunBusy("a studio run is already in progress")
            self._runs[run.run_id] = run
            self._active_run_id = run.run_id

    def attach_worker(self, run_id: str, worker: Thread) -> None:
        with self._lock:
            run = self._require_locked(run_id)
            if run.worker is not None:
                raise RuntimeError("studio run already has a worker")
            run.worker = worker

    def progress(
        self,
        run_id: str,
        tick: int,
        running_scores: Sequence[float | None],
    ) -> None:
        with self._lock:
            run = self._require_locked(run_id)
            run.tick = tick
            run.running_scores = list(running_scores)

    def finish(
        self,
        run_id: str,
        state: Literal["done", "error", "cancelled"],
        *,
        results: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            run = self._require_locked(run_id)
            run.state = state
            run.results = results
            run.error = error
            self._evict_terminal_locked()

    def cancel(self, run_id: str) -> dict[str, object]:
        with self._lock:
            run = self._require_locked(run_id)
            if run.state == "running":
                run.state = "cancelling"
                run.cancel_requested.set()
            return deepcopy(self._status_locked(run))

    def status(self, run_id: str) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._status_locked(self._require_locked(run_id)))

    def has_run(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def is_live_run(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            return run is not None and run.state not in _TERMINAL_STATES

    def record_transport_error(self, run_id: str, message: str) -> None:
        with self._lock:
            run = self._require_locked(run_id)
            if run.transport_error is None:
                run.transport_error = message

    def worker(self, run_id: str) -> Thread | None:
        with self._lock:
            return self._require_locked(run_id).worker

    def active_run(self) -> StudioRun | None:
        with self._lock:
            if self._active_run_id is None:
                return None
            return self._require_locked(self._active_run_id)

    def active_worker_snapshot(self) -> RunWorkerSnapshot | None:
        with self._lock:
            if self._active_run_id is None:
                return None
            run = self._require_locked(self._active_run_id)
            return RunWorkerSnapshot(run.run_id, run.state, run.worker)

    def set_displayed(self, run_id: str | None) -> None:
        with self._lock:
            if run_id is not None:
                self._require_locked(run_id)
            self._displayed_run_id = run_id
            self._evict_terminal_locked()

    def protected_run_ids(self) -> set[str]:
        with self._lock:
            return {
                run_id
                for run_id in (self._active_run_id, self._displayed_run_id)
                if run_id is not None
            }

    def stop_accepting(self) -> None:
        with self._lock:
            self._accepting = False

    def reap_terminal(self) -> None:
        with self._lock:
            self._reap_terminal_locked()

    def _reap_terminal_locked(self) -> None:
        if self._active_run_id is None:
            self._evict_terminal_locked()
            return
        run = self._require_locked(self._active_run_id)
        worker = run.worker
        if run.state not in _TERMINAL_STATES:
            return
        # A dead thread cannot become live again, so this join cannot block;
        # keeping the lock preserves reservation ordering during the reap.
        if worker is not None and worker.ident is not None and not worker.is_alive():
            worker.join()
        self._active_run_id = None
        self._evict_terminal_locked()

    def _evict_terminal_locked(self) -> None:
        protected = {self._active_run_id, self._displayed_run_id}
        candidates = sorted(
            (
                run
                for run in self._runs.values()
                if run.run_id not in protected and run.state in _TERMINAL_STATES
            ),
            key=lambda run: run.started_at,
        )
        while len(self._runs) > self._max_runs and candidates:
            del self._runs[candidates.pop(0).run_id]

    def _require_locked(self, run_id: str) -> StudioRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise StudioRunNotFound(run_id) from error

    def _status_locked(self, run: StudioRun) -> dict[str, object]:
        status: dict[str, object] = {
            "run_id": run.run_id,
            "state": run.state,
            "tick": run.tick,
            "total": run.total,
            "running_scores": list(run.running_scores),
            "started_at": run.started_at,
        }
        if run.state == "done":
            status.update(
                {
                    "results": run.results,
                    "replay_url": f"/runs/{run.run_id}/replay.bin",
                    "viewer_url": (
                        f"/runs/{run.run_id}/client/replay"
                        f"?replay=/runs/{run.run_id}/replay.bin"
                    ),
                }
            )
        elif run.state == "error":
            status["error"] = run.error or "run failed"
        if run.transport_error is not None:
            status["transport_error"] = run.transport_error
        return status


class SampledLiveRun:
    """Turn every v3 delta into progress and sampled serialized v1 frames."""

    def __init__(
        self,
        run_id: str,
        *,
        timesteps: int,
        publisher: FramePublisher,
        progress: Callable[[int, Sequence[float | None]], None],
        cancelled: Callable[[], bool],
    ) -> None:
        self.run_id = run_id
        self.sample_interval = max(1, timesteps // 240)
        self.publisher = publisher
        self.progress = progress
        self.cancelled = cancelled
        self.materializer: V1FrameMaterializer | None = None
        self.held_frame: bytes | None = None
        self.last_v3_frame: dict[str, object] | None = None
        self.running_scores: list[float | None] = []

    def header_sink(self, header: dict[str, object]) -> None:
        self.materializer = V1FrameMaterializer(header)
        self._emit(self.materializer.initial_frame())

    def frame_sink(self, frame: dict[str, object]) -> None:
        if self.cancelled():
            self.held_frame = None
            raise RunCancelled()
        if self.held_frame is not None:
            self.publisher(self.run_id, self.held_frame)
            self.held_frame = None
        materializer = self._materializer()
        materializer.apply_frame(frame)
        self.last_v3_frame = frame
        self._update_running_scores(frame)
        tick = int(frame["timestep"])
        self.progress(tick, self.running_scores)
        if tick % self.sample_interval == 0:
            self.held_frame = _encode_json(materializer.materialize())

    def finalize(self, results: Mapping[str, object]) -> None:
        materializer = self._materializer()
        if self.last_v3_frame is not None:
            # ReplayWriter.finish may add terminal measurements after frame_sink.
            materializer.apply_frame(self.last_v3_frame)
            previous_scores = list(self.running_scores)
            self._update_running_scores(self.last_v3_frame)
            if self.running_scores != previous_scores:
                self.progress(int(self.last_v3_frame["timestep"]), self.running_scores)
        self.held_frame = None
        self._emit(
            materializer.materialize(
                final=True,
                final_scores=results["scores"],
                final_details=results.get("details"),
            )
        )

    def discard(self) -> None:
        self.held_frame = None

    def _emit(self, frame: Mapping[str, object]) -> None:
        self.publisher(self.run_id, _encode_json(frame))

    def _materializer(self) -> V1FrameMaterializer:
        if self.materializer is None:
            raise RuntimeError("episode did not publish a bootstrap header")
        return self.materializer

    def _update_running_scores(self, frame: Mapping[str, object]) -> None:
        for reading in frame.get("running") or []:
            seat = int(reading["seat"])
            while len(self.running_scores) <= seat:
                self.running_scores.append(None)
            score = reading.get("score")
            self.running_scores[seat] = float(score) if score is not None else None


class ArtifactStore:
    """Atomically publish immutable run directories and prune old artifacts."""

    def __init__(
        self,
        root: Path | str = DEFAULT_RUNS_PATH,
        *,
        max_runs: int = MAX_STORED_RUNS,
    ) -> None:
        if max_runs <= 0:
            raise ValueError("max_runs must be positive")
        supplied = Path(root)
        if supplied.is_symlink():
            raise ValueError("artifact store cannot be a symlink")
        self.root = supplied
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_runs = max_runs
        self._lock = Lock()

    def publish(
        self,
        run_id: str,
        *,
        replay: bytes,
        results: Mapping[str, object],
        studio: Mapping[str, object],
    ) -> Path:
        self._validate_run_id(run_id)
        with self._lock:
            destination = self.root / run_id
            if destination.exists():
                raise FileExistsError(f"run artifacts already exist: {run_id}")
            temporary = Path(tempfile.mkdtemp(dir=self.root, prefix=f".{run_id}."))
            try:
                self._write(temporary / "replay.bin", replay)
                self._write(temporary / "results.json", _encode_json(results))
                self._write(temporary / "studio.json", _encode_json(studio))
                os.rename(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return destination

    def read_artifact(self, run_id: str, name: str) -> bytes:
        self._validate_run_id(run_id)
        if name not in {"replay.bin", "results.json", "studio.json"}:
            raise FileNotFoundError(name)
        with self._lock:
            run_path = self.root / run_id
            path = run_path / name
            if run_path.is_symlink() or path.is_symlink() or not path.is_file():
                raise FileNotFoundError(path)
            return path.read_bytes()

    def has_run(self, run_id: str) -> bool:
        try:
            self._validate_run_id(run_id)
        except ValueError:
            return False
        with self._lock:
            run_path = self.root / run_id
            return run_path.is_dir() and not run_path.is_symlink()

    def prune(self, *, protected: set[str] | None = None) -> list[str]:
        protected_ids = set(protected or ())
        with self._lock:
            directories = [
                path
                for path in self.root.iterdir()
                if _RUN_ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
            ]
            directories.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
            removed: list[str] = []
            while len(directories) > self.max_runs:
                victim = next(
                    (path for path in directories if path.name not in protected_ids),
                    None,
                )
                if victim is None:
                    break
                shutil.rmtree(victim)
                directories.remove(victim)
                removed.append(victim.name)
            return removed

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        with path.open("xb") as artifact:
            artifact.write(payload)
            artifact.flush()
            os.fsync(artifact.fileno())

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid studio run id")


class RunCoordinator:
    """Prepare runs, own worker threads, and publish their terminal artifacts."""

    def __init__(
        self,
        registry: RunRegistry,
        artifacts: ArtifactStore,
        *,
        publisher: FramePublisher,
        episode_runner: EpisodeRunner = run_episode,
        target_catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    ) -> None:
        self.registry = registry
        self.artifacts = artifacts
        self.publisher = publisher
        self.episode_runner = episode_runner
        self.target_catalog_path = target_catalog_path

    def start(
        self,
        catalog: StudioVariantCatalog,
        *,
        ruleset: object,
        variant_id: str,
        mode: Literal["ranked-preview", "exploration", "fixed"],
        seed: str | None,
        scenario_id: str | None = None,
        timesteps: int | None = None,
    ) -> dict[str, object]:
        config = compose_run_config(
            catalog,
            variant_id=variant_id,
            mode=mode,
            seed=seed,
            scenario_id=scenario_id,
            timesteps=timesteps,
            target_catalog_path=self.target_catalog_path,
        )
        validation = validate_ruleset(ruleset, ruleset_limits(config.resolved_config))
        if not validation.valid:
            raise StudioCompileError(_validation_payload(validation))
        working_ruleset = validation.normalized

        targets = config.resolved_targets
        players = config.resolved_config.get("players") or []
        opponents = tuple(
            {
                "seat": seat,
                "name": (
                    players[seat].get("name")
                    if seat < len(players) and isinstance(players[seat], Mapping)
                    else f"Seat {seat + 1}"
                ),
                "policy": "baseline",
            }
            for seat in range(1, len(targets))
        )
        run_rulesets = (working_ruleset,) + tuple(
            choose_ruleset(target.as_dict()) for target in targets[1:]
        )
        overrides = {"timesteps": timesteps} if timesteps is not None else {}
        metadata: dict[str, object] = {
            "variant": config.variant_id,
            "mode": config.mode,
            "scenario_id": config.scenario_id,
            "context_id": config.context_id,
            "seed": config.seed,
            "opponents": list(opponents),
            "overrides": overrides,
        }
        run = StudioRun(
            uuid4().hex,
            config,
            run_rulesets,
            (True,) + (False,) * (len(run_rulesets) - 1),
            opponents,
            metadata,
            running_scores=[None] * len(run_rulesets),
        )
        self.registry.reserve(run)
        worker = Thread(
            target=self._run_worker,
            args=(run,),
            name=f"studio-run-{run.run_id}",
            daemon=True,
        )
        self.registry.attach_worker(run.run_id, worker)
        try:
            worker.start()
        except Exception as exception:
            self.registry.finish(
                run.run_id,
                "error",
                error=f"{type(exception).__name__}: run failed",
            )
            self.run_finished(run.run_id)
            raise
        return {
            "run_id": run.run_id,
            "seed": run.config.seed,
            "scenario_id": run.config.scenario_id,
            "context_id": run.config.context_id,
            "seats": len(run.rulesets),
            "timesteps": run.total,
            "opponents": list(run.opponents),
        }

    def cancel(self, run_id: str) -> dict[str, object]:
        return self.registry.cancel(run_id)

    def status(self, run_id: str) -> dict[str, object]:
        return self.registry.status(run_id)

    def has_run(self, run_id: str) -> bool:
        return self.registry.has_run(run_id) or self.artifacts.has_run(run_id)

    def is_live_run(self, run_id: str) -> bool:
        return self.registry.is_live_run(run_id)

    def record_transport_error(self, run_id: str, message: str) -> None:
        self.registry.record_transport_error(run_id, message)

    def set_displayed(self, run_id: str | None) -> None:
        self.registry.set_displayed(run_id)

    def shutdown(self, timeout: float) -> bool:
        self.registry.stop_accepting()
        snapshot = self.registry.active_worker_snapshot()
        if snapshot is None:
            return True
        self.registry.cancel(snapshot.run_id)
        snapshot = self.registry.active_worker_snapshot() or snapshot
        worker = snapshot.worker
        if worker is None or worker.ident is None:
            if snapshot.state in _TERMINAL_STATES:
                self.registry.reap_terminal()
                return True
            return False
        worker.join(timeout)
        if worker.is_alive():
            return False
        self.registry.reap_terminal()
        return True

    def _run_worker(self, run: StudioRun) -> None:
        live = SampledLiveRun(
            run.run_id,
            timesteps=run.total,
            publisher=self.publisher,
            progress=lambda tick, scores: self.registry.progress(
                run.run_id, tick, scores
            ),
            cancelled=run.cancel_requested.is_set,
        )
        state: Literal["done", "error", "cancelled"] = "error"
        results: dict[str, object] | None = None
        error = "run failed"
        try:
            results, replay, _timings = self.episode_runner(
                run.config.engine_config,
                run.rulesets,
                emit_timing_logs=False,
                submitted=run.submitted,
                header_sink=live.header_sink,
                frame_sink=live.frame_sink,
                target_catalog_path=self.target_catalog_path,
            )
            live.finalize(results)
            self.artifacts.publish(
                run.run_id,
                replay=replay,
                results=results,
                studio=run.studio_metadata,
            )
            state = "done"
            error = ""
        except RunCancelled:
            live.discard()
            state = "cancelled"
            error = ""
        except Exception as exception:
            live.discard()
            error = f"{type(exception).__name__}: run failed"
            _LOGGER.exception("studio run failed", extra={"run_id": run.run_id})
        finally:
            self.registry.finish(
                run.run_id,
                state,
                results=results if state == "done" else None,
                error=error or None,
            )
        if state == "done":
            try:
                self.artifacts.prune(protected=self.registry.protected_run_ids())
            except OSError:
                _LOGGER.exception("studio artifact pruning failed")


def _encode_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validation_payload(result: ValidationResult) -> dict[str, object]:
    return {
        "valid": result.valid,
        "normalized": result.normalized,
        "errors": [
            {"path": issue.path, "message": issue.message} for issue in result.errors
        ],
        "node_count": result.node_count,
        "byte_count": result.byte_count,
    }
