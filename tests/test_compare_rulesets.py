from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compare_rulesets", ROOT / "tools" / "compare_rulesets.py")
assert SPEC is not None and SPEC.loader is not None
comparison = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comparison
SPEC.loader.exec_module(comparison)


def test_identical_rulesets_have_zero_paired_deltas_and_identical_replays(
    tiny_episode_config, tmp_path, monkeypatch
):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    config = {**tiny_episode_config, "seats": 1, "targets": ["wellness.max"]}
    baseline = comparison.choose_ruleset({"id": "wellness.max"})
    first = tmp_path / "first"
    second = tmp_path / "second"
    report = comparison.compare_rulesets(config, baseline, [17, 18], first)
    assert report == comparison.compare_rulesets(config, baseline, [17, 18], second)
    for metric in report["metrics"].values():
        assert metric["paired_delta_mean"] == 0
        assert metric["paired_delta_stdev"] == 0
    for seed in (17, 18):
        assert (first / str(seed) / "baseline.replay").read_bytes() == (
            first / str(seed) / "candidate.replay"
        ).read_bytes()
        assert (first / str(seed) / "candidate.results.json").read_bytes() == (
            second / str(seed) / "candidate.results.json"
        ).read_bytes()
        assert json.loads((first / str(seed) / "config.json").read_text())["seed"] == seed
    with pytest.raises(FileExistsError):
        comparison.compare_rulesets(config, baseline, [17], first)


@pytest.mark.parametrize("seeds", [[], [-1], [True], [1, 1]])
def test_invalid_seed_samples_rejected_before_writing(seeds, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    with pytest.raises(ValueError, match="seeds"):
        comparison.compare_rulesets({}, {}, seeds, tmp_path / "results")
    assert not (tmp_path / "results").exists()


def test_requires_fixed_hash_seed(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    with pytest.raises(ValueError, match="PYTHONHASHSEED"):
        comparison.compare_rulesets({}, {}, [1], tmp_path / "results")


def test_cli_records_provenance_and_overrides_scenario_duration(tmp_path):
    import os
    import subprocess

    output = tmp_path / "experiment"
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "compare_rulesets.py"),
         "--variant", "solo-ladder", "--ruleset", str(ROOT / "rulesets" / "worked-example.json"),
         "--seeds", "17", "--timesteps", "2", "--out", str(output)],
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["variant"] == "solo-ladder"
    assert len(provenance["upstream_commit"]) == 40
    assert "src/coworld/episode.py" in provenance["source_sha256"]
    assert "src/sugarscape/config.json" in provenance["source_sha256"]
    config = json.loads((output / "17" / "config.json").read_text())
    assert config["timesteps"] == 2
    assert config["scenario_index"] == 17
    for arm in ("baseline", "candidate"):
        result = json.loads((output / "17" / f"{arm}.results.json").read_text())
        assert result["timesteps_completed"] == 2
    report = json.loads((output / "comparison.json").read_text())
    assert report["metrics"]["score.match_mean"]["paired_delta_stdev"] is None
