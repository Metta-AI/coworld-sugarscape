from __future__ import annotations

import json
from pathlib import Path

import pytest

from coworld.targets import load_target_catalog, resolve_seat_targets


def test_shipped_catalog_has_nine_honest_global_provisional_targets() -> None:
    catalog = load_target_catalog()

    assert len(catalog.targets) == 9
    assert all(target.scope == "global" for target in catalog.targets.values())
    assert all(target.provisional for target in catalog.targets.values())
    assert all(target.generation.get("description") for target in catalog.targets.values())
    assert catalog.get("wealth.skewed-gini-0.5").bins == catalog.get("wealth.egalitarian").bins


def test_catalog_rejects_inconsistent_binning_for_same_variable(tmp_path: Path) -> None:
    base = {
        "variable": "example",
        "scope": "global",
        "support": [0, 2],
        "bins": [0, 1, 2],
        "probs": [0.5, 0.5],
        "window": 2,
        "source": "test",
        "provisional": True,
        "generation": {"description": "test fixture"},
    }
    (tmp_path / "one.json").write_text(json.dumps({**base, "id": "one"}), encoding="utf-8")
    (tmp_path / "two.json").write_text(
        json.dumps({**base, "id": "two", "bins": [0, 0.5, 2]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="inconsistent support/bins"):
        load_target_catalog(tmp_path)


def test_assignments_default_to_global_and_use_effective_measurement_window() -> None:
    catalog = load_target_catalog()
    targets = resolve_seat_targets(None, seats=2, measurement_window=7, catalog=catalog)

    assert [target.id for target in targets] == [
        "wealth.skewed-gini-0.5",
        "wealth.skewed-gini-0.5",
    ]
    assert all(target.scope == "global" and target.window == 7 for target in targets)
