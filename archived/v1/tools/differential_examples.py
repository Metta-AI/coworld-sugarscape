#!/usr/bin/env python3
# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
"""Compare short native runs with every pinned DTL example.

This is an oracle-generation tool, not a production dependency. It rewrites
only output paths and the timestep cap in temporary copies of upstream
configurations, then compares the emitted bytes.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "reference" / "dtl-python" / "examples"
PYTHON_ORACLE = ROOT / "reference" / "dtl-python" / "sugarscape.py"


def first_difference(expected: bytes, actual: bytes) -> str:
    limit = min(len(expected), len(actual))
    offset = next((i for i in range(limit) if expected[i] != actual[i]), limit)
    if offset == limit and len(expected) == len(actual):
        return "identical"
    start = max(0, offset - 60)
    end = offset + 120
    byte_difference = (
        f"byte {offset}; python={expected[start:end]!r}; "
        f"nim={actual[start:end]!r}"
    )
    try:
        expected_document = json.loads(expected)
        actual_document = json.loads(actual)
        expected_rows = (
            expected_document
            if isinstance(expected_document, list)
            else [expected_document]
        )
        actual_rows = (
            actual_document if isinstance(actual_document, list) else [actual_document]
        )
        for row_index, (expected_row, actual_row) in enumerate(
            zip(expected_rows, actual_rows, strict=False)
        ):
            if expected_row != actual_row:
                differences = [
                    f"{key}: {expected_row.get(key)!r} != {actual_row.get(key)!r}"
                    for key in expected_row.keys() | actual_row.keys()
                    if expected_row.get(key) != actual_row.get(key)
                ]
                return (
                    f"row {row_index + 1}; "
                    f"python ID={expected_row.get('ID')!r} "
                    f"timestep={expected_row.get('timestep')!r}; "
                    f"nim ID={actual_row.get('ID')!r} "
                    f"timestep={actual_row.get('timestep')!r}; "
                    + "; ".join(differences[:8])
                    + f"; {byte_difference}"
                )
    except (json.JSONDecodeError, TypeError):
        pass
    return byte_difference


def configured_copy(
    source: Path,
    destination: Path,
    logfile: Path,
    timesteps: int | None,
    logfile_format: str,
    agent_logfile: Path | None = None,
) -> None:
    raw = json.loads(source.read_text())
    options = raw.setdefault("sugarscapeOptions", {}) if "sugarscapeOptions" in raw else raw
    options["agentLogfile"] = (
        str(agent_logfile) if agent_logfile is not None else None
    )
    options["headlessMode"] = True
    options["logfile"] = str(logfile)
    options["logfileFormat"] = logfile_format
    environment_file = options.get("environmentFile")
    if environment_file and not Path(environment_file).is_absolute():
        options["environmentFile"] = str((ROOT / environment_file).resolve())
    if timesteps is not None:
        options["timesteps"] = timesteps
    destination.write_text(json.dumps(raw))


def compare_example(
    binary: Path,
    python: Path,
    example: Path,
    timesteps: int | None,
    logfile_format: str,
    compare_agent_log: bool,
    retained_workspace: Path | None = None,
) -> str | None:
    workspace_context = (
        contextlib.nullcontext(str(retained_workspace))
        if retained_workspace is not None
        else tempfile.TemporaryDirectory(prefix="sugarscape-differential-")
    )
    if retained_workspace is not None:
        retained_workspace.mkdir(parents=True, exist_ok=True)
    with workspace_context as temp:
        workspace = Path(temp)
        python_log = workspace / "python.json"
        nim_log = workspace / "nim.json"
        python_agent_log = workspace / "python-agents.json"
        nim_agent_log = workspace / "nim-agents.json"
        python_config = workspace / "python-config.json"
        nim_config = workspace / "nim-config.json"
        configured_copy(
            example,
            python_config,
            python_log,
            timesteps,
            logfile_format,
            python_agent_log if compare_agent_log else None,
        )
        configured_copy(
            example,
            nim_config,
            nim_log,
            timesteps,
            logfile_format,
            nim_agent_log if compare_agent_log else None,
        )
        subprocess.run(
            [str(python), str(PYTHON_ORACLE), "--conf", str(python_config)],
            cwd=workspace,
            check=True,
        )
        subprocess.run(
            [str(binary), "--conf", str(nim_config)],
            cwd=workspace,
            check=True,
        )
        expected = python_log.read_bytes()
        actual = nim_log.read_bytes()
        if expected == actual:
            if not compare_agent_log:
                return None
            expected_agents = python_agent_log.read_bytes()
            actual_agents = nim_agent_log.read_bytes()
            if expected_agents == actual_agents:
                return None
            return "agent log: " + first_difference(
                expected_agents,
                actual_agents,
            )
        return "aggregate log: " + first_difference(expected, actual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--timesteps", type=int, default=4)
    parser.add_argument(
        "--full",
        action="store_true",
        help="preserve each example's configured timestep limit",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="CPython interpreter for the pinned reference implementation",
    )
    parser.add_argument("--example", action="append", default=[])
    parser.add_argument(
        "--config",
        action="append",
        type=Path,
        default=[],
        help="compare an additional configuration file",
    )
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument(
        "--agent-log",
        action="store_true",
        help="also require byte-identical per-agent logs",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="retain generated configs and logs under this directory",
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    python = args.python.resolve()
    timesteps = None if args.full else args.timesteps
    examples = args.config or (
        [EXAMPLES / f"{name}.json" for name in args.example]
        if args.example
        else sorted(EXAMPLES.glob("*.json"))
    )

    failures = 0
    for example in examples:
        difference = compare_example(
            binary,
            python,
            example,
            timesteps,
            args.format,
            args.agent_log,
            (
                args.workspace.resolve() / example.stem
                if args.workspace is not None
                else None
            ),
        )
        if difference is None:
            print(f"PASS {example.stem}")
        else:
            failures += 1
            print(f"FAIL {example.stem}: {difference}")
    print(f"{len(examples) - failures}/{len(examples)} byte-identical")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
