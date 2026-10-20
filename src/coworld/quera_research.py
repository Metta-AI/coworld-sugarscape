"""Pinned Julia forward worlds, retaining the author's alive/occupancy semantics."""

from pathlib import Path
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from time import perf_counter


def run(config, parameters, source, source_root):
    from .research import finish_episode

    started = perf_counter()
    directory = Path(tempfile.mkdtemp(prefix="sugarscape-quera-"))
    project = source_root / config.research.study
    julia = os.environ["COWORLD_JULIA"]
    version = subprocess.check_output(
        [julia, "--startup-file=no", "--version"], text=True
    ).strip()
    if version != "julia version 1.11.3":
        raise ValueError("Quera requires Julia 1.11.3")
    runner = Path(__file__).with_name("quera_runner.jl")
    command = [
        julia,
        "--startup-file=no",
        "--project=" + str(project),
        str(runner),
        str(project),
        str(directory),
        str(config.seed),
        str(config.timesteps),
        *(
            str(parameters[key])
            for key in [
                "vision_probability",
                "metabolism_alpha",
                "metabolism_beta",
                "wealth_alpha",
                "wealth_beta",
                "regeneration",
            ]
        ),
    ]
    log_path = directory / "native.log"
    try:
        with log_path.open("x") as log:
            subprocess.run(
                command,
                cwd=directory,
                env={
                    **os.environ,
                    "JULIA_DEPOT_PATH": os.environ["COWORLD_JULIA_DEPOT"],
                    "JULIA_NUM_THREADS": "1",
                    "JULIA_NUM_PRECOMPILE_TASKS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "JULIA_PKG_OFFLINE": "true",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=570,
            )
    finally:
        sys.stderr.write(log_path.read_text())
    with (directory / "agents.csv").open() as stream:
        agent_rows = list(csv.DictReader(stream))
    with (directory / "cells.csv").open() as stream:
        cell_rows = list(csv.DictReader(stream))
    count = config.timesteps + 1
    if len(agent_rows) != count * 100 or len(cell_rows) != count * 625:
        raise ValueError("incomplete native Julia history")
    frames = []
    for tick in range(count):
        agents = [
            {key: float(value) for key, value in row.items()}
            for row in agent_rows[tick * 100 : (tick + 1) * 100]
        ]
        cells = [
            {key: float(value) for key, value in row.items()}
            for row in cell_rows[tick * 625 : (tick + 1) * 625]
        ]
        if any(
            row["time"] != tick or not all(math.isfinite(v) for v in row.values())
            for row in [*agents, *cells]
        ):
            raise ValueError("invalid native Julia observation")
        if any(row["alive"] not in (0, 1) for row in agents):
            raise ValueError("forward alive flags are not binary")
        living = [a for a in agents if a["alive"] == 1]
        frames.append(
            {
                "timestep": tick,
                "width": 25,
                "height": 25,
                "sugar": [c["sugar"] for c in cells],
                "spice": [0] * 625,
                "agents": [
                    [int(a["agent"]), a["x"] - 1, a["y"] - 1, a["wealth"], 0]
                    for a in living
                ],
                "measurements": {
                    "population": len(living),
                    "registered_agent_slots": 100,
                    "occupied_cells": sum(c["occupied"] for c in cells),
                    "negative_wealth_alive": sum(a["wealth"] < 0 for a in living),
                    "total_resources": sum(a["wealth"] for a in living),
                    "resource_gini": None,
                },
                "native_observation": {"agents": agents, "cells": cells},
                "native_state_sha256": hashlib.sha256(
                    json.dumps(
                        {"agents": agents, "cells": cells}, sort_keys=True
                    ).encode()
                ).hexdigest(),
            }
        )
    provenance = {
        **source,
        "julia_version": version,
        "runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
        "native_outputs_sha256": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ["agents.csv", "cells.csv"]
        },
        "recorder_scope": "Native six-array forward history; hashes identify recorded arrays, not RNG state. Preserve native survival/occupancy quirks and negative wealth. No training or gradient claim.",
    }
    return finish_episode(config, parameters, frames, provenance, started, 49)
