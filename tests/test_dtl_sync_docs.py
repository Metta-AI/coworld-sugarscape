from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import yaml

from dtl_sync_support import load_sync

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/dtl-sync.md"


def test_runbook_commands_match_cli_help():
    text = RUNBOOK.read_text()
    commands = re.findall(r"```(?:sh|bash)\n(.*?)```", text, re.S)
    checked = set()
    for block in commands:
        for line in block.replace("\\\n", " ").splitlines():
            match = re.search(r"tools/dtl_sync.py (detect|prepare inputs|prepare patch|verify|publish tree|publish deliver|publish retry-alerts|publish failure)\b(.*)", line)
            if not match:
                continue
            command, arguments = match.groups()
            result = subprocess.run([sys.executable, str(ROOT / "tools/dtl_sync.py"),
                                     *command.split(), "--help"], capture_output=True, text=True)
            assert result.returncode == 0
            flags = set(re.findall(r"--[a-z][a-z-]*", arguments))
            assert flags <= set(re.findall(r"--[a-z][a-z-]*", result.stdout))
            checked.add(command)
    assert checked == {"detect", "prepare inputs", "prepare patch", "verify", "publish tree",
                       "publish deliver", "publish retry-alerts", "publish failure"}
    workflow = yaml.safe_load((ROOT / ".github/workflows/dtl-sync.yml").read_text())
    dispatch = re.findall(r"^gh workflow run dtl-sync.yml.*$", text, re.M)
    assert len(dispatch) == 5
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    for line in dispatch:
        assert "--ref main" in line
        assert set(re.findall(r"-f ([a-z_]+)=", line)) <= inputs.keys()


def test_documented_patch_policy_matches_constants():
    sync = load_sync()
    text = RUNBOOK.read_text()
    for label, paths in [("Allowed directories", sync.ALLOWED_DIRECTORIES),
                         ("Allowed files", sync.ALLOWED_FILES),
                         ("Protected files", sync.PROTECTED_FILES),
                         ("Protected prefixes", sync.PROTECTED_PREFIXES)]:
        row = next(line for line in text.splitlines() if line.startswith(f"| {label} |"))
        assert set(re.findall(r"`([^`]+)`", row)) == set(paths)


def test_workflow_required_check_names_match_runbook():
    text = RUNBOOK.read_text()
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    section = text.split("## Required checks for rollout\n", 1)[1].split("\n## ", 1)[0]
    contexts = set(re.findall(r"`([^`]+)`", section.split("\n\n", 1)[0]))
    assert contexts == set(workflow["jobs"])
    assert all("name" not in job for job in workflow["jobs"].values())
