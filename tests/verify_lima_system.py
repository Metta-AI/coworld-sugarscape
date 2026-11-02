"""Qualify the complete native architecture through real public game/player processes."""

import json
from pathlib import Path
import subprocess
import sys
import zlib

output = Path(sys.argv[1]).resolve()
subprocess.run(
    [
        sys.executable,
        "tools/research_experiments.py",
        "--variant",
        "paper-lima-container",
        "--seeds",
        "1729",
        "--timeout-seconds",
        "3300",
        "--out",
        str(output),
    ],
    check=True,
    timeout=3400,
)
episode = output / "paper-lima-container/1729"
result = json.loads((episode / "results.json").read_bytes())
replay = json.loads(zlib.decompress((episode / "replay.bin").read_bytes()))
provenance = replay["details"]["provenance"]
assert result["scores"] == [0.0]
assert result["result.timesteps_completed"] == 1000
assert result["result.gini_final"] is None
assert provenance["execution"]["native_model_steps"] == {"m1": 1000, "m2": 1000}
assert provenance["native_audit"]["registered_agents_accounted_for_once"] == 799
assert provenance["snapshot_audit"]["initial_unique_agents"] == 799
assert provenance["snapshot_audit"]["unmatched_deliveries"] == 0
assert (
    provenance["transport_qualification"]["all_native_listeners_bound_to_loopback"]
    is True
)
assert len(replay["frames"]) == 1
frame = replay["frames"][0]
assert frame["width"] == frame["height"] == 0
assert frame["agents"] == []
assert set(frame["native_observation"]["netlogo_logs"]) == {"m1", "m2"}
assert frame["native_observation"]["saved_agents"]
print(
    json.dumps(
        {
            "native_models": 3,
            "netlogo_steps_per_world": 1000,
            "registered_identities_reconciled": 799,
            "unmatched_router_deliveries": 0,
            "scope": "Native container-scenario method through public Coworld processes. No host-GUI, historical timing or spontaneous AgentSpeak re-entry claim.",
        }
    )
)
