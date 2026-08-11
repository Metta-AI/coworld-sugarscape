from __future__ import annotations

from pathlib import Path

from coworld.ruleset import FEATURE_NAMES


ROOT = Path(__file__).resolve().parents[1]


def test_rules_reference_lists_every_compiler_feature_and_frozen_limit() -> None:
    rules = (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8")
    for feature in FEATURE_NAMES:
        assert f"`{feature}`" in rules
    assert "32,768 bytes" in rules
    assert "256" in rules
    assert "Maximum expression depth: 16" in rules


def test_rules_reference_freezes_accepted_semantics() -> None:
    rules = (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8")
    assert "clamps `base` to `max(base, 0)`" in rules
    assert "clamps the\n  exponent into `[-8, 8]`" in rules
    assert "Completed DTL statistic from tick T-1" in rules
    assert "Left-to-right, so `[\"-\",10,3,2]` is `5`" in rules
    assert "canonical results\npayload with `timings` removed" in rules
