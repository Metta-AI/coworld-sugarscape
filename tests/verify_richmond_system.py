"""Qualify the complete released GPU method through the public Coworld protocol."""

import json
import os
from pathlib import Path
import subprocess
import sys
import zlib

output = (
    Path(os.environ["GMN_OUTPUT_DIR"]).resolve()
    if "GMN_OUTPUT_DIR" in os.environ
    else Path(sys.argv[1]).resolve()
)
native = output / "native"
native.mkdir(exist_ok=False)
subprocess.run(
    [
        sys.executable,
        "tools/research_experiments.py",
        "--variant",
        "paper-richmond-full",
        "--seeds",
        "1729",
        "--timeout-seconds",
        "1800",
        "--out",
        str(output / "episode"),
    ],
    check=True,
    env={**os.environ, "COWORLD_RICHMOND_EVIDENCE_DIR": str(native)},
    timeout=1850,
)
episode = output / "episode/paper-richmond-full/1729"
results = json.loads((episode / "results.json").read_bytes())
replay = json.loads(zlib.decompress((episode / "replay.bin").read_bytes()))
assert results["scores"] == [0.0]
assert results["result.gini_final"] is None
assert len(replay["frames"]) == 1
provenance = replay["details"]["provenance"]
assert provenance["hardware"]["device_count"] == 1
assert provenance["native_audit"]["complete_grid"] is True
assert provenance["native_audit"]["step_rows"] == 6600
assert provenance["native_audit"]["resolution_rows"] == 162
assert provenance["qualification"]["model_source_changes"] == []
assert provenance["native_seeds"] == [0, 1, 2]
verdict = {
    "complete_native_method": True,
    "native_conditions": 84,
    "population_rows": 6600,
    "resolution_rows": 162,
    "archive_comparison": provenance["archive_comparison"],
    "historical_v100_timing_equivalence": False,
    "scope": "One real GPU game, baseline player and spectator over the public WebSocket protocol. Source and method remain unchanged. Hosted Kubernetes deployment is a separate qualification.",
}
(output / "method-qualification.json").write_text(json.dumps(verdict, indent=2) + "\n")
if "GMN_RESULT_PATH" in os.environ:
    Path(os.environ["GMN_RESULT_PATH"]).write_text(json.dumps(verdict) + "\n")
print(json.dumps(verdict))
