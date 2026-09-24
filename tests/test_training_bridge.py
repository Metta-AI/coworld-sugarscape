"""Complete-game checks for the game-owned training transport."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.training_bridge import TrainingSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["choice", "text"])
def test_training_session_completes_real_certification_game(mode: str) -> None:
    session = TrainingSession("certification", mode, None)
    first = session.reset({"seed": "training-proof", "players": 2})
    assert first["game"] == "sugarscape"
    assert "seed" not in first["semantic_view"]["config"]
    assert "scenario_pool" not in first["semantic_view"]["config"]
    assert (first["typed_question"] is not None) == (mode == "choice")

    if mode == "choice":
        encoding = session.encode()
        assert len(encoding["values"]) == 66
        assert len(encoding["actions"]) == 7

    for seat in range(2):
        response = session.teacher()["response"]
        result = session.step({"decision_id": seat, "response": response})
        assert result["kind"] == "accepted"
    terminal = result["observation"]
    assert terminal["kind"] == "terminal"
    assert len(terminal["scores"]) == 2
    assert all(score >= 0 for score in terminal["scores"].values())
    assert terminal["utilities"] == terminal["scores"]


def test_jsonl_bridge_reuses_process_across_seeds() -> None:
    process = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/training_bridge.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    for seed in ("alpha", "beta"):
        process.stdin.write(
            json.dumps({"kind": "reset", "seed": seed, "players": 2}) + "\n"
        )
        process.stdin.flush()
        observation = json.loads(process.stdout.readline())
        assert observation["kind"] == "decision"
        assert observation["seat"] == 0
        assert observation["decision_id"] == 0
    process.stdin.close()
    assert process.wait(timeout=5) == 0


def test_commonwealth_utility_keeps_wellness_signal_bounded() -> None:
    session = TrainingSession("commonwealth", "choice", 50)
    observation = session.reset({"seed": "commonwealth-proof", "players": 1})
    result = session.step(
        {
            "decision_id": observation["decision_id"],
            "response": session.teacher()["response"],
        }
    )
    terminal = result["observation"]
    assert terminal["scores"][0] > 1
    assert 0 < terminal["utilities"][0] < 0.1
