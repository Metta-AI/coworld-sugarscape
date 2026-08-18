"""Incrementally materialize v3 replay deltas as v1 broadcast frames.

The studio applies every delta to this stateful adapter, but only asks for a
whole frame at its sampling cadence. Complete replay conversion uses the same
path and materializes after every delta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .replay import WEALTH_QUANTUM
from .scoring import (
    LEGACY_SCORE_METHOD,
    SCORE_METHOD,
    Histogram,
    score_histogram,
    wasserstein_1,
)
from .targets import DEFAULT_CATALOG_PATH


V1_REPLAY_FORMAT = "sugarscape.replay.v1"
V1_FRAME_FORMAT = "sugarscape.frame.v1"


def load_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> list[dict]:
    """Load every shipped distribution target in stable viewer order."""

    catalog_path = Path(path)
    return sorted(
        (
            target
            for target in (
                json.loads(target_path.read_text(encoding="utf-8"))
                for target_path in catalog_path.glob("*.json")
            )
            if target.get("kind", "distribution") == "distribution"
        ),
        key=lambda target: (target.get("variable", ""), target.get("id", "")),
    )


def score_against(
    target: dict,
    measured: dict | None,
    score_method: str,
) -> float | None:
    """Score one recorded histogram with the engine's declared method."""

    if not measured or not measured.get("probs"):
        return None
    if list(measured.get("bins") or []) != list(target.get("bins") or []):
        return None
    histogram = Histogram(
        bins=tuple(measured["bins"]),
        probs=tuple(measured["probs"]),
        sample_count=int(measured.get("sample_count") or 0),
    )
    if histogram.empty:
        return 0.0
    target_probs = tuple(target["probs"])
    if score_method == SCORE_METHOD:
        return score_histogram(histogram, target_probs).score
    if score_method == LEGACY_SCORE_METHOD:
        distance = wasserstein_1(histogram.probs, target_probs, histogram.bins)
        support = histogram.bins[-1] - histogram.bins[0]
        return min(1.0, max(0.0, 1.0 - distance / support))
    return None


def _seat_names(header: dict) -> list[dict]:
    config = header["config"]
    players = config.get("players") or []
    targets = header.get("targets") or []
    seats = max(1, len(targets))
    names = []
    for index in range(seats):
        name = None
        if index < len(players) and isinstance(players[index], dict):
            name = players[index].get("name")
        names.append({"name": name or f"Seat {index + 1}", "decisionModels": []})
    return names


class V1FrameMaterializer:
    """Apply every v3 delta while materializing only requested whole frames."""

    def __init__(
        self,
        header: dict,
        *,
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
        max_timestep: int | None = None,
    ) -> None:
        self.score_method = str(header.get("score_method", LEGACY_SCORE_METHOD))
        grid = header["initial_grid"]
        grid_cells = grid["cells"]
        self.width = int(grid["width"])
        self.height = int(grid["height"])
        self.cells = [list(cell[:3]) for cell in grid_cells]
        self.max_sugar = max((cell[3] for cell in grid_cells), default=0)
        self.max_spice = max((cell[4] for cell in grid_cells), default=0)
        self.roster = {row[0]: row for row in header["roster"]}
        self.live = {row[0]: list(row) for row in header["initial_agents"]}
        self.slots = _seat_names(header)
        config = header["config"]
        self.max_timestep = config.get("timesteps") or max_timestep or 0
        self.starting_agents = len(header["initial_agents"])
        self.targets = header.get("targets") or []
        self.catalog = load_catalog(catalog_path)
        self.assigned = {target.get("id") for target in self.targets}
        # Histogram samples are sparse. Both assigned and catalog readings carry
        # forward until a later v3 frame replaces them.
        self.latest: dict[int, dict] = {}
        self.measured_now: dict[str, dict] = {}
        self.final_scores = list(header.get("scores") or [])
        self.timestep = 0
        self.stats = self._stats_from({}, 0)

    def initial_frame(self) -> dict[str, object]:
        """Materialize the bootstrap state before any v3 delta is applied."""

        return self.materialize()

    def apply_frame(self, frame: dict) -> None:
        """Apply one v3 delta without allocating a whole renderer frame."""

        for index, sugar, spice, pollution in frame["cell_deltas"]:
            self.cells[index] = [sugar, spice, pollution]
        deltas = frame["agent_deltas"]
        for row in deltas["births"]:
            self.roster[row[0]] = row
        for row in deltas["upsert"]:
            self.live[row[0]] = list(row)
        for agent_id in deltas["remove"]:
            self.live.pop(agent_id, None)
        for reading in frame.get("running") or []:
            self.latest[reading["seat"]] = reading
        measured = frame.get("measured") or {}
        for variable, histogram in measured.items():
            self.measured_now[str(variable)] = histogram
        self.timestep = int(frame["timestep"])
        runtime = frame.get("runtimeStats") or {}
        self.stats = self._stats_from(runtime, self.timestep)

    def materialize(
        self,
        *,
        final: bool = False,
        final_scores: Sequence[float] | None = None,
    ) -> dict[str, object]:
        """Build the current whole frame, optionally injecting final scores."""

        if final_scores is not None:
            self.final_scores = list(final_scores)
        agents = []
        for agent_id in sorted(self.live):
            dynamic = self.live[agent_id]
            static = self.roster.get(agent_id) or [agent_id, 0, 0, 0, 0, 0, 0, 0, -1]
            agents.append(
                {
                    "id": agent_id,
                    "cell": dynamic[1] * self.height + dynamic[2],
                    "slot": static[1],
                    "decisionModel": self.slots[static[1] % len(self.slots)]["name"],
                    "age": max(0, self.timestep - static[2]),
                    "sugar": dynamic[3],
                    "spice": dynamic[4],
                    "sugarMetabolism": static[6],
                    "spiceMetabolism": static[7],
                    "vision": static[4],
                    "movement": static[5],
                    "depressed": False,
                    "sick": bool(dynamic[6]),
                    "tribe": dynamic[5],
                }
            )
        return {
            "format": V1_FRAME_FORMAT,
            "timestep": self.timestep,
            "maxTimestep": self.max_timestep,
            "environmentMaxSugar": self.max_sugar,
            "environmentMaxSpice": self.max_spice,
            "startingAgents": self.starting_agents,
            # v3 wealth is stored in presentation buckets, not raw resource units.
            "wealthQuantum": WEALTH_QUANTUM,
            "width": self.width,
            "height": self.height,
            "cells": [list(cell) for cell in self.cells],
            "agents": agents,
            "links": [],
            "slots": self.slots,
            "stats": self.stats,
            "final": final,
            "coworld": self.coworld_block(),
        }

    def coworld_block(self) -> dict[str, object]:
        """Build target, running-measurement, and authoritative-score metadata."""

        seats = []
        for seat, target in enumerate(self.targets):
            reading = self.latest.get(seat) or {}
            histogram = reading.get("histogram") or {}
            seat_row = {
                "seat": seat,
                "name": self.slots[seat % len(self.slots)]["name"],
                "targetId": target.get("id"),
                "variable": target.get("variable"),
                "bins": target.get("bins") or [],
                "targetProbs": target.get("probs") or [],
                "measuredProbs": histogram.get("probs") or [],
                "sampleCount": histogram.get("sample_count", 0),
                "measured": bool(histogram.get("probs")),
                "assigned": True,
            }
            if reading.get("score") is not None:
                seat_row["score"] = reading["score"]
            scalar = target.get("kind", "distribution") != "distribution"
            if scalar:
                seat_row["targetKind"] = target["kind"]
            if scalar and reading.get("score_method"):
                seat_row["scoreMethod"] = reading["score_method"]
            if scalar and reading.get("survivor_count") is not None:
                seat_row["survivorCount"] = reading["survivor_count"]
            if scalar and reading.get("mean_wellness") is not None:
                seat_row["meanWellness"] = reading["mean_wellness"]
            if scalar and reading.get("component_means"):
                seat_row["componentMeans"] = reading["component_means"]
            seats.append(seat_row)
        choices = []
        for target in self.catalog:
            measurement = self.measured_now.get(str(target.get("variable"))) or {}
            choices.append(
                {
                    "id": target.get("id"),
                    "variable": target.get("variable"),
                    "assigned": target.get("id") in self.assigned,
                    "bins": target.get("bins") or [],
                    "targetProbs": target.get("probs") or [],
                    "measuredProbs": measurement.get("probs") or [],
                    "sampleCount": measurement.get("sample_count", 0),
                    "score": score_against(target, measurement, self.score_method),
                }
            )
        return {
            "seats": seats,
            "choices": choices,
            "finalScores": list(self.final_scores),
        }

    def _stats_from(self, runtime: dict, timestep: int) -> dict[str, object]:
        stats = dict(runtime)
        stats.setdefault("timestep", timestep)
        stats.setdefault("population", len(self.live))
        for key in (
            "giniCoefficient",
            "agentStarvationDeaths",
            "agentAgingDeaths",
            "agentCombatDeaths",
            "agentDiseaseDeaths",
        ):
            stats.setdefault(key, 0)
        return stats


def convert_document(document: dict) -> dict[str, object]:
    """Convert a complete v3 replay document to the legacy v1 envelope."""

    header = document["header"]
    frames = document["frames"]
    materializer = V1FrameMaterializer(header, max_timestep=len(frames))
    converted = [materializer.initial_frame()]
    total = len(frames)
    for position, frame in enumerate(frames):
        materializer.apply_frame(frame)
        converted.append(materializer.materialize(final=position == total - 1))
    return {
        "format": V1_REPLAY_FORMAT,
        "config": header["config"],
        "frames": converted,
    }
