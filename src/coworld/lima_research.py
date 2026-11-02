"""Expose the native two-NetLogo/JaCaMo architecture as one reference experiment."""

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
    runtime = Path(os.environ["COWORLD_LIMA"])
    qualification = json.loads((runtime / "qualification.json").read_bytes())
    if qualification["source"] != source:
        raise ValueError("Lima native runtime/source qualification mismatch")
    directory = Path(tempfile.mkdtemp(prefix="sugarscape-lima-"))
    native = directory / "native"
    prefix = os.environ["COWORLD_LIMA_PYTHON_PREFIX"]
    log_path = directory / "native.log"
    try:
        with log_path.open("x") as log:
            subprocess.run(
                [
                    prefix + "/bin/python3.11",
                    str(Path(__file__).with_name("lima_runner.py")),
                    str(native),
                ],
                env={
                    **os.environ,
                    "PYTHONHOME": prefix,
                    "LD_LIBRARY_PATH": prefix + "/lib",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=3200,
            )
    finally:
        sys.stderr.write(log_path.read_text())
    complete = json.loads((native / "complete.json").read_bytes())
    audit = json.loads((native / "native-audit.json").read_bytes())
    snapshot_audit = json.loads((native / "snapshot-audit.json").read_bytes())
    # Each world has its own clock. Retain both native logs and the quiescent SQL
    # snapshot rather than inventing a synchronized spatial trajectory.
    histories = {
        model: (
            native / "shared_volume/netlogo_output" / (model + "_output.txt")
        ).read_text()
        for model in ["m1", "m2"]
    }
    saved_agents = {
        p.name: p.read_text()
        for p in sorted(
            (native / "shared_volume/jacamo/jacamo_model/src/agt/list").glob("*.asl")
        )
    }
    active_jacamo = sum(audit["active_jacamo_agents"].values())
    frame = {
        "timestep": 1000,
        "width": 0,
        "height": 0,
        "sugar": [],
        "spice": [],
        "agents": [],
        "measurements": {
            "population": sum(audit["netlogo_survivors"].values()) + active_jacamo,
            "population_scope": "Agents currently loaded in the two NetLogo worlds and JaCaMo; queued identities are separate.",
            "resource_gini": None,
            "netlogo_survivors": audit["netlogo_survivors"],
            "queued_agents": audit["queued_agents"],
            "active_jacamo_agents": active_jacamo,
            "registered_agents_accounted_for_once": audit[
                "registered_agents_accounted_for_once"
            ],
        },
        "native_observation": {
            "netlogo_logs": histories,
            "jacamo_log": (native / "jacamo.log").read_text(),
            "database_rows": [
                json.loads(line)
                for line in (native / "snapshot-final.jsonl").read_text().splitlines()
            ],
            "saved_agents": saved_agents,
        },
    }
    frame["native_state_sha256"] = hashlib.sha256(
        json.dumps(frame["native_observation"], sort_keys=True).encode()
    ).hexdigest()
    provenance = {
        **source,
        "qualification": qualification,
        "native_audit": audit,
        "snapshot_audit": snapshot_audit,
        "execution": complete,
        "transport_qualification": json.loads(
            (native / "transport-qualified.json").read_bytes()
        ),
        "native_seed_mapping": "The author architecture does not provide a reproducible shared seed. The episode seed is recorded but does not replace its native random streams or asynchronous schedule.",
        "recorder_scope": "Complete 1000-step logs from both original NetLogo models, original JaCaMo log, quiescent SQL snapshot and exported AgentSpeak files. No common spatial clock, hidden native state or Gini is reconstructed. This episode does not prove host-GUI topology or spontaneous saved-agent re-entry.",
    }
    return finish_episode(config, parameters, [frame], provenance, started, 1000)
