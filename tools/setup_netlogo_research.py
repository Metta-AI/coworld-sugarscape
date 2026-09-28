#!/usr/bin/env python3
"""Fetch verified NetLogo distributions and compile the retained native recorders."""

from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-dir",
        type=Path,
        help="Reuse existing hash-verified original distribution archives",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build/research-runtimes")
    parser.add_argument("--javac", default="javac")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = json.loads(
        (ROOT / "src/coworld/research_sources/netlogo-runtimes.json").read_bytes()
    )
    for version, entry in runtime.items():
        archive = (
            (args.archive_dir / f"NetLogo-{version}-64.tgz")
            if args.archive_dir
            else args.output / f"NetLogo-{version}-64.tgz"
        )
        if not archive.exists():
            with (
                urlopen(
                    Request(
                        entry["url"], headers={"User-Agent": "coworld-sugarscape/1.0"}
                    ),
                    timeout=120,
                ) as source,
                archive.open("xb") as target,
            ):
                shutil.copyfileobj(source, target)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["archive_sha256"]:
            raise ValueError("NetLogo archive hash mismatch: " + version)
        destination = args.output / ("netlogo-" + version)
        if not destination.exists():
            destination.mkdir()
            with tarfile.open(archive) as source:
                for member in source.getmembers():
                    relative = Path(*Path(member.name).parts[1:])
                    if str(relative) == "." or relative.parts[0] != "app":
                        continue
                    member.name = str(relative)
                    source.extract(member, destination, filter="data")
        study = "brearcliffe_2020" if version == "6.1.1" else "oremland_2014"
        driver = "Replay" if version == "6.1.1" else "RunPolicyBatch"
        classes = destination / "classes"
        classes.mkdir(exist_ok=True)
        classpath_jars = sorted(p.name for p in (destination / "app").glob("*.jar"))
        if version == "5.3.1":
            configuration = (destination / "app/NetLogo.cfg").read_text().splitlines()
            classpath_jars = [
                "NetLogo.jar",
                *next(
                    line.split("=", 1)[1]
                    for line in configuration
                    if line.startswith("app.classpath=")
                ).split(":"),
            ]
        classpath = ":".join(str(destination / "app" / name) for name in classpath_jars)
        subprocess.run(
            [
                args.javac,
                "-cp",
                classpath,
                "-d",
                str(classes),
                str(ROOT / "src/coworld/research_sources" / study / (driver + ".java")),
            ],
            check=True,
        )
        if version == "6.1.1":
            matrix = destination / "app/extensions/.bundled/matrix"
            target = classes / "matrix"
            if not target.exists():
                shutil.copytree(matrix, target)
        jars = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((destination / "app").glob("*.jar"))
        }
        (destination / "qualification.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "archive_sha256": entry["archive_sha256"],
                    "jars_sha256": jars,
                    "classpath_jars": classpath_jars,
                    "classes_sha256": {
                        str(p.relative_to(classes)): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in sorted(classes.rglob("*"))
                        if p.is_file()
                    },
                    "driver_source_sha256": hashlib.sha256(
                        (
                            ROOT
                            / "src/coworld/research_sources"
                            / study
                            / (driver + ".java")
                        ).read_bytes()
                    ).hexdigest(),
                },
                indent=2,
            )
            + "\n"
        )
        print("export COWORLD_NETLOGO_" + version[0] + "=" + str(destination.resolve()))
