"""Pinned study models, one-shot parameter protocols and scientific episode artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import csv
import argparse
import os
import subprocess
import tempfile
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import secrets
import sys
from time import perf_counter
from typing import Literal
import zlib

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .ruleset import ValidationIssue, ValidationResult

SOURCE_ROOT = Path(__file__).with_name("research_sources")
PROTOCOL = "sugarscape-research/1"
REPLAY_FORMAT = "sugarscape.research-replay/1"


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class McCullochParameters(Parameters):
    max_metabolism: int = Field(ge=1, le=4)
    max_vision: int = Field(ge=1, le=16)


class CarrellaParameters(Parameters):
    population: int = Field(ge=10, le=200)
    mutation: float = Field(ge=0, le=1)
    maximum_sugar: int = Field(ge=6, le=100)
    maximum_spice: int = Field(ge=5, le=100)
    reproduction: float = Field(ge=0, le=100)


class DoganParameters(Parameters):
    speed: Literal["slow", "balanced", "fast"]
    policy: Literal[
        "baseline",
        "labour/ubi",
        "labour/means_tested",
        "wealth/ubi",
        "wealth/means_tested",
        "disp_levy/means_tested",
        "uhi_scenario",
    ]


class BrearcliffeParameters(Parameters):
    group_a: Literal["Rule M", "EC", "Q-Learning", "SARSA"]
    group_b: Literal["Rule M", "EC", "Q-Learning", "SARSA"]
    interpretation: Literal["released-code", "paper-table"]


class OremlandParameters(Parameters):
    rates: list[Literal[0, 0.25, 0.5, 0.75]] = Field(min_length=200, max_length=200)
    phase: Literal[0, 4]
    clipped: bool


class ReturnParameters(Parameters):
    period: Literal[5, 6]


class QueraParameters(Parameters):
    vision_probability: float = Field(ge=0, le=1)
    metabolism_alpha: float = Field(gt=0, le=20)
    metabolism_beta: float = Field(gt=0, le=20)
    wealth_alpha: float = Field(gt=0, le=20)
    wealth_beta: float = Field(gt=0, le=20)
    regeneration: float = Field(ge=0, le=10)


class ResearchSpec(Parameters):
    study: Literal[
        "mcculloch_2022",
        "carrella_2021",
        "izquierdo_2009",
        "dogan_2026",
        "brearcliffe_2020",
        "oremland_2014",
        "quera_2025",
    ]
    mode: Literal["reference", "population-calibration"] = "reference"
    parameters: dict[str, object]
    target_population: int = Field(default=0, ge=0, le=2500)


class PlayerName(Parameters):
    name: str = Field(min_length=1)


class ResearchConfig(Parameters):
    research: ResearchSpec
    tokens: list[str] = Field(default_factory=list, max_length=1)
    players: list[PlayerName] = Field(min_length=1, max_length=1)
    seats: Literal[1] = 1
    seed: int = Field(default=-1, ge=-1)
    timesteps: int = Field(ge=1, le=20000)
    player_connect_timeout_seconds: float = Field(default=180, gt=0, le=600)
    spectator_grace_seconds: float = Field(default=30, ge=0, le=180)


PARAMETER_MODELS = {
    "mcculloch_2022": McCullochParameters,
    "carrella_2021": CarrellaParameters,
    "izquierdo_2009": ReturnParameters,
    "dogan_2026": DoganParameters,
    "brearcliffe_2020": BrearcliffeParameters,
    "oremland_2014": OremlandParameters,
    "quera_2025": QueraParameters,
}
PAPER_HORIZONS = {
    "mcculloch_2022": 100,
    "carrella_2021": 500,
    "dogan_2026": 300,
    "quera_2025": 49,
}


def resolve_config(
    raw: Mapping[str, object], *, seed_source: Callable[[], int] | None = None
) -> dict[str, object]:
    config = ResearchConfig.model_validate(dict(raw))
    parameters = PARAMETER_MODELS[config.research.study].model_validate(
        config.research.parameters
    )
    if config.research.study == "izquierdo_2009":
        if config.research.mode != "reference" or config.timesteps != parameters.period:
            raise ValueError(
                "Izquierdo is a fixed reference witness, with timesteps equal to its return period"
            )
    if (
        config.research.mode != "reference"
        and config.research.study != "mcculloch_2022"
    ):
        raise ValueError(
            "parameter calibration is implemented only for the McCulloch challenge"
        )
    if (
        config.research.study in PAPER_HORIZONS
        and config.timesteps > PAPER_HORIZONS[config.research.study]
    ):
        raise ValueError(
            "research horizon exceeds the supported original study horizon"
        )
    config.research.parameters = parameters.model_dump()
    if config.seed == -1:
        config.seed = (seed_source or (lambda: secrets.randbits(63)))()
    if config.seed < 0:
        raise ValueError("resolved research seed must be non-negative")
    return config.model_dump()


def observation(config: Mapping[str, object], slot: int) -> dict[str, object]:
    spec = ResearchSpec.model_validate(config["research"])
    schema = (
        PARAMETER_MODELS[spec.study].model_json_schema()
        if spec.mode != "reference"
        else {"type": "object", "additionalProperties": False, "maxProperties": 0}
    )
    return {
        "type": "observation",
        "protocol": PROTOCOL,
        "seat": slot,
        "study": spec.study,
        "mode": spec.mode,
        "timesteps": config["timesteps"],
        "reference_parameters": spec.parameters,
        "parameter_schema": schema,
        "objective": {"kind": spec.mode, "target_population": spec.target_population},
        "qualification": "Fixed native study rules. Calibration scoring is a Coworld adaptation; a reference episode has noncompetitive score zero.",
    }


def validate_action(config: Mapping[str, object], action: object) -> ValidationResult:
    schema = observation(config, 0)["parameter_schema"]
    if isinstance(action, dict) and any(
        isinstance(value, float) and not math.isfinite(value)
        for value in action.values()
    ):
        return ValidationResult(
            None,
            (ValidationIssue("$.parameters", "parameter values must be finite"),),
            0,
            0,
        )
    errors = tuple(
        ValidationIssue(
            "$.parameters" + "".join(f"[{json.dumps(part)}]" for part in error.path),
            error.message,
        )
        for error in Draft202012Validator(schema).iter_errors(action)
    )
    if errors:
        return ValidationResult(None, errors, 0, 0)
    spec = ResearchSpec.model_validate(config["research"])
    normalized = (
        {}
        if spec.mode == "reference"
        else PARAMETER_MODELS[spec.study].model_validate(action).model_dump()
    )
    return ValidationResult(normalized, (), 0, len(json.dumps(normalized)))


def source_entry(study: str):
    manifest = json.loads((SOURCE_ROOT / "manifest.json").read_bytes())
    entry = next(row for row in manifest if row["study"] == study)
    for name, digest in entry["files_sha256"].items():
        if (
            hashlib.sha256((SOURCE_ROOT / study / name).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError(f"research source hash mismatch: {study}/{name}")
    return entry


def source_module(study: str):
    entry = source_entry(study)
    filename = entry["entrypoint"]
    name = "coworld.research_sources." + study
    module_spec = importlib.util.spec_from_file_location(
        name,
        SOURCE_ROOT / study / filename,
        submodule_search_locations=[str((SOURCE_ROOT / study / filename).parent)]
        if study == "dogan_2026"
        else None,
    )
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module, entry


@dataclass(frozen=True)
class Snapshot:
    timestep: int
    width: int
    height: int
    sugar: list[float]
    spice: list[float]
    agents: list[list[float | int]]
    measurements: dict[str, float | int | str]
    native_state_sha256: str

    def as_dict(self) -> dict[str, object]:
        return self.__dict__


def snapshot(study: str, model, tick: int) -> Snapshot:
    if study == "mcculloch_2022":
        agents = [
            [key[0] * 50 + key[1], a.x, a.y, a.sugar, 0]
            for key, a in model.agents.items()
        ]
        sugar, spice = list(model.sugar), [0] * 2500
        native = {
            "agents": [[list(key), a.model_dump()] for key, a in model.agents.items()],
            "sugar": sugar,
            "occupancy": model.occupancy,
            "random": model.random.getstate(),
        }
        extra = {
            "physical_occupants": sum(model.occupancy),
            "scheduled_agents": len(agents),
        }
    elif study == "carrella_2021":
        agents = [
            [a.identifier, a.x, a.y, a.sugar, a.spice] for a in model.agents.values()
        ]
        sugar, spice = list(model.sugar.values()), list(model.spice.values())
        native = {
            "agents": [a.model_dump() for a in model.agents.values()],
            "sugar": sugar,
            "spice": spice,
            "random": model.random.getstate(),
            "tick": model.tick,
            "prices": model.prices,
            "mean_price": model.mean_price,
        }
        extra = {
            "native_tick": model.tick,
            "trade_count": len(model.prices),
            "mean_price": model.mean_price,
            "utility_gini": model.observation()[2],
        }
    elif study == "dogan_2026":
        from_module = sys.modules[model.__class__.__module__]
        agents = [
            [a.unique_id, *a.cell.coordinate, a.sugar, a.spice]
            for a in model.agents
            if not isinstance(a, from_module.OwnerHumanAgent)
        ]
        sugar = model.grid.sugar.data.flatten().tolist()
        spice = model.grid.spice.data.flatten().tolist()
        native = {
            "agents": [
                [a.unique_id, a.sugar, a.spice, a.age, a.__class__.__name__]
                for a in model.agents
            ],
            "sugar": sugar,
            "spice": spice,
            "random": model.random.getstate(),
            "numpy_random": model.rng.bit_generator.state,
        }
        deaths = model.datacollector.model_vars["StarvationDeaths"]
        extra = {
            "registered_population": len(model.agents),
            "owner_population": len(model.agents) - len(agents),
            "starvation_deaths_cumulative": sum(deaths),
            "native_gini": from_module.compute_gini(model),
        }
    else:
        agents = [
            [i, a.position % 50, a.position // 50, a.wealth, 0]
            for i, a in enumerate(model.agents)
        ]
        # The witness model uses row-major storage; the viewer uses x-major cells.
        sugar = [model.sugar[y * 50 + x] for x in range(50) for y in range(50)]
        spice = [0] * 2500
        native = model.observation("return", tick)
        extra = {
            "births": model.births,
            "harvest": model.harvest,
            "formal_state_sha256": model.state_hash(),
        }
    wealths = sorted(float(a[3]) + float(a[4]) for a in agents)
    population = len(agents)
    if study == "dogan_2026":
        wealths = sorted(a.sugar + a.spice for a in model.agents)
        population = len(model.agents)
        extra["grid_population"] = len(agents)
    total = sum(wealths)
    gini = (
        (
            sum(
                (2 * i - len(wealths) - 1) * wealth
                for i, wealth in enumerate(wealths, 1)
            )
            / (len(wealths) * total)
        )
        if total > 0
        else 0.0
    )
    digest = hashlib.sha256(
        json.dumps(
            native, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return Snapshot(
        tick,
        50,
        50,
        sugar,
        spice,
        agents,
        {
            "population": population,
            "total_resources": total,
            "resource_gini": gini,
            **extra,
        },
        digest,
    )


def run_native_episode(
    config: Mapping[str, object],
    submissions: Sequence[object],
    *,
    submitted: Sequence[bool],
    frame_sink=None,
):
    started = perf_counter()
    resolved = ResearchConfig.model_validate(config)
    spec = resolved.research
    if len(submissions) != 1 or len(submitted) != 1:
        raise ValueError("research variants require exactly one controller seat")
    if not submitted[0]:
        raise ValueError("research controller did not submit before its deadline")
    validation = validate_action(config, submissions[0])
    if not validation.valid:
        raise ValueError(str(validation.errors))
    parameters = spec.parameters if spec.mode == "reference" else validation.normalized
    if spec.study == "quera_2025":
        from .quera_research import run

        return run(resolved, parameters, source_entry(spec.study), SOURCE_ROOT)
    if spec.study in {"brearcliffe_2020", "oremland_2014"}:
        from .netlogo_research import run

        return run(resolved, parameters, source_entry(spec.study), SOURCE_ROOT)
    module, provenance = source_module(spec.study)
    if spec.study == "mcculloch_2022":
        model = module.PaperModel(seed=resolved.seed, **parameters)
    elif spec.study == "carrella_2021":
        model = module.Model(module.Parameters(seed=resolved.seed, **parameters))
    elif spec.study == "dogan_2026":
        calibration = module.SugarscapeAITax(
            tax_regime="none", redistribution_mode="none", k=0, m=0, seed=42
        )
        calibration.run_model(200)
        income_threshold = float(
            calibration.datacollector.model_vars["MedianIncome"][199]
        )
        wealth_upper = 2 * float(
            calibration.datacollector.model_vars["MedianWealth"][199]
        )
        transfer = module.SugarscapeAITax(
            tax_regime="wealth",
            redistribution_mode="means_tested",
            k=10,
            m=10,
            income_threshold=income_threshold,
            wealth_threshold_lower=50,
            wealth_threshold_upper=wealth_upper,
            seed=42,
        )
        transfer.run_model(300)
        data = transfer.datacollector.get_agent_vars_dataframe()
        eligible = data[data["TransferReceived"] > 0]["TransferReceived"]
        uhi_rate = 2 * (float(eligible.mean()) if len(eligible) > 0 else 1.0)
        policies = {
            "baseline": ("none", "none"),
            "disp_levy/means_tested": ("displacement_levy", "means_tested"),
            "uhi_scenario": ("uhi_scenario", "none"),
        }
        if parameters["policy"] in policies:
            tax, redistribution = policies[parameters["policy"]]
        else:
            tax, redistribution = parameters["policy"].split("/")
        k, m = {"slow": (20, 10), "balanced": (10, 10), "fast": (5, 20)}[
            parameters["speed"]
        ]
        model = module.SugarscapeAITax(
            tax_regime=tax,
            redistribution_mode=redistribution,
            k=k,
            m=m,
            income_threshold=income_threshold,
            wealth_threshold_lower=50,
            wealth_threshold_upper=wealth_upper,
            uhi_transfer_rate=uhi_rate if tax == "uhi_scenario" else 0,
            seed=resolved.seed,
        )
        provenance = {
            **provenance,
            "calibration": {
                "seed": 42,
                "income_threshold": income_threshold,
                "wealth_threshold_upper": wealth_upper,
                "uhi_transfer_rate": uhi_rate,
            },
        }
    else:
        with (
            SOURCE_ROOT
            / spec.study
            / "results/full-model-return-2026-10-17/capacity.csv"
        ).open() as stream:
            capacity = [int(value) for row in csv.reader(stream) for value in row]
        sites = [
            p
            for p in range(2500)
            if capacity[p] == 0
            and all(
                capacity[
                    (p // 50 * 50 + (p % 50 + dx) % 50)
                    if dx
                    else ((p // 50 + dy) % 50) * 50 + p % 50
                ]
                == 0
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
            )
        ][:250]
        model = module.Model(
            capacity,
            [module.Agent(p, 1, 1, 1, 95) for p in sites],
            capacity,
            resolved.seed,
        )
    frames = []
    for tick in range(resolved.timesteps + 1):
        state = snapshot(spec.study, model, tick)
        frames.append(state.as_dict())
        if frame_sink is not None:
            frame_sink(
                {
                    "type": "frame",
                    "protocol": PROTOCOL,
                    "timestep": tick,
                    "measurements": state.measurements,
                }
            )
        if tick < resolved.timesteps:
            if spec.study == "izquierdo_2009":
                period = parameters["period"]
                model.step(
                    lambda index, occupied: module.Agent(
                        sites[index], 1, 1, period, 99 if period == 5 else 100
                    )
                )
            else:
                model.step()
    if (
        spec.study == "izquierdo_2009"
        and frames[0]["measurements"]["formal_state_sha256"]
        != frames[-1]["measurements"]["formal_state_sha256"]
    ):
        raise ValueError("formal return witness did not return to its initial state")
    paper_horizon = (
        parameters["period"]
        if spec.study == "izquierdo_2009"
        else PAPER_HORIZONS[spec.study]
    )
    return finish_episode(
        resolved, parameters, frames, provenance, started, paper_horizon
    )


def finish_episode(resolved, parameters, frames, provenance, started, paper_horizon):
    spec = resolved.research
    final = frames[-1]["measurements"]
    score = (
        0.0
        if spec.mode == "reference"
        else 1.0 / (1.0 + abs(final["population"] - spec.target_population))
    )
    details = {
        "study": spec.study,
        "mode": spec.mode,
        "parameters": parameters,
        "target_population": spec.target_population,
        "paper_horizon": paper_horizon,
        "executed_horizon": resolved.timesteps,
        "duration_override": paper_horizon != resolved.timesteps,
        "measurements": final,
        "provenance": provenance,
        "seed": resolved.seed,
        "engine": provenance["engine"],
        "python": sys.version,
    }
    replay = {
        "format": REPLAY_FORMAT,
        "details": details,
        "players": [p.model_dump() for p in resolved.players],
        "frames": frames,
    }
    encoded = json.dumps(replay, separators=(",", ":"), allow_nan=False).encode()
    method = (
        "research-reference/1"
        if spec.mode == "reference"
        else "research-population-calibration/1"
    )
    results = {
        "score_method": method,
        "scores": [score],
        "score.match_mean": score,
        "score.match_min": score,
        "score.seat_0": score,
        "details": [details],
        "histograms": {},
        "rulesets_identical": True,
        "result.population_final": final["population"],
        "result.gini_final": final["resource_gini"],
        "result.extinct": final["population"] == 0,
        "result.timesteps_completed": resolved.timesteps,
        "timings": {"research_seconds": perf_counter() - started},
    }
    return results, zlib.compress(encoded, level=9), results["timings"]


def run_episode(config, submissions, *, submitted, frame_sink=None):
    """Bound native execution in the qualified interpreter, keeping server I/O responsive."""
    output = Path(tempfile.mkdtemp(prefix="sugarscape-research-"))
    request = output / "request.json"
    request.write_text(
        json.dumps(
            {"config": config, "submissions": submissions, "submitted": submitted},
            allow_nan=False,
        )
    )
    environment = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    prefix_key = (
        "COWORLD_RESEARCH_PREFIX_DOGAN"
        if config["research"]["study"] == "dogan_2026"
        else "COWORLD_RESEARCH_PREFIX"
    )
    if prefix_key in environment:
        environment["PYTHONHOME"] = environment[prefix_key]
        environment["LD_LIBRARY_PATH"] = environment[prefix_key] + "/lib"
    with (output / "worker.log").open("x") as log:
        result = subprocess.run(
            [
                os.environ[
                    "COWORLD_RESEARCH_PYTHON_DOGAN"
                    if config["research"]["study"] == "dogan_2026"
                    else "COWORLD_RESEARCH_PYTHON"
                ],
                "-m",
                "coworld.research",
                str(request),
                str(output),
            ],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"native research worker failed; retained evidence at {output}: "
            + (output / "worker.log").read_text()
        )
    results = json.loads((output / "results.json").read_bytes())
    replay = (output / "replay.bin").read_bytes()
    if frame_sink is not None:
        document = json.loads(zlib.decompress(replay))
        for frame in document["frames"]:
            frame_sink(
                {
                    "type": "frame",
                    "protocol": PROTOCOL,
                    "timestep": frame["timestep"],
                    "measurements": frame["measurements"],
                }
            )
    return results, replay, results["timings"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bounded native Sugarscape research worker"
    )
    parser.add_argument("request", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    request = json.loads(arguments.request.read_bytes())
    expected_version = (
        (3, 12, 4)
        if request["config"]["research"]["study"] == "dogan_2026"
        else (3, 11, 14)
    )
    if sys.version_info[:3] != expected_version:
        raise RuntimeError(
            f"research adapter requires the qualified interpreter {expected_version}"
        )
    results, replay, _ = run_native_episode(
        request["config"], request["submissions"], submitted=request["submitted"]
    )
    (arguments.output / "replay.bin").write_bytes(replay)
    (arguments.output / "results.json").write_text(json.dumps(results, allow_nan=False))
