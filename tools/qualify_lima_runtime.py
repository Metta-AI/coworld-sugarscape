"""Record the actual native runtime and source bytes for offline Lima episodes."""

import hashlib
import json
from pathlib import Path
import subprocess

root = Path("/opt/lima")
source = json.loads((root / "source/source-manifest.json").read_bytes())
for name, digest in source["files_sha256"].items():
    assert hashlib.sha256((root / "source" / name).read_bytes()).hexdigest() == digest
qualification = {
    "source": source,
    "java8": subprocess.run(
        [str(root / "java8/bin/java"), "-version"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr,
    "java15": subprocess.run(
        [str(root / "java15/bin/java"), "-version"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr,
    "packages": subprocess.check_output(["python", "-m", "pip", "freeze"], text=True),
    "files_sha256": {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ["mysql", "jacamo", "netlogo/app", "java8", "java15"]
        for p in sorted((root / folder).rglob("*"))
        if p.is_file()
    },
    "boundary": "Native processes colocated in one game container. Qualified current dependencies; historical dependency equivalence unproven. No episode-time downloads.",
}
(root / "qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
