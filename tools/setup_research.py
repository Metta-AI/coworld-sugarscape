#!/usr/bin/env python3
"""Install the pinned native Python workers used by research variants and system checks."""

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    "COWORLD_RESEARCH_PYTHON": (
        ".research-venv",
        "3.11.14",
        ["pydantic==2.12.3", "jsonschema==4.25.1"],
    ),
    "COWORLD_RESEARCH_PYTHON_DOGAN": (
        ".dogan-venv",
        "3.12.4",
        [
            "pydantic==2.12.3",
            "jsonschema==4.25.1",
            "mesa==3.5.1",
            "numpy==2.4.2",
            "pandas==2.3.3",
            "networkx==3.7",
        ],
    ),
}
if __name__ == "__main__":
    subprocess.run(
        [sys.executable, str(ROOT / "tools/fetch_research_sources.py")], check=True
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"UV_PROJECT", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"}
    }
    for variable, (directory, version, dependencies) in WORKERS.items():
        python = ROOT / directory / "bin/python"
        if not python.exists():
            subprocess.run(
                [
                    "uv",
                    "venv",
                    "--no-project",
                    "--python",
                    version,
                    str(ROOT / directory),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )
        subprocess.run(
            [
                str(python),
                "-c",
                "import platform; assert platform.python_version() == " + repr(version),
            ],
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), *dependencies],
            env=environment,
            check=True,
        )
        print("export " + variable + "=" + str(python))
