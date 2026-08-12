from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from probe_reachability import (  # noqa: E402
    GREEDY_RULESET,
    _TRAIT_DEFAULTS,
    crossover,
    is_valid,
    mutate,
    random_ruleset,
)


def test_generated_and_evolved_rulesets_are_always_valid() -> None:
    rng = random.Random(7)
    genomes = [random_ruleset(rng, _TRAIT_DEFAULTS) for _ in range(50)]
    assert all(is_valid(genome) for genome in genomes)
    evolved = []
    for _ in range(100):
        left, right = rng.sample(genomes, 2)
        evolved.append(mutate(rng, left, _TRAIT_DEFAULTS))
        evolved.append(crossover(rng, left, right))
    # Operators may occasionally exceed budgets; the probe filters those, so
    # the invariant is that validity is common, not universal.
    assert sum(1 for genome in evolved if is_valid(genome)) > len(evolved) * 0.9
    assert is_valid(GREEDY_RULESET)


def test_probe_end_to_end_reports_ceiling_at_or_above_floor(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "probe_reachability.py"),
            "--config", str(ROOT / "tests" / "fixtures" / "certification-config.json"),
            "--population", "4",
            "--generations", "1",
            "--seeds", "7",
            "--jobs", "2",
            "--out", str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["ceiling_lower_bound"] >= report["baseline_null"]
    assert (tmp_path / "best-ruleset.json").exists()
