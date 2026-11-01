"""Run the original qualified Java recorders without reconstructing missing world state."""

from pathlib import Path
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter


def execute_recorder(command, directory):
    log_path = directory / "native.log"
    try:
        with log_path.open("x") as log:
            subprocess.run(
                command,
                cwd=directory,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=570,
                check=True,
            )
    finally:
        sys.stderr.write(log_path.read_text())


def run(config, parameters, source, source_root):
    from .research import finish_episode

    started = perf_counter()
    study = config.research.study
    directory = Path(tempfile.mkdtemp(prefix="sugarscape-netlogo-"))
    runtime = Path(
        os.environ[
            "COWORLD_NETLOGO_6" if study == "brearcliffe_2020" else "COWORLD_NETLOGO_5"
        ]
    )
    qualification = json.loads((runtime / "qualification.json").read_bytes())
    for name, digest in qualification["jars_sha256"].items():
        if hashlib.sha256((runtime / "app" / name).read_bytes()).hexdigest() != digest:
            raise ValueError("NetLogo runtime jar mismatch: " + name)
    driver = "Replay" if study == "brearcliffe_2020" else "RunPolicyBatch"
    if (
        qualification["driver_source_sha256"]
        != source["files_sha256"][driver + ".java"]
    ):
        raise ValueError("NetLogo recorder source differs from the compiled runtime")
    for name, digest in qualification["classes_sha256"].items():
        if (
            hashlib.sha256((runtime / "classes" / name).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("NetLogo recorder class or extension mismatch: " + name)
    classpath = (
        str(runtime / "classes")
        + os.pathsep
        + os.pathsep.join(
            str(runtime / "app" / name) for name in qualification["classpath_jars"]
        )
    )
    java = os.environ["COWORLD_JAVA"]
    version = subprocess.check_output(
        [java, "-version"], stderr=subprocess.STDOUT, text=True
    )
    seed = config.seed % 2147483647
    model = (source_root / study / "model.nlogo").read_text()
    if study == "brearcliffe_2020":
        for expected in [
            "random-seed new-seed",
            "set learning-rate 0.9",
            "set gamma 0.8",
        ]:
            if model.count(expected) != 1:
                raise ValueError(
                    "unexpected author model parameter declaration: " + expected
                )
        alpha, gamma = (
            ("0.9", "0.8")
            if parameters["interpretation"] == "released-code"
            else ("0.8", "0.9")
        )
        model = (
            model.replace("random-seed new-seed", f"random-seed {seed}")
            .replace("set learning-rate 0.9", "set learning-rate " + alpha)
            .replace("set gamma 0.8", "set gamma " + gamma)
        )
        (directory / "model.nlogo").write_text(model)
        shutil.copy2(
            source_root / study / "symmetric-sugar-map.txt",
            directory / "symmetric-sugar-map.txt",
        )
        shutil.copytree(runtime / "classes/matrix", directory / "matrix")
        command = [
            java,
            "-Xmx1g",
            "-Djava.awt.headless=true",
            "-cp",
            classpath,
            "Replay",
            str(directory / "model.nlogo"),
            parameters["group_a"],
            parameters["group_b"],
            str(config.timesteps),
            str(directory / "trajectory.csv"),
        ]
        execute_recorder(command, directory)
        with (directory / "trajectory.csv").open() as stream:
            raw_rows = list(csv.DictReader(stream))
        if len(raw_rows) != config.timesteps + 1:
            raise ValueError("incomplete Brearcliffe native trajectory")
        observations = []
        for tick, row in enumerate(raw_rows):
            values = {key: float(value) for key, value in row.items()}
            if (
                len(values) != 17
                or values["tick"] != tick
                or not all(math.isfinite(v) for v in values.values())
            ):
                raise ValueError("invalid native recorder observation")
            observations.append(
                {
                    "timestep": tick,
                    "width": 0,
                    "height": 0,
                    "sugar": [],
                    "spice": [],
                    "agents": [],
                    "measurements": {
                        "population": int(
                            values["count group-A"] + values["count group-B"]
                        ),
                        "resource_gini": None,
                        **values,
                    },
                    "native_state_sha256": hashlib.sha256(
                        json.dumps(values, sort_keys=True).encode()
                    ).hexdigest(),
                }
            )
        horizon = 20000
        recorder = "Per-tick native aggregate statistics only. No spatial state or unreported Gini is reconstructed. Hashes identify recorded observations, not complete native RNG/state."
    else:
        if config.timesteps != 50:
            raise ValueError("Oremland native evaluator requires exactly50steps")
        (directory / "model.nlogo").write_text(model)
        shutil.copy2(source_root / study / "sugar-map.txt", directory / "sugar-map.txt")
        request = {
            "id": "episode",
            "seed": seed,
            "phase": parameters["phase"],
            "clipped": parameters["clipped"],
            "policy": parameters["rates"],
        }
        (directory / "request.jsonl").write_text(json.dumps(request) + "\n")
        command = [
            java,
            "-Xmx1g",
            "-Djava.awt.headless=true",
            "-cp",
            classpath,
            "RunPolicyBatch",
            str(directory / "model.nlogo"),
            str(directory / "request.jsonl"),
            str(directory / "results.jsonl"),
        ]
        execute_recorder(command, directory)
        rows = (directory / "results.jsonl").read_text().splitlines()
        if len(rows) != 1:
            raise ValueError("expected exactly one complete native evaluator result")
        native = json.loads(rows[0])
        if native["steps"] != 50 or any(
            native[k] != request[k] for k in ["id", "seed", "phase", "clipped"]
        ):
            raise ValueError("native evaluator request/output mismatch")
        measurements = {
            key: native[key] for key in ["population", "total_tax", "debt_refund"]
        }
        if native["population"] != int(native["population"]):
            raise ValueError("native population is not an integer count")
        measurements["population"] = int(native["population"])
        measurements["resource_gini"] = None
        observations = [
            {
                "timestep": 50,
                "width": 0,
                "height": 0,
                "sugar": [],
                "spice": [],
                "agents": [],
                "measurements": measurements,
                "native_state_sha256": native["state_sha256"],
            }
        ]
        horizon = 50
        recorder = "Endpoint native evaluator only, with original survivor-state hash. Intermediate spatial states and unreported Gini are unavailable. Reconstruction choices remain explicit."
    provenance = {
        **source,
        "engine": "native-netlogo",
        "native_seed": seed,
        "seed_mapping": "nonnegative episode seed modulo2147483647",
        "java_version": version,
        "netlogo": qualification,
        "recorder_scope": recorder,
        "native_output_sha256": hashlib.sha256(
            (
                directory
                / ("trajectory.csv" if study == "brearcliffe_2020" else "results.jsonl")
            ).read_bytes()
        ).hexdigest(),
        "executed_model_sha256": hashlib.sha256(
            (directory / "model.nlogo").read_bytes()
        ).hexdigest(),
    }
    return finish_episode(
        config, parameters, observations, provenance, started, horizon
    )
