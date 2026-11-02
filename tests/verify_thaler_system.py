"""Qualify complete public game/player episodes using all four native Haskell kernels."""

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zlib

output = Path(sys.argv[1]).resolve()
variants = [
    f"paper-thaler-{implementation}-{mode}"
    for implementation in ["seq", "io", "tvar", "tarray"]
    for mode in ["baseline", "rebirth"]
]
command = [
    sys.executable,
    "tools/research_experiments.py",
    "--out",
    str(output),
    "--seeds",
    "42",
]
for variant in variants:
    command += ["--variant", variant]
subprocess.run(command, check=True, timeout=1200)
for variant in variants:
    folder = output / variant / "42"
    replay = json.loads(zlib.decompress((folder / "replay.bin").read_bytes()))
    details = replay["details"]
    assert len(replay["frames"]) == 1000
    assert [frame["timestep"] for frame in replay["frames"]] == list(range(1, 1001))
    assert [frame["measurements"]["native_time"] for frame in replay["frames"]] == list(
        range(1000)
    )
    assert details["duration_override"] is False
    assert details["provenance"]["native_seed"] == 42
    assert details["provenance"]["qualification"]["compiler"] == "8.4.3"
    kind = details["parameters"]["implementation"]
    expected_binary = details["provenance"]["qualification"]["files_sha256"][
        f"bin/sugarscape-{kind}"
    ]
    assert details["provenance"]["executed_binary_sha256"] == expected_binary
    assert json.loads((folder / "results.json").read_bytes())["scores"] == [0.0]
    assert all(
        frame["width"] == 0 and frame["agents"] == [] for frame in replay["frames"]
    )
    if variant == "paper-thaler-seq-baseline":
        target = Path(__file__).parent / "fixtures/research/thaler-seq-baseline.csv"
        assert (
            details["provenance"]["native_output_sha256"]
            == hashlib.sha256(target.read_bytes()).hexdigest()
        )
        with target.open() as stream:
            wanted = [int(row["PopSize"]) for row in csv.DictReader(stream)]
        assert [
            frame["measurements"]["population"] for frame in replay["frames"]
        ] == wanted
print(
    json.dumps(
        {
            "qualified_native_episodes": 8,
            "observations": 8000,
            "sequential_retained_trajectory": "exact",
            "concurrent_counts": "not forced to match a prior schedule",
        }
    )
)
