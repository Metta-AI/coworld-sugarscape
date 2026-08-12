"""Deterministic zlib-compressed presentation-frame replay logs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Sequence
import zlib

from .measurement import RollingMeasurements
from .ruleset import CompiledRuleset
from .scoring import score_histogram
from .targets import Target


REPLAY_FORMAT = "sugarscape.replay.v3"
REPLAY_VERSION = 2
WEALTH_QUANTUM = 50
FrameSink = Callable[[dict[str, object]], None]

# Version 2 agent encoding: every agent's full state rides the replay, split
# so completeness does not defeat delta compaction.
# - Static traits are recorded ONCE per agent (header.roster for initial
#   agents, frame agent_deltas.births for newborns):
#     [id, seat, born_tick, sex01, vision, movement, sugar_metabolism,
#      spice_metabolism, max_age]
#   Age is deliberately NOT stored per tick — viewers derive it as
#   (current_tick - born_tick), otherwise every agent would upsert every tick.
# - Dynamic state upserts only on change:
#     [id, x, y, sugar_bucket, spice_bucket, tribe (-1 = none),
#      disease_count]
#   Sugar and spice are bucketed separately (WEALTH_QUANTUM presentation
#   precision, exact values stay in measurement/scoring).


@dataclass(frozen=True, slots=True)
class ReplayArtifact:
    """Encoded replay plus measured storage sizes."""

    data: bytes
    raw_size_bytes: int
    compressed_size_bytes: int


class ReplayWriter:
    """Accumulate lean presentation frames and encode them at episode end."""

    def __init__(
        self,
        world: Any,
        *,
        config: Mapping[str, object],
        targets: Sequence[Target],
        rulesets: Sequence[CompiledRuleset],
        measurements: RollingMeasurements,
        histogram_interval: int = 10,
        frame_sink: FrameSink | None = None,
    ) -> None:
        if histogram_interval <= 0:
            raise ValueError("replay_histogram_interval must be positive")
        self.config = _without_tokens(config)
        self.targets = tuple(targets)
        self.rulesets = tuple(rulesets)
        self.measurements = measurements
        self.histogram_interval = histogram_interval
        self.frame_sink = frame_sink
        self.initial_grid = _initial_grid(world)
        self._last_cells = _cell_state(world)
        self.roster = [_agent_static(agent) for agent in _sorted_agents(world)]
        self.initial_agents = [_agent_dynamic(agent) for agent in _sorted_agents(world)]
        self._known_agents = {record[0] for record in self.roster}
        self._last_agents = {record[0]: tuple(record[1:]) for record in self.initial_agents}
        self.frames: list[dict[str, object]] = []

    def capture_frame(self, world: Any) -> dict[str, object]:
        """Capture one completed tick and synchronously publish it if requested."""

        current_cells = _cell_state(world)
        deltas = [
            [index, *current]
            for index, (previous, current) in enumerate(zip(self._last_cells, current_cells))
            if previous != current
        ]
        self._last_cells = current_cells
        live_agents = _sorted_agents(world)
        births = [
            _agent_static(agent) for agent in live_agents if agent.ID not in self._known_agents
        ]
        self._known_agents.update(record[0] for record in births)
        current_agent_records = [_agent_dynamic(agent) for agent in live_agents]
        current_agents = {record[0]: tuple(record[1:]) for record in current_agent_records}
        upserted_agents = [
            record
            for record in current_agent_records
            if self._last_agents.get(record[0]) != tuple(record[1:])
        ]
        removed_agents = sorted(set(self._last_agents) - set(current_agents))
        self._last_agents = current_agents
        frame: dict[str, object] = {
            "type": "frame",
            "timestep": world.timestep,
            "cell_deltas": deltas,
            "agent_deltas": {
                "births": births,
                "upsert": upserted_agents,
                "remove": removed_agents,
            },
            "runtimeStats": dict(world.runtimeStats),
        }
        if world.timestep % self.histogram_interval == 0 or world.timestep == world.maxTimestep:
            frame["running"] = self._running_scores()
            frame["measured"] = self._measured_variables()
        self.frames.append(frame)
        if self.frame_sink is not None:
            self.frame_sink(frame)
        return frame

    def finish(
        self,
        *,
        scores: Sequence[float],
        seat_details: Sequence[Mapping[str, object]],
    ) -> ReplayArtifact:
        """Build the final header and return deterministic zlib bytes."""

        document = {
            "format": REPLAY_FORMAT,
            "version": REPLAY_VERSION,
            "header": {
                "config": self.config,
                "seed": self.config["seed"],
                "targets": [target.as_dict() for target in self.targets],
                "rulesets": [ruleset.normalized for ruleset in self.rulesets],
                "scores": list(scores),
                "seat_details": list(seat_details),
                "initial_grid": self.initial_grid,
                "roster": self.roster,
                "initial_agents": self.initial_agents,
            },
            "frames": self.frames,
        }
        raw = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        compressed = zlib.compress(raw, level=9)
        return ReplayArtifact(compressed, len(raw), len(compressed))

    def _measured_variables(self) -> dict[str, object]:
        """Every measured variable's current global histogram, not just the targeted one.

        The engine already measures all of them each tick regardless of what the
        episode is scored on (see RollingMeasurements.record_tick), so recording
        them costs one histogram build per variable per sample point and lets a
        viewer re-score an episode against any target in the catalog. Without
        this a viewer could only ever show the target the episode happened to be
        assigned, or would have to re-derive measurements itself and risk
        disagreeing with the engine that produced the score.
        """

        measured: dict[str, object] = {}
        for variable in sorted(self.measurements.catalog.bins_by_variable):
            measured[variable] = self.measurements.histogram(
                variable, scope="global"
            ).as_dict()
        return measured

    def _running_scores(self) -> list[dict[str, object]]:
        running: list[dict[str, object]] = []
        for seat, target in enumerate(self.targets):
            histogram = self.measurements.histogram(
                target.variable,
                scope=target.scope,
                seat=seat if target.scope == "seat" else None,
            )
            score = score_histogram(histogram, target.probs)
            running.append(
                {
                    "seat": seat,
                    "variable": target.variable,
                    "histogram": histogram.as_dict(),
                    "score": score.score,
                }
            )
        return running


def decode_replay(data: bytes) -> dict[str, object]:
    """Decompress and validate the replay envelope used by tests and tools."""

    try:
        document = json.loads(zlib.decompress(data))
    except (zlib.error, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid Sugarscape replay: {error}") from error
    if not isinstance(document, dict) or document.get("format") != REPLAY_FORMAT:
        raise ValueError("invalid Sugarscape replay format")
    if document.get("version") != REPLAY_VERSION or not isinstance(document.get("frames"), list):
        raise ValueError("unsupported Sugarscape replay version")
    return document


def _initial_grid(world: Any) -> dict[str, object]:
    return {
        "width": world.environment.width,
        "height": world.environment.height,
        "cells": [
            [cell.sugar, cell.spice, cell.pollution, cell.maxSugar, cell.maxSpice]
            for column in world.environment.grid
            for cell in column
        ],
    }


def _cell_state(world: Any) -> list[tuple[float, float, float]]:
    return [
        (cell.sugar, cell.spice, cell.pollution)
        for column in world.environment.grid
        for cell in column
    ]


def _sorted_agents(world: Any) -> list[Any]:
    return sorted(world.agents, key=lambda item: item.ID)


def _agent_static(agent: Any) -> list[int]:
    """One-time traits: [id, seat, born, sex01, vision, movement, m_sugar, m_spice, max_age]."""

    return [
        agent.ID,
        agent.seat,
        agent.born,
        1 if agent.sex == "male" else 0,
        agent.vision,
        agent.movement,
        agent.sugarMetabolism,
        agent.spiceMetabolism,
        agent.maxAge,
    ]


def _agent_dynamic(agent: Any) -> list[int]:
    """Delta-tracked state: [id, x, y, sugar_bucket, spice_bucket, tribe, diseases]."""

    return [
        agent.ID,
        agent.cell.x,
        agent.cell.y,
        quantize_wealth(agent.sugar),
        quantize_wealth(agent.spice),
        -1 if agent.tribe is None else agent.tribe,
        len(agent.diseases),
    ]


def quantize_wealth(wealth: float) -> int:
    """Round replay-only wealth to its nearest presentation bucket."""

    return int(round(wealth / WEALTH_QUANTUM)) * WEALTH_QUANTUM


def _without_tokens(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _without_tokens(item) for key, item in value.items() if key != "tokens"}
    if isinstance(value, list):
        return [_without_tokens(item) for item in value]
    if isinstance(value, tuple):
        return [_without_tokens(item) for item in value]
    return value
