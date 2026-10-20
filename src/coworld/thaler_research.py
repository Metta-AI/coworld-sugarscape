"""Execute the unchanged Haskell kernels through the qualified population observers."""

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter


def run(config, parameters, source):
    from .research import finish_episode

    started = perf_counter()
    runtime = Path(os.environ["COWORLD_THALER"])
    qualification = json.loads((runtime / "qualification.json").read_bytes())
    if (
        qualification["compiler"] != "8.4.3"
        or qualification["source"]["files_sha256"] != source["files_sha256"]
    ):
        raise ValueError("Haskell compiler/source qualification mismatch")
    for name, digest in qualification["files_sha256"].items():
        if hashlib.sha256((runtime / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Haskell native runtime mismatch: " + name)
    implementation = parameters["implementation"]
    if implementation == "seq" and parameters["capabilities"] != 1:
        raise ValueError("sequential native executable supports one capability")
    directory = Path(tempfile.mkdtemp(prefix="sugarscape-thaler-"))
    command = [
        str(runtime / "lib/ld-linux-x86-64.so.2"),
        "--library-path",
        str(runtime / "lib"),
        str(runtime / "bin" / ("sugarscape-" + implementation)),
        str(parameters["population"]),
        "True" if parameters["rebirthing"] else "False",
    ]
    if implementation != "seq":
        command += ["+RTS", "-N" + str(parameters["capabilities"]), "-RTS"]
    log_path = directory / "native.log"
    try:
        with (
            (directory / "population.csv").open("x") as output,
            log_path.open("x") as log,
        ):
            subprocess.run(
                command,
                cwd=directory,
                stdout=output,
                stderr=log,
                check=True,
                timeout=570,
            )
    finally:
        sys.stderr.write(log_path.read_text())
    with (directory / "population.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1000 or [float(row["T"]) for row in rows] != list(range(1000)):
        raise ValueError("incomplete native Haskell population history")
    frames = []
    for index, row in enumerate(rows):
        population = int(row["PopSize"])
        if population < 0:
            raise ValueError("invalid native Haskell population count")
        frames.append(
            {
                "timestep": index + 1,
                "width": 0,
                "height": 0,
                "sugar": [],
                "spice": [],
                "agents": [],
                "measurements": {
                    "population": population,
                    "resource_gini": None,
                    "native_time": float(row["T"]),
                },
                "native_state_sha256": hashlib.sha256(
                    json.dumps(row, sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    provenance = {
        **source,
        "qualification": qualification,
        "native_seed": 42,
        "executed_binary_sha256": hashlib.sha256(
            Path(command[3]).read_bytes()
        ).hexdigest(),
        "seed_mapping": "The author kernels use fixed seed42. The episode seed does not replace it. Concurrent scheduling remains nondeterministic.",
        "native_output_sha256": hashlib.sha256(
            (directory / "population.csv").read_bytes()
        ).hexdigest(),
        "recorder_scope": "Original initSim forced to completion, then returned population observations exported. Frame indices1–1000 correspond to native times0–999. Population is the returned observable-agent count. No spatial state, hidden RNG/state or historical hardware timing is reconstructed.",
    }
    return finish_episode(config, parameters, frames, provenance, started, 1000)
