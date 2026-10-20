"""Complete public game/player episodes against retained native study observations."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/research"


def test_native_failure_closes_the_public_episode_without_success_artifacts(tmp_path):
    output = tmp_path / "failed-native-runtime"
    process = subprocess.run(
        [
            sys.executable,
            "tools/research_experiments.py",
            "--variant",
            "paper-mcculloch-4-7",
            "--seeds",
            "0",
            "--out",
            str(output),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONHASHSEED": "0",
            "COWORLD_RESEARCH_PYTHON": sys.executable,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    folder = output / "paper-mcculloch-4-7/0"
    assert process.returncode != 0
    assert "requires the qualified interpreter" in (folder / "game.log").read_text()
    assert not (folder / "results.json").exists()
    assert not (folder / "replay.bin").exists()


def test_mcculloch_public_episodes_reproduce_released_model_trajectories(
    tmp_path: Path,
) -> None:
    output = tmp_path / "mcculloch"
    subprocess.run(
        [
            sys.executable,
            "tools/research_experiments.py",
            "--variant",
            "paper-mcculloch-1-1",
            "--variant",
            "paper-mcculloch-2-10",
            "--variant",
            "paper-mcculloch-4-7",
            "--seeds",
            "0",
            "--out",
            str(output),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=True,
        timeout=180,
    )
    targets = json.loads((FIXTURES / "mcculloch-populations.json").read_bytes())
    for target in targets["runs"]:
        name = f"paper-mcculloch-{target['max_metabolism']}-{target['max_vision']}"
        folder = output / name / "0"
        replay = json.loads(zlib.decompress((folder / "replay.bin").read_bytes()))
        assert [f["measurements"]["population"] for f in replay["frames"]] == target[
            "population"
        ]
        assert [f["timestep"] for f in replay["frames"]] == list(range(101))
        assert replay["details"]["duration_override"] is False
        assert json.loads((folder / "results.json").read_bytes())["scores"] == [0]


def test_carrella_and_constructive_witnesses_complete_through_player_protocol(
    tmp_path: Path,
) -> None:
    output = tmp_path / "other-studies"
    subprocess.run(
        [
            sys.executable,
            "tools/research_experiments.py",
            "--variant",
            "paper-carrella",
            "--variant",
            "paper-izquierdo-return-5",
            "--variant",
            "paper-izquierdo-return-6",
            "--seeds",
            "123",
            "--out",
            str(output),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=True,
        timeout=240,
    )
    folder = output / "paper-carrella/123"
    replay = json.loads(zlib.decompress((folder / "replay.bin").read_bytes()))
    with (FIXTURES / "carrella-seed123.csv").open() as stream:
        targets = list(csv.DictReader(stream))
    assert len(targets) == len(replay["frames"]) == 501
    for target, frame in zip(targets, replay["frames"], strict=True):
        actual = frame["measurements"]
        assert actual["population"] == int(target["population"])
        assert actual["native_tick"] == int(target["tick"])
        assert actual["utility_gini"] == float(target["gini"])
        assert actual["trade_count"] == int(target["trade_count"])
        assert actual["mean_price"] == float(target["mean_price"])
        assert sum(frame["sugar"]) == int(target["landscape_sugar"])
        assert sum(frame["spice"]) == int(target["landscape_spice"])
    for period in [5, 6]:
        path = output / f"paper-izquierdo-return-{period}/123/replay.bin"
        witness = json.loads(zlib.decompress(path.read_bytes()))
        initial, final = (
            witness["frames"][0]["measurements"],
            witness["frames"][-1]["measurements"],
        )
        assert len(witness["frames"]) == period + 1
        assert (
            initial["formal_state_sha256"]
            == final["formal_state_sha256"]
            == "b265f3e961cde1a5fff6d7afefce3eef132e126c2c6e774fe835e5b326b96bac"
        )
        assert final["births"] == 250 and final["harvest"] == 0
