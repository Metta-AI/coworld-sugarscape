#!/usr/bin/env python3
"""Render a v3 episode through the v1 broadcast viewer.

The broadcast viewer on `ux-replay-broadcast` is the design we want to keep;
v3 is the engine we want behind it. The two are closer than they look, so this
converts rather than rewrites:

- Both index cells `x * height + y`, so the lattice maps across untransposed.
- v3's per-cell row is `[sugar, spice, pollution, maxSugar, maxSpice]` and v1's
  is `[sugar, spice, pollution]` — a prefix, not a translation.
- v3 vendors the same DTL simulation, so `runtimeStats` already carries the
  exact keys the viewer reads (`giniCoefficient`, `agentStarvationDeaths`,
  `agentAgingDeaths`, `agentCombatDeaths`, `agentDiseaseDeaths`).

The real difference is shape, not meaning: v3 records deltas against an initial
state, v1 records whole frames. So this replays the deltas forward and
materialises each tick.

    python tools/v3_to_v1_replay.py build/local/replay.bin build/local/replay.v1.json

What does NOT survive, and cannot: v3 scores a seat on how closely its measured
distribution matches a target, so there is no wealth race to win. The viewer's
race panel will plot seat wealth because that is what it plots; read it as
"what the ruleset grew", not as a scoreboard.
"""

from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coworld.scoring import Histogram, score_histogram  # noqa: E402
from coworld.replay import WEALTH_QUANTUM  # noqa: E402

V1_REPLAY_FORMAT = "sugarscape.replay.v1"
V1_FRAME_FORMAT = "sugarscape.frame.v1"
CATALOG = Path(__file__).resolve().parents[1] / "targets"


def load_catalog() -> list[dict]:
    """Every shipped target, so a viewer can offer the whole catalog."""

    return sorted(
        (json.loads(path.read_text(encoding="utf-8")) for path in CATALOG.glob("*.json")),
        key=lambda target: (target.get("variable", ""), target.get("id", "")),
    )


def score_against(target: dict, measured: dict | None) -> float | None:
    """Score a measured histogram against a target using the ENGINE's scorer.

    Re-implementing `1 - normalized_W1` here would risk quietly disagreeing with
    the number the episode was actually scored on, which is the one thing this
    view must not do.
    """

    if not measured or not measured.get("probs"):
        return None
    if list(measured.get("bins") or []) != list(target.get("bins") or []):
        return None  # different support: not comparable, and must not pretend
    histogram = Histogram(
        bins=tuple(measured["bins"]),
        probs=tuple(measured["probs"]),
        sample_count=int(measured.get("sample_count") or 0),
    )
    return score_histogram(histogram, tuple(target["probs"])).score


def load_v3(path: Path) -> dict:
    document = json.loads(zlib.decompress(path.read_bytes()))
    if document.get("format") != "sugarscape.replay.v3":
        raise SystemExit(f"not a v3 replay: {document.get('format')!r}")
    return document


def seat_names(header: dict) -> list[dict]:
    players = header["config"].get("players") or []
    seats = max(1, len(header.get("targets") or []))
    names = []
    for index in range(seats):
        name = None
        if index < len(players) and isinstance(players[index], dict):
            name = players[index].get("name")
        names.append({"name": name or f"Seat {index + 1}", "decisionModels": []})
    return names


def convert(document: dict) -> dict:
    header = document["header"]
    grid = header["initial_grid"]
    width, height = grid["width"], grid["height"]

    # v1 wants [sugar, spice, pollution]; v3 appends the two capacities.
    cells = [list(cell[:3]) for cell in grid["cells"]]
    max_sugar = max((cell[3] for cell in grid["cells"]), default=0)
    max_spice = max((cell[4] for cell in grid["cells"]), default=0)

    # roster: id -> [id, seat, born, sex01, vision, movement, mSugar, mSpice, maxAge]
    roster = {row[0]: row for row in header["roster"]}
    # live:   id -> [id, x, y, sugarBucket, spiceBucket, tribe, diseases]
    live = {row[0]: list(row) for row in header["initial_agents"]}

    slots = seat_names(header)
    max_timestep = header["config"].get("timesteps") or len(document["frames"])
    starting_agents = len(header["initial_agents"])

    def materialise(timestep: int, stats: dict, final: bool) -> dict:
        agents = []
        for agent_id in sorted(live):
            dynamic = live[agent_id]
            static = roster.get(agent_id) or [agent_id, 0, 0, 0, 0, 0, 0, 0, -1]
            agents.append({
                "id": agent_id,
                # Same formula both sides; see module docstring.
                "cell": dynamic[1] * height + dynamic[2],
                "slot": static[1],
                "decisionModel": slots[static[1] % len(slots)]["name"],
                "age": max(0, timestep - static[2]),
                "sugar": dynamic[3],
                "spice": dynamic[4],
                "sugarMetabolism": static[6],
                "spiceMetabolism": static[7],
                "vision": static[4],
                "movement": static[5],
                "depressed": False,
                "sick": bool(dynamic[6]),
                # Cultural tag. DTL writes -1 for "no tribe"; the shipped config
                # runs three, and majority_tribe_share is a target variable, so
                # this has to survive the conversion.
                "tribe": dynamic[5],
            })
        return {
            "format": V1_FRAME_FORMAT,
            "timestep": timestep,
            "maxTimestep": max_timestep,
            "environmentMaxSugar": max_sugar,
            "environmentMaxSpice": max_spice,
            "startingAgents": starting_agents,
            # v3 records per-agent wealth in presentation BUCKETS, not raw units
            # (see quantize_wealth). Say so, loudly, in the frame: a viewer that
            # treats a 50-unit bucket as a sugar count will decide that every
            # agent below the first bucket is about to starve, which measured at
            # 24.2% of agent-frames before this was carried across.
            "wealthQuantum": WEALTH_QUANTUM,
            "width": width,
            "height": height,
            "cells": [list(cell) for cell in cells],
            "agents": agents,
            "links": [],
            "slots": slots,
            "stats": stats,
            "final": final,
        }

    def stats_from(runtime: dict, timestep: int) -> dict:
        # DTL's own names carry across unchanged; fill only what the viewer reads
        # and is missing, rather than inventing values it would then print.
        out = dict(runtime)
        out.setdefault("timestep", timestep)
        out.setdefault("population", len(live))
        for key in (
            "giniCoefficient",
            "agentStarvationDeaths",
            "agentAgingDeaths",
            "agentCombatDeaths",
            "agentDiseaseDeaths",
        ):
            out.setdefault(key, 0)
        return out

    # v3's actual question is "did the rules grow the target", so the target, the
    # measured histogram and the running score have to reach the viewer. They are
    # recorded only every `replay_histogram_interval` ticks, so the last known
    # reading is carried forward — a frame between samples shows the most recent
    # measurement rather than an empty panel.
    targets = header.get("targets") or []
    catalog = load_catalog()
    assigned = {target.get("id") for target in targets}
    latest = {}
    measured_now: dict[str, dict] = {}

    def coworld_block() -> dict:
        seats = []
        for seat, target in enumerate(targets):
            reading = latest.get(seat) or {}
            histogram = reading.get("histogram") or {}
            seat_row = {
                "seat": seat,
                "name": slots[seat % len(slots)]["name"],
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
            seats.append(seat_row)
        # The whole catalog, each scored against what this episode actually grew.
        # `assigned` marks the one the episode was really played for, so the view
        # can say so rather than presenting seven equal-looking verdicts.
        choices = []
        for target in catalog:
            measurement = measured_now.get(target.get("variable")) or {}
            choices.append({
                "id": target.get("id"),
                "variable": target.get("variable"),
                "assigned": target.get("id") in assigned,
                "bins": target.get("bins") or [],
                "targetProbs": target.get("probs") or [],
                "measuredProbs": measurement.get("probs") or [],
                "sampleCount": measurement.get("sample_count", 0),
                "score": score_against(target, measurement),
            })
        return {
            "seats": seats,
            "choices": choices,
            "finalScores": list(header.get("scores") or []),
        }

    frames = [materialise(0, stats_from({}, 0), False)]
    frames[0]["coworld"] = coworld_block()
    total = len(document["frames"])
    for position, frame in enumerate(document["frames"]):
        for index, sugar, spice, pollution in frame["cell_deltas"]:
            cells[index] = [sugar, spice, pollution]
        deltas = frame["agent_deltas"]
        for row in deltas["births"]:
            roster[row[0]] = row
        for row in deltas["upsert"]:
            live[row[0]] = list(row)
        for agent_id in deltas["remove"]:
            live.pop(agent_id, None)
        for reading in frame.get("running") or []:
            latest[reading["seat"]] = reading
        for variable, histogram in (frame.get("measured") or {}).items():
            measured_now[variable] = histogram
        timestep = frame["timestep"]
        built = materialise(
            timestep,
            stats_from(frame.get("runtimeStats") or {}, timestep),
            position == total - 1,
        )
        built["coworld"] = coworld_block()
        frames.append(built)

    return {
        "format": V1_REPLAY_FORMAT,
        "config": header["config"],
        "frames": frames,
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    converted = convert(load_v3(source))
    destination.write_text(json.dumps(converted), encoding="utf-8")
    frames = converted["frames"]
    print(
        f"{source} -> {destination}\n"
        f"  {len(frames)} frames, t0..t{frames[-1]['timestep']}, "
        f"{frames[0]['width']}x{frames[0]['height']}, "
        f"{len(frames[0]['slots'])} seat(s), "
        f"maxSugar {frames[0]['environmentMaxSugar']} maxSpice {frames[0]['environmentMaxSpice']}"
    )


if __name__ == "__main__":
    main()
