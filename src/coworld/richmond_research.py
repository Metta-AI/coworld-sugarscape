"""Execute the unmodified released FLAME GPU benchmark on one allocated GPU."""

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter


def run(config, parameters, source, source_root):
    from .research import finish_episode

    started = perf_counter()
    runtime = Path(os.environ["COWORLD_RICHMOND"])
    qualification = json.loads((runtime / "qualification.json").read_bytes())
    if qualification["source"] != source:
        raise ValueError("Richmond source/runtime qualification mismatch")
    for name, digest in qualification["files_sha256"].items():
        if hashlib.sha256((runtime / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Richmond native runtime mismatch: " + name)
    directory = Path(tempfile.mkdtemp(prefix="sugarscape-richmond-"))
    run_dir = directory / "run"
    run_dir.mkdir()
    environment = {
        **os.environ,
        "FLAMEGPU2_INC_DIR": str(runtime / "engine/include"),
        "CUDA_PATH": "/usr/local/cuda-11.8",
        "CUDA_HOME": "/usr/local/cuda-11.8",
        "LD_LIBRARY_PATH": "/usr/local/cuda-11.8/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64",
    }
    hardware = json.loads(
        subprocess.check_output(
            [str(runtime / "bin/gpu-probe")], env=environment, text=True, timeout=30
        )
    )
    if (
        hardware["device_count"] != 1
        or hardware["compute_capability"] not in qualification["architectures"]
    ):
        raise ValueError(
            "the packaged CUDA runtime requires one allocated A10, L4 or Hopper GPU"
        )
    hardware["driver_and_clocks"] = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=uuid,name,driver_version,clocks.current.graphics,clocks.current.memory",
            "--format=csv",
        ],
        env=environment,
        text=True,
        timeout=30,
    )
    with (
        (run_dir / "stdout.log").open("x") as stdout,
        (run_dir / "stderr.log").open("x") as stderr,
    ):
        result = subprocess.run(
            [
                "timeout",
                "--signal=TERM",
                "--kill-after=30",
                "1700",
                str(runtime / "bin/submodel-benchmark"),
            ],
            cwd=run_dir,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=1740,
        )
    (run_dir / "execution-exit-code.txt").write_text(str(result.returncode) + "\n")
    (directory / "exit-code.txt").write_text(str(result.returncode) + "\n")
    shutil.copy2(
        source_root / "richmond_2023/source-manifest.json",
        directory / "source-manifest.json",
    )
    csv_rows = {}
    for path in sorted(run_dir.glob("*.csv")):
        with path.open() as stream:
            csv_rows[path.name] = sum(1 for _ in csv.DictReader(stream))
    receipt = {
        "execution_exit_code": result.returncode,
        "files": {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(run_dir.iterdir())
            if p.is_file()
        },
        "csv_rows": csv_rows,
    }
    (directory / "qualification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if result.returncode != 0:
        raise RuntimeError(
            "native Richmond benchmark failed; retained evidence at "
            + str(directory)
            + ": "
            + (run_dir / "stderr.log").read_text()
        )
    subprocess.run(
        [
            sys.executable,
            str(source_root / "richmond_2023/audit_native.py"),
            str(directory),
            str(directory / "audit"),
        ],
        check=True,
        timeout=30,
    )
    audit = json.loads((directory / "audit/audit.json").read_bytes())
    if (
        not audit["complete_grid"]
        or audit["step_rows"] != 6600
        or audit["resolution_rows"] != 162
    ):
        raise ValueError("native Richmond benchmark did not complete all 84 conditions")
    native_csv = {p.name: p.read_text() for p in sorted(run_dir.glob("*.csv"))}
    comparisons = {}
    for name in [
        "performance_scalingperStep.csv",
        "occupationperStep.csv",
        "resolution_steps.csv",
    ]:
        with (run_dir / name).open() as stream:
            actual = list(csv.DictReader(stream))
        with (source_root / "richmond_2023/reference" / name).open() as stream:
            expected = list(csv.DictReader(stream))
        assert len(actual) == len(expected)
        mismatches = sum(
            {k: v for k, v in left.items() if k != "s_step"}
            != {k: v for k, v in right.items() if k != "s_step"}
            for left, right in zip(actual, expected, strict=True)
        )
        comparisons[name] = {
            "rows": len(actual),
            "nontiming_row_mismatches": mismatches,
        }
    with (run_dir / "occupationperStep.csv").open() as stream:
        last = list(csv.DictReader(stream))[-1]
    frame = {
        "timestep": 100,
        "width": 0,
        "height": 0,
        "sugar": [],
        "spice": [],
        "agents": [],
        "measurements": {
            "population": int(last["pop_count"]),
            "resource_gini": None,
            "population_scope": "Final occupation record: seed 2, width 512, density 0.64, step 99. This is not a total across 84 cases.",
            "completed_conditions": 84,
            "native_step_rows": 6600,
            "resolution_rows": 162,
        },
        "native_observation": {"csv_files": native_csv},
        "native_state_sha256": hashlib.sha256(
            json.dumps(native_csv, sort_keys=True).encode()
        ).hexdigest(),
    }
    provenance = {
        **source,
        "qualification": qualification,
        "hardware": hardware,
        "native_audit": audit,
        "native_files": receipt,
        "archive_comparison": comparisons,
        "native_seeds": [0, 1, 2],
        "seed_mapping": "The original benchmark runs its fixed seeds 0–2. The episode seed does not replace them.",
        "recorder_scope": "All 84 unmodified benchmark cases: 48 scaling and 18 occupation cases at 100 steps; 18 resolution cases at 3 steps. Retain all 6,600 population records and 162 resolution rows. One endpoint frame contains the complete CSV collection, not an invented shared trajectory. No independent cell-state, historical V100 timing or corrected-model claim.",
    }
    return finish_episode(config, parameters, [frame], provenance, started, 100)
