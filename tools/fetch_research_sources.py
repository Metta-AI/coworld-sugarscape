"""Materialize pinned research inputs during setup; episodes remain offline."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "src/coworld/research_sources"


def fetch(item):
    url, path, expected = item
    if path.exists():
        data = path.read_bytes()
    else:
        with urlopen(url, timeout=120) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Research source hash mismatch: {path}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".download")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path


if __name__ == "__main__":
    inputs = []
    for entry in json.loads((ROOT / "manifest.json").read_bytes()):
        repository = entry["repository"].removeprefix("https://github.com/")
        for name, upstream in entry["downloads"].items():
            inputs.append(
                (
                    f"https://raw.githubusercontent.com/{repository}/{entry['revision']}/{quote(upstream)}",
                    ROOT / entry["study"] / name,
                    entry["files_sha256"][name],
                )
            )
    with ThreadPoolExecutor(max_workers=8) as pool:
        for path in pool.map(fetch, inputs):
            print(path.relative_to(ROOT))
