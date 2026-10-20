"""Prepare pinned original engines with population export after complete simulation."""

import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
assets = Path(__file__).resolve().parent
pins = json.loads((assets / "timing/revision-fidelity.json").read_text())["hashes"][
    "timing"
]
for name, digest in pins.items():
    assert hashlib.sha256((args.source / name).read_bytes()).hexdigest() == digest
args.output.mkdir(parents=True, exist_ok=False)
for name in pins:
    destination = args.output / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((args.source / name).read_bytes())
packaging = {}
for variant in ["seq", "io", "tvar", "tarray"]:
    for filename in ["LICENSE", "ChangeLog.md"]:
        name = f"criterion/sugarscape-{variant}/{filename}"
        data = (args.source / name).read_bytes()
        (args.output / name).write_bytes(data)
        packaging[name] = hashlib.sha256(data).hexdigest()
changes = {}
for variant in ["seq", "io", "tvar", "tarray"]:
    name = f"criterion/sugarscape-{variant}/src/Main.hs"
    path = args.output / name
    original = path.read_text()
    assert original.count("    Crit.defaultMain [") == 1
    first = original.index("    Crit.defaultMain [")
    last = original.index("  where\n", first)
    call = "initSim steps dt" if variant == "seq" else "initSim g t dt"
    replacement = (
        "    [agentsText, rebirthText] <- getArgs\n"
        f"    outputs <- {call} (read agentsText) (read rebirthText)\n"
        "    forced <- evaluate (force outputs)\n"
        '    putStrLn "T,PopSize"\n'
        '    mapM_ (\\(outputTime, _, agents) -> putStrLn (show outputTime ++ "," ++ show (length agents))) (reverse forced)\n'
    )
    patched = original[:first] + replacement + original[last:]
    patched = patched.replace(
        "module Main where\n",
        "module Main where\n\nimport System.Environment (getArgs)\n"
        "import Control.DeepSeq (force)\nimport Control.Exception (evaluate)\n",
        1,
    )
    # The initializer and all simulation loops remain byte-for-byte unchanged.
    assert patched[patched.index("  where\n") :] == original[last:]
    patched = patched.replace("import qualified Criterion.Main as Crit\n", "")
    patched = patched.replace("    cores <- getNumCapabilities\n", "")
    patched = patched.replace("import Control.Concurrent\n", "")
    path.write_text(patched)
    changes[name] = {
        "original_sha256": pins[name],
        "exporter_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
report = {
    "revision": "f5851488bf2369e2bbdc3f2499ed69c142de9fec",
    "source_sha256": pins,
    "changes": changes,
    "packaging_sha256": packaging,
    "observation": "Replace Criterion dispatch with one original initSim call, force its complete result as nfIO does, then export chronological time/population counts. No model loop, initialization, RNG, or instrumentation change.",
    "limits": "Population is the returned observable-agent count, not an independently reconstructed live-agent state. Concurrent scheduling remains nondeterministic. Exporter execution is not timing evidence.",
}
(args.output / "observer-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"verified_source_files": len(pins), "changed_entrypoints": 4}))
