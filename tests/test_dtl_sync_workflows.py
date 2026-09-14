from __future__ import annotations

import copy
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "astral-sh/setup-uv": "bec219d24cd3e171d82865faccec33120bb574f4",
}
ACTIONLINT_CHECKSUM = "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _check_action_pins(workflow: dict) -> None:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                action, revision = step["uses"].split("@")
                assert re.fullmatch(r"[0-9a-f]{40}", revision), step["uses"]
                assert revision == ACTION_PINS[action], step["uses"]


def test_ci_events_are_pr_to_main_and_push_to_main() -> None:
    workflow = _workflow()
    assert workflow["on"] == {
        "pull_request": {"branches": ["main"]},
        "push": {"branches": ["main"]},
    }
    assert set(workflow["jobs"]) == {"tests", "workflow-lint", "image-smoke"}


def test_ci_uses_pinned_tools_and_read_only_checkout() -> None:
    workflow = _workflow()
    _check_action_pins(workflow)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert 0 < job["timeout-minutes"] <= 30
        assert "permissions" not in job
        assert "secrets." not in str(job)
        checkout = job["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert checkout["with"]["persist-credentials"] is False
    steps = workflow["jobs"]["tests"]["steps"]
    assert steps[0]["with"]["submodules"] == "recursive"
    python = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    uv = next(step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert python["with"]["python-version"] == "3.13.5"
    assert uv["with"]["version"] == "0.12.13"
    assert uv["with"]["enable-cache"] is False


def test_ci_runs_project_suite_and_actionlint() -> None:
    jobs = _workflow()["jobs"]
    tests = jobs["tests"]
    assert tests["env"]["PYTHONHASHSEED"] == "0"
    commands = [step["run"] for step in tests["steps"] if "run" in step]
    assert commands == ["uv sync", '.venv/bin/python -m pytest -q -n auto -m "not perf"',
                        ".venv/bin/python -m pytest -q -m perf"]
    lint_commands = [step["run"] for step in jobs["workflow-lint"]["steps"] if "run" in step]
    install, run = lint_commands
    assert "releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz" in install
    assert ACTIONLINT_CHECKSUM in install
    assert "sha256sum --check" in install
    assert install.index("sha256sum --check") < install.index("tar -xzf")
    assert run == "build/tools/actionlint -color"


def test_ci_builds_and_smokes_game_on_prs() -> None:
    job = _workflow()["jobs"]["image-smoke"]
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["steps"][0]["with"]["submodules"] == "recursive"
    commands = [step["run"] for step in job["steps"] if "run" in step]
    assert commands[0] == "docker build --tag sugarscape-ci --file Dockerfile ."
    assert "docker run --rm --network none sugarscape-ci python -c" in commands[1]
    assert "import coworld.dtl" in commands[1]
    assert "'tkinter' not in sys.modules" in commands[1]
    assert all("docker push" not in command for command in commands)


@pytest.mark.parametrize("revision", ["v7", "main", "TODO", "0" * 40])
def test_workflow_pin_validation_rejects_floating_or_placeholder_refs(revision: str) -> None:
    workflow = copy.deepcopy(_workflow())
    workflow["jobs"]["tests"]["steps"][0]["uses"] = f"actions/checkout@{revision}"
    with pytest.raises(AssertionError):
        _check_action_pins(workflow)
