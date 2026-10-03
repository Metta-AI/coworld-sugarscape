from __future__ import annotations

import json
from pathlib import Path

import pytest

from coworld.config import resolve_episode_config
from coworld.episode import run_episode
from coworld.server import SugarscapeServer
from players.baseline.player import choose_ruleset
from tools.qualify_game_image import oracle


@pytest.mark.parametrize("corrupt", [False, True])
def test_image_oracle_checks_saved_results_and_complete_replay(
    tmp_path: Path, tiny_episode_config: dict[str, object], corrupt: bool
) -> None:
    config = resolve_episode_config(
        {
            **tiny_episode_config,
            "seats": 1,
            "tokens": ["local-test"],
            "players": [{"name": "baseline"}],
            "targets": ["tribe.diversity"],
            "measurement_window": 2,
        }
    )
    ruleset = choose_ruleset(
        SugarscapeServer(config, "unused", "unused")._observation(0)["target"]
    )
    results, replay, _ = run_episode(
        config, [ruleset], submitted=[True], emit_timing_logs=False
    )
    if corrupt:
        results["scores"][0] += 1
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "results.json").write_text(json.dumps(results))
    (tmp_path / "replay.bin").write_bytes(replay)
    if corrupt:
        with pytest.raises(AssertionError):
            oracle(tmp_path)
        assert not (tmp_path / "oracle.json").exists()
    else:
        oracle(tmp_path)
        assert json.loads((tmp_path / "oracle.json").read_text())["ticks"] == 4
