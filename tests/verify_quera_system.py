"""Qualify a complete native Julia episode through the public game/player protocol.

Run inside the packaged game: python /qualification/verify_quera_system.py NEW_OUTPUT.
CI mounts this test directory read-only at /qualification.
"""

import gzip
import json
import math
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
        "paper-quera-forward",
        "--seeds",
        "0",
        "--out",
        str(output),
    ],
    check=True,
    timeout=650,
)
replay = json.loads(
    zlib.decompress((output / "paper-quera-forward/0/replay.bin").read_bytes())
)
expected = json.loads(
    gzip.decompress(
        (Path(__file__).parent / "fixtures/research/quera-seed0.json.gz").read_bytes()
    )
)
assert len(replay["frames"]) == 50
assert replay["details"]["duration_override"] is False
assert replay["details"]["executed_horizon"] == 49
errors = {"wealth": 0.0, "sugar": 0.0}
for tick, frame in enumerate(replay["frames"]):
    for kind, count in [("agents", 100), ("cells", 625)]:
        actual_rows = frame["native_observation"][kind]
        wanted_rows = expected[kind][tick * count : (tick + 1) * count]
        assert len(actual_rows) == len(wanted_rows) == count
        for actual, wanted in zip(actual_rows, wanted_rows, strict=True):
            assert actual.keys() == wanted.keys()
            for name, value in wanted.items():
                if name in errors:
                    errors[name] = max(errors[name], abs(actual[name] - value))
                    assert math.isclose(
                        actual[name], value, rel_tol=1e-12, abs_tol=1e-12
                    ), (tick, kind, name, actual[name], value)
                else:
                    assert actual[name] == value, (tick, kind, name)
assert replay["frames"][-1]["measurements"]["population"] == 75
assert json.loads((output / "paper-quera-forward/0/results.json").read_bytes())[
    "scores"
] == [0.0]
print(
    json.dumps(
        {
            "qualified_native_states": 50,
            "agent_rows": 5000,
            "cell_rows": 31250,
            "maximum_absolute_error": errors,
        }
    )
)
