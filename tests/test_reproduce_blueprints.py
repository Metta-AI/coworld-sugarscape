from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reproduce_blueprints", ROOT / "tools" / "reproduce_blueprints.py")
assert SPEC is not None and SPEC.loader is not None
paper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper)


@pytest.fixture
def archived_experiment(tmp_path, monkeypatch):
    archive = tmp_path / "configs.zip"
    with ZipFile(archive, "w") as zipped:
        for model in paper.MODELS:
            zipped.writestr(f"{model}7.config", json.dumps({
                "seed": 7, "agentDecisionModels": [model], "timesteps": 5000,
                "logfile": "./historical.json", "startingAgents": 250,
            }))
    monkeypatch.setattr(paper, "ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(paper.subprocess, "check_output", lambda cmd, **_: paper.PAPER_ENGINE if "rev-parse" in cmd else "")
    return ["--engine", str(tmp_path), "--archive", str(archive), "--seeds", "7"]


@pytest.mark.parametrize("timeout", [None, 15])
def test_preserves_archived_configs_and_records_every_model(archived_experiment, tmp_path, monkeypatch, timeout):
    seen = []
    clock = iter(range(0, 80, 10))
    monkeypatch.setattr(paper.time, "perf_counter", lambda: next(clock))

    def simulate(command, **kwargs):
        config = json.loads(Path(command[-1]).read_text())
        seen.append(config)
        assert kwargs["timeout"] == (3600 if timeout is None else timeout) and kwargs["check"]
        Path(config["logfile"]).write_text(json.dumps([
            {"timestep": 0, "population": 250}, {"timestep": 20, "population": 125},
        ]))

    monkeypatch.setattr(paper.subprocess, "run", simulate)
    output = tmp_path / "result"
    timeout_args = [] if timeout is None else ["--timeout-seconds", str(timeout)]
    assert paper.main(archived_experiment + ["--timesteps", "20", "--out", str(output)] + timeout_args) == 0
    assert len(seen) == 4
    report = json.loads((output / "report.json").read_text())
    assert report["duration"] == "shortened smoke"
    assert len(report["runs"]) == 4
    for run in report["runs"]:
        assert run["wall_seconds"] == 10
        assert run["world_ticks_per_second"] == 2
    for model in paper.MODELS:
        original = json.loads((output / "7" / model / "archived.config.json").read_text())
        executed = json.loads((output / "7" / model / "run.config.json").read_text())
        assert original["timesteps"] == 5000
        assert original["logfile"] == "./historical.json"
        assert {k: v for k, v in original.items() if k not in {"logfile", "timesteps"}} == {
            k: v for k, v in executed.items() if k not in {"logfile", "timesteps"}
        }


def test_timeout_keeps_partial_evidence_without_completed_report(archived_experiment, tmp_path, monkeypatch):
    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(paper.subprocess, "run", time_out)
    output = tmp_path / "partial"
    with pytest.raises(subprocess.TimeoutExpired):
        paper.main(archived_experiment + ["--out", str(output)])
    request = json.loads((output / "request.json").read_text())
    assert request["seeds"] == [7]
    assert request["models"] == list(paper.MODELS)
    assert request["timeout_seconds_per_model"] == 3600
    assert request["timesteps_override"] is None
    assert request["planned_runs"] == 4
    assert not (output / "report.json").exists()


def test_rejects_engine_drift_before_output(archived_experiment, tmp_path, monkeypatch):
    monkeypatch.setattr(paper.subprocess, "check_output", lambda *_, **__: "a" * 40)
    output = tmp_path / "wrong-pin"
    with pytest.raises(SystemExit):
        paper.main(archived_experiment + ["--out", str(output)])
    assert not output.exists()


def test_rejects_modified_archive(archived_experiment, tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "ARCHIVE_SHA256", "0" * 64)
    output = tmp_path / "wrong-archive"
    with pytest.raises(SystemExit):
        paper.main(archived_experiment + ["--out", str(output)])
    assert not output.exists()


def test_rejects_short_archived_duration(archived_experiment, tmp_path, monkeypatch):
    archive = tmp_path / "configs.zip"
    with ZipFile(archive) as zipped:
        configs = [(name, json.loads(zipped.read(name))) for name in zipped.namelist()]
    with ZipFile(archive, "w") as zipped:
        for name, config in configs:
            config["timesteps"] = 20
            zipped.writestr(name, json.dumps(config))
    monkeypatch.setattr(paper, "ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    output = tmp_path / "short-archive"
    with pytest.raises(SystemExit):
        paper.main(archived_experiment + ["--out", str(output)])
    assert not output.exists()


def test_rejects_untracked_import_shadow(archived_experiment, tmp_path, monkeypatch):
    def git_output(command, **kwargs):
        if "rev-parse" in command:
            return paper.PAPER_ENGINE
        assert "--untracked-files=all" in command
        return "?? random.py\n"

    monkeypatch.setattr(paper.subprocess, "check_output", git_output)
    output = tmp_path / "shadowed-engine"
    with pytest.raises(SystemExit):
        paper.main(archived_experiment + ["--out", str(output)])
    assert not output.exists()
