"""Build qualified Haskell population observers and retain their Linux runtime closure."""

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "src/coworld/research_sources/thaler_2019"
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
manifest = json.loads((source / "source-manifest.json").read_bytes())
for name, digest in manifest["files_sha256"].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest, name
stack_root = Path(os.environ["STACK_ROOT"])
stack_root.mkdir(parents=True, exist_ok=True)
shutil.copy2(source / "stack-global-config.yaml", stack_root / "config.yaml")
subprocess.run(
    [
        sys.executable,
        str(source / "prepare_population_observers.py"),
        str(source / "original"),
        str(output / "source"),
    ],
    check=True,
)
(output / "bin").mkdir()
(output / "lib").mkdir()
(output / "licenses").mkdir()
qualification = {
    "source": manifest,
    "observer": json.loads((output / "source/observer-manifest.json").read_bytes()),
    "compiler": "8.4.3",
    "probes": {},
    "packages": subprocess.check_output(["dpkg-query", "-W"], text=True),
}
for implementation in ["seq", "io", "tvar", "tarray"]:
    project = output / "source/criterion" / ("sugarscape-" + implementation)
    subprocess.run(
        ["stack", "build", "--jobs", "2"], cwd=project, check=True, timeout=3600
    )
    assert (
        subprocess.check_output(
            ["stack", "exec", "--", "ghc", "--numeric-version"], cwd=project, text=True
        ).strip()
        == "8.4.3"
    )
    install = Path(
        subprocess.check_output(
            ["stack", "path", "--local-install-root"], cwd=project, text=True
        ).strip()
    )
    binary = output / "bin" / ("sugarscape-" + implementation)
    shutil.copy2(install / "bin" / binary.name, binary)
    linked = subprocess.check_output(["ldd", str(binary)], text=True)
    for line in linked.splitlines():
        parts = line.split()
        paths = [part for part in parts if part.startswith("/")]
        if "not found" in line:
            raise ValueError("incomplete Haskell runtime closure: " + line)
        for name in paths:
            path = Path(name)
            destination = output / "lib" / path.name
            if destination.exists():
                assert destination.read_bytes() == path.read_bytes()
            else:
                shutil.copy2(path, destination)
    runtime = [] if implementation == "seq" else ["+RTS", "-N1", "-RTS"]
    command = [
        str(output / "lib/ld-linux-x86-64.so.2"),
        "--library-path",
        str(output / "lib"),
        str(binary),
        "500",
        "False",
        *runtime,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=True, timeout=600
    )
    (output / (implementation + ".csv")).write_text(result.stdout)
    rows = list(csv.DictReader(result.stdout.splitlines()))
    assert len(rows) == 1000
    assert [float(row["T"]) for row in rows] == list(range(1000))
    assert all(0 <= int(row["PopSize"]) <= 2500 for row in rows)
    qualification["probes"][implementation] = {
        "agents": 500,
        "rebirthing": False,
        "capabilities": 1,
        "native_seed": 42,
        "observations": 1000,
        "final_population": int(rows[-1]["PopSize"]),
        "csv_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
    }
for notice in Path("/usr/share/doc").glob("*/copyright"):
    shutil.copy2(
        notice,
        output / "licenses" / (notice.parent.name.replace(":", "_") + ".copyright"),
    )
qualification["files_sha256"] = {
    str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in [output / "bin", output / "lib"]
    for p in sorted(folder.iterdir())
    if p.is_file()
}
(output / "qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
print(
    "Four native Haskell observers and their exact runtime closure qualified",
    flush=True,
)
