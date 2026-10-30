"""Materialize hash-pinned research sources and reference observations during setup."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import ZipFile

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "src/coworld/research_sources"


def store(path, data, expected):
    if path.exists():
        data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Research input hash mismatch: {path}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".download")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path


def fetch(item):
    url, path, expected = item
    if path.exists():
        data = path.read_bytes()
    else:
        request = Request(
            quote(url, safe=":/"),
            headers={
                "User-Agent": "Sugarscape-replication-source-recovery/1.0",
            },
        )
        with urlopen(request, timeout=120) as response:
            data = response.read()
    return store(path, data, expected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["sources", "fixtures", "all"], default="all")
    args = parser.parse_args()
    inputs = []
    if args.kind in {"sources", "all"}:
        downloads = json.loads((ROOT / "downloads.json").read_bytes())
        for entry in json.loads((ROOT / "manifest.json").read_bytes()):
            packaging = downloads[entry["study"]]
            for name, url in packaging["files"].items():
                inputs.append(
                    (url, ROOT / entry["study"] / name, entry["files_sha256"][name])
                )
            if "archive" in packaging:
                pin = packaging["archive"]
                archive = fetch(
                    (
                        pin["url"],
                        PROJECT / "build/research-downloads" / pin["sha256"],
                        pin["sha256"],
                    )
                )
                with ZipFile(archive) as bundle:
                    for name, member in pin["files"].items():
                        store(
                            ROOT / entry["study"] / name,
                            bundle.read(member),
                            entry["files_sha256"][name],
                        )
    if args.kind in {"fixtures", "all"}:
        fixtures = PROJECT / "tests/fixtures/research"
        for pin in json.loads((fixtures / "manifest.json").read_bytes()):
            inputs.append((pin["url"], fixtures / pin["path"], pin["sha256"]))
    with ThreadPoolExecutor(max_workers=8) as pool:
        for path in pool.map(fetch, inputs):
            print(path.relative_to(PROJECT))
