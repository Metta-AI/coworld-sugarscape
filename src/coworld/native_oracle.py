"""Typed parity snapshot for the pinned Python and native simulators."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping

from .simulation import CoworldSugarscape


SCHEMA_VERSION = 3
SOURCE_PIN = "585282e9ce7b22a33b89abb0d777917bd5887d1a"


def _closed(raw: Mapping[str, object], expected: set[str], location: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"{location} fields must be {', '.join(sorted(expected))}")


def _int(value: object, location: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{location} must be an integer >= {minimum}")
    return value


def _number(value: object, location: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{location} must be a finite non-negative number")
    return value


@dataclass(frozen=True)
class NativeSnapshot:
    timestep: int
    width: int
    height: int
    sugar_regrow_rate: int | float
    spice_regrow_rate: int | float
    max_cell_distance: int
    rng_words: tuple[int, ...]
    rng_index: int
    live_order: tuple[int, ...]
    cells: tuple[
        tuple[int | float, int | float, int | float, int | float, int | None], ...
    ]
    agents: tuple[tuple[int | float, ...], ...]
    ordered_candidates: tuple[tuple[tuple[int, int | float], ...], ...]
    deaths: tuple[tuple[int, int, int, str], ...]

    @classmethod
    def from_json(cls, raw: object) -> NativeSnapshot:
        if not isinstance(raw, Mapping):
            raise ValueError("snapshot must be an object")
        keys = {
            "schemaVersion",
            "sourcePin",
            "timestep",
            "width",
            "height",
            "sugarRegrowRate",
            "spiceRegrowRate",
            "maxCellDistance",
            "rng",
            "liveOrder",
            "cells",
            "agents",
            "orderedCandidates",
            "deaths",
        }
        _closed(raw, keys, "snapshot")
        if raw["schemaVersion"] != SCHEMA_VERSION or raw["sourcePin"] != SOURCE_PIN:
            raise ValueError("snapshot schemaVersion or sourcePin is unsupported")
        width = _int(raw["width"], "width", 1)
        height = _int(raw["height"], "height", 1)
        max_cell_distance = _int(raw["maxCellDistance"], "maxCellDistance")
        rng = raw["rng"]
        if not isinstance(rng, Mapping):
            raise ValueError("rng must be an object")
        _closed(rng, {"version", "words", "index", "gaussNext"}, "rng")
        words = rng["words"]
        if (
            rng["version"] != 3
            or rng["gaussNext"] is not None
            or not isinstance(words, list)
            or len(words) != 624
        ):
            raise ValueError("rng must be an unbuffered CPython MT19937 version 3 state")
        rng_words = tuple(_int(word, "rng.words") for word in words)
        if any(word > 0xFFFFFFFF for word in rng_words):
            raise ValueError("rng.words values must fit uint32")
        rng_index = _int(rng["index"], "rng.index")
        if rng_index > 624:
            raise ValueError("rng.index must be <= 624")

        raw_cells = raw["cells"]
        raw_agents = raw["agents"]
        raw_order = raw["liveOrder"]
        raw_candidates = raw["orderedCandidates"]
        raw_deaths = raw["deaths"]
        count = width * height
        if not isinstance(raw_cells, list) or len(raw_cells) != count:
            raise ValueError("cells must contain width * height entries")
        if not isinstance(raw_agents, list) or not isinstance(raw_order, list):
            raise ValueError("agents and liveOrder must be arrays")
        if not isinstance(raw_candidates, list) or len(raw_candidates) != count:
            raise ValueError("orderedCandidates must contain width * height arrays")
        if not isinstance(raw_deaths, list):
            raise ValueError("deaths must be an array")

        cells = []
        for index, cell in enumerate(raw_cells):
            if not isinstance(cell, Mapping):
                raise ValueError(f"cells[{index}] must be an object")
            _closed(
                cell,
                {"sugar", "maxSugar", "spice", "maxSpice", "occupantId"},
                f"cells[{index}]",
            )
            occupant = cell["occupantId"]
            sugar = _number(cell["sugar"], "cell.sugar")
            max_sugar = _number(cell["maxSugar"], "cell.maxSugar")
            spice = _number(cell["spice"], "cell.spice")
            max_spice = _number(cell["maxSpice"], "cell.maxSpice")
            if sugar > max_sugar:
                raise ValueError("cell.sugar must not exceed cell.maxSugar")
            if spice > max_spice:
                raise ValueError("cell.spice must not exceed cell.maxSpice")
            cells.append(
                (
                    sugar,
                    max_sugar,
                    spice,
                    max_spice,
                    None if occupant is None else _int(occupant, "cell.occupantId"),
                )
            )

        agent_keys = {
            "id",
            "seat",
            "x",
            "y",
            "sugar",
            "spice",
            "age",
            "sugarMetabolism",
            "spiceMetabolism",
            "vision",
            "movement",
            "maxAge",
            "lookaheadFactor",
        }
        agents = []
        for index, agent in enumerate(raw_agents):
            if not isinstance(agent, Mapping):
                raise ValueError(f"agents[{index}] must be an object")
            _closed(agent, agent_keys, f"agents[{index}]")
            max_age = agent["maxAge"]
            if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < -1:
                raise ValueError("agent.maxAge must be -1 or a non-negative integer")
            values = (
                _int(agent["id"], "agent.id"),
                _int(agent["seat"], "agent.seat"),
                _int(agent["x"], "agent.x"),
                _int(agent["y"], "agent.y"),
                _number(agent["sugar"], "agent.sugar"),
                _number(agent["spice"], "agent.spice"),
                _int(agent["age"], "agent.age"),
                _number(agent["sugarMetabolism"], "agent.sugarMetabolism"),
                _number(agent["spiceMetabolism"], "agent.spiceMetabolism"),
                _int(agent["vision"], "agent.vision"),
                _int(agent["movement"], "agent.movement"),
                max_age,
                _number(agent["lookaheadFactor"], "agent.lookaheadFactor"),
            )
            if values[2] >= width or values[3] >= height:
                raise ValueError("agent position is outside the world")
            agents.append(values)
        ids = [int(agent[0]) for agent in agents]
        live_order = tuple(_int(value, "liveOrder") for value in raw_order)
        if ids != sorted(set(ids)) or sorted(live_order) != ids:
            raise ValueError("agents must be ID-sorted and liveOrder must be its permutation")
        occupants = [cell[4] for cell in cells if cell[4] is not None]
        if sorted(occupants) != ids:
            raise ValueError("cell occupancy must match live agents")
        for agent in agents:
            cell_index = int(agent[2]) * height + int(agent[3])
            if cells[cell_index][4] != int(agent[0]):
                raise ValueError("cell occupancy disagrees with agent position")

        candidates = []
        for origin, entries in enumerate(raw_candidates):
            if not isinstance(entries, list):
                raise ValueError(f"orderedCandidates[{origin}] must be an array")
            parsed = []
            for entry in entries:
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError("candidate entries must be [cellIndex, distance]")
                target = _int(entry[0], "candidate index")
                if target >= count:
                    raise ValueError("candidate index is outside the world")
                distance = _number(entry[1], "candidate distance")
                if distance == 0 or distance > max_cell_distance:
                    raise ValueError("candidate distance is outside maxCellDistance")
                parsed.append((target, distance))
            targets = [entry[0] for entry in parsed]
            if len(set(targets)) != len(targets) or origin in targets:
                raise ValueError("ordered candidates must be unique and exclude their origin")
            candidates.append(tuple(parsed))
        deaths = []
        for index, death in enumerate(raw_deaths):
            if not isinstance(death, Mapping):
                raise ValueError(f"deaths[{index}] must be an object")
            _closed(death, {"id", "seat", "age", "cause"}, f"deaths[{index}]")
            cause = death["cause"]
            if cause not in {"starvation", "aging"}:
                raise ValueError("death cause must be starvation or aging")
            deaths.append(
                (
                    _int(death["id"], "death.id"),
                    _int(death["seat"], "death.seat"),
                    _int(death["age"], "death.age"),
                    str(cause),
                )
            )
        death_ids = [death[0] for death in deaths]
        if len(set(death_ids)) != len(death_ids) or set(death_ids) & set(ids):
            raise ValueError("death ids must be unique and absent from living agents")
        return cls(
            _int(raw["timestep"], "timestep"),
            width,
            height,
            _number(raw["sugarRegrowRate"], "sugarRegrowRate"),
            _number(raw["spiceRegrowRate"], "spiceRegrowRate"),
            max_cell_distance,
            rng_words,
            rng_index,
            live_order,
            tuple(cells),
            tuple(agents),
            tuple(candidates),
            tuple(deaths),
        )

    def as_json(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sourcePin": SOURCE_PIN,
            "timestep": self.timestep,
            "width": self.width,
            "height": self.height,
            "sugarRegrowRate": self.sugar_regrow_rate,
            "spiceRegrowRate": self.spice_regrow_rate,
            "maxCellDistance": self.max_cell_distance,
            "rng": {
                "version": 3,
                "words": list(self.rng_words),
                "index": self.rng_index,
                "gaussNext": None,
            },
            "liveOrder": list(self.live_order),
            "cells": [
                {
                    "sugar": sugar,
                    "maxSugar": max_sugar,
                    "spice": spice,
                    "maxSpice": max_spice,
                    "occupantId": occupant,
                }
                for sugar, max_sugar, spice, max_spice, occupant in self.cells
            ],
            "agents": [
                dict(
                    zip(
                        (
                            "id", "seat", "x", "y", "sugar", "spice", "age",
                            "sugarMetabolism", "spiceMetabolism", "vision",
                            "movement", "maxAge", "lookaheadFactor",
                        ),
                        agent,
                        strict=True,
                    )
                )
                for agent in self.agents
            ],
            "orderedCandidates": [
                [list(entry) for entry in entries]
                for entries in self.ordered_candidates
            ],
            "deaths": [
                {"id": agent_id, "seat": seat, "age": age, "cause": cause}
                for agent_id, seat, age, cause in self.deaths
            ],
        }


def validate_supported_world(world: CoworldSugarscape) -> None:
    config = world.configuration
    requirements = (
        (
            config["environmentWraparound"] is True,
            "environmentWraparound must be true",
        ),
        (config["agentMovementMode"] == "cardinal", "agentMovementMode must be cardinal"),
        (config["agentVisionMode"] == "cardinal", "agentVisionMode must be cardinal"),
        (config["environmentSeasonInterval"] == 0, "seasons are unsupported"),
        (config["environmentPollutionTimeframe"] == [0, 0], "pollution is unsupported"),
        (
            config["environmentPollutionDiffusionDelay"] == 0,
            "pollution diffusion is unsupported",
        ),
        (config["startingDiseases"] == 0, "disease is unsupported"),
        (config["agentReplacements"] == 0, "replacement is unsupported"),
        (config["agentTagging"] is False, "tagging is unsupported"),
        (config["agentTradeFactor"] == [0, 0], "trade is unsupported"),
        (config["agentLendingFactor"] == [0, 0], "lending is unsupported"),
        (config["agentFertilityFactor"] == [0, 0], "reproduction is unsupported"),
        (config["agentAggressionFactor"] == [0, 0], "combat is unsupported"),
        (
            config["agentUniversalSugar"] == [0, 0]
            and config["agentUniversalSpice"] == [0, 0],
            "universal income is unsupported",
        ),
        (config["agentDecisionModelFactor"] == [0, 0], "ethical decisions are unsupported"),
    )
    for accepted, message in requirements:
        if not accepted:
            raise ValueError(message)
    welfare_ruleset = {
        "version": 1,
        "movement": [{"score": ["get", "cell.welfare"]}],
    }
    if any(
        not ruleset.is_null and ruleset.normalized != welfare_ruleset
        for ruleset in world.seat_manager.rulesets
    ):
        raise ValueError("only null or exact cell.welfare SugarLang rules are supported")
    for index, agent in enumerate(world.agents):
        if not agent.alive or agent.cell is None:
            raise ValueError(f"agents[{index}] must be alive and placed")
        if agent.diseases:
            raise ValueError(f"agents[{index}] disease state is unsupported")
        if agent.movementModifier != 0 or agent.visionModifier != 0:
            raise ValueError(f"agents[{index}] movement and vision modifiers are unsupported")
    for column in world.environment.grid:
        for cell in column:
            if cell.pollution != 0:
                raise ValueError("cell pollution state is unsupported")


def snapshot_world(world: CoworldSugarscape) -> NativeSnapshot:
    validate_supported_world(world)
    environment = world.environment
    version, state, gauss_next = random.getstate()
    if version != 3 or gauss_next is not None:
        raise ValueError("native simulation requires an unbuffered CPython MT19937 state")
    cells = tuple(
        (
            cell.sugar,
            cell.maxSugar,
            cell.spice,
            cell.maxSpice,
            cell.agent.ID if cell.agent is not None else None,
        )
        for column in environment.grid
        for cell in column
    )
    agents = tuple(
        (
            agent.ID,
            agent.seat,
            agent.cell.x,
            agent.cell.y,
            agent.sugar,
            agent.spice,
            agent.age,
            agent.sugarMetabolism,
            agent.spiceMetabolism,
            agent.findVision(),
            agent.findMovement(),
            agent.maxAge,
            agent.lookaheadFactor,
        )
        for agent in sorted(world.agents, key=lambda value: value.ID)
    )
    candidates = tuple(
        tuple(
            (candidate.x * environment.height + candidate.y, distance)
            for bucket in range(1, environment.maxCellDistance + 1)
            for candidate, distance in cell.ranges[bucket].items()
        )
        for column in environment.grid
        for cell in column
    )
    return NativeSnapshot(
        world.timestep,
        environment.width,
        environment.height,
        environment.sugarRegrowRate,
        environment.spiceRegrowRate,
        environment.maxCellDistance,
        tuple(state[:624]),
        state[624],
        tuple(agent.ID for agent in world.agents),
        cells,
        agents,
        candidates,
        tuple(getattr(world, "native_deaths", ())),
    )


def step_python(snapshot: NativeSnapshot, ticks: int) -> NativeSnapshot:
    """Run the reduced v2 contract in Python from the same wire snapshot."""

    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
        raise ValueError("ticks must be a non-negative integer")
    rng = random.Random()
    rng.setstate((3, snapshot.rng_words + (snapshot.rng_index,), None))
    cells = [list(cell) for cell in snapshot.cells]
    agents = {int(agent[0]): list(agent) for agent in snapshot.agents}
    live_order = list(snapshot.live_order)
    timestep = snapshot.timestep
    deaths = list(snapshot.deaths)

    for _ in range(ticks):
        if not live_order:
            break
        deaths = []
        timestep += 1
        for cell in cells:
            cell[0] = min(cell[1], cell[0] + snapshot.sugar_regrow_rate)
            cell[2] = min(cell[3], cell[2] + snapshot.spice_regrow_rate)
        rng.shuffle(live_order)
        for agent_id in live_order:
            agent = agents[agent_id]
            origin = int(agent[2]) * snapshot.height + int(agent[3])
            cell_range = min(int(agent[9]), int(agent[10]), snapshot.max_cell_distance)
            candidates = [
                (target, distance)
                for target, distance in snapshot.ordered_candidates[origin]
                if distance <= cell_range
            ]
            rng.shuffle(candidates)
            destination = origin
            best_welfare = float("-inf")
            best_distance = float("inf")
            for target, distance in candidates:
                if cells[target][4] is not None:
                    continue
                total_metabolism = agent[7] + agent[8]
                sugar_proportion = agent[7] / total_metabolism if total_metabolism else 0
                spice_proportion = agent[8] / total_metabolism if total_metabolism else 0
                adjusted_sugar = max(
                    agent[4] + cells[target][0] - agent[7] * agent[12], 0
                )
                adjusted_spice = max(
                    agent[5] + cells[target][2] - agent[8] * agent[12], 0
                )
                welfare = (adjusted_sugar**sugar_proportion) * (
                    adjusted_spice**spice_proportion
                )
                if welfare > best_welfare or (
                    welfare == best_welfare and distance < best_distance
                ):
                    destination = target
                    best_welfare = welfare
                    best_distance = distance
            if destination != origin:
                cells[origin][4] = None
                cells[destination][4] = agent_id
                agent[2] = destination // snapshot.height
                agent[3] = destination % snapshot.height
            agent[4] += cells[destination][0]
            agent[5] += cells[destination][2]
            cells[destination][0] = 0
            cells[destination][2] = 0
            agent[4] -= agent[7]
            agent[5] -= agent[8]
            sugar_starved = agent[4] < 0 or (agent[4] <= 0 and agent[7] > 0)
            spice_starved = agent[5] < 0 or (agent[5] <= 0 and agent[8] > 0)
            if sugar_starved or spice_starved:
                cells[destination][4] = None
                deaths.append((agent_id, int(agent[1]), int(agent[6]), "starvation"))
                continue
            agent[6] += 1
            if agent[11] != -1 and agent[6] >= agent[11]:
                cells[destination][4] = None
                deaths.append((agent_id, int(agent[1]), int(agent[6]), "aging"))
        for agent_id, _seat, _age, _cause in deaths:
            agents.pop(agent_id)
        dead_ids = {death[0] for death in deaths}
        live_order = [agent_id for agent_id in live_order if agent_id not in dead_ids]

    _version, state, gauss_next = rng.getstate()
    if gauss_next is not None:
        raise AssertionError("shuffle cannot populate the Gaussian cache")
    return NativeSnapshot(
        timestep,
        snapshot.width,
        snapshot.height,
        snapshot.sugar_regrow_rate,
        snapshot.spice_regrow_rate,
        snapshot.max_cell_distance,
        tuple(state[:624]),
        state[624],
        tuple(live_order),
        tuple(tuple(cell) for cell in cells),
        tuple(tuple(agents[agent_id]) for agent_id in sorted(agents)),
        snapshot.ordered_candidates,
        tuple(deaths),
    )
