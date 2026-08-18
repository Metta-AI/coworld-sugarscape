from __future__ import annotations

import json
from pathlib import Path

import pytest

from coworld.scoring import target_scale
from coworld.targets import load_target_catalog, parse_target, resolve_seat_targets


def test_shipped_catalog_is_honest_global_and_provenance_complete() -> None:
    """Catalog invariants that hold regardless of which targets are generated.

    The disease targets were shelved 2026-08-11 (no stable endemic equilibrium
    exists in DTL's parameter space — see docs/TARGETS.md), leaving seven.
    Non-provisional targets must carry real generation provenance (engine-run
    or an empirical dataset recipe); provisional ones must describe their
    parametric placeholder.
    """
    catalog = load_target_catalog()

    assert len(catalog.targets) == 8
    assert not any(target_id.startswith("disease.") for target_id in catalog.targets)
    distributions = [
        target for target in catalog.targets.values() if target.kind == "distribution"
    ]
    assert all(target.scope == "global" for target in distributions)
    for target in distributions:
        assert target.generation.get("description")
        if not target.provisional:
            method = target.generation.get("method")
            assert method in {"engine-run", "hmd-life-table"}
            if method == "engine-run":
                assert target.generation.get("engine_commit")
                assert target.generation.get("seeds", 0) >= 30
    assert (
        catalog.get("wealth.skewed-gini-0.5").bins
        == catalog.get("wealth.egalitarian").bins
    )
    # Shelving the disease targets must not drop sick_fraction from
    # measurement: it keeps measurement-only canonical bins.
    assert "sick_fraction" in catalog.bins_by_variable
    wellness = catalog.get("wellness.max")
    assert wellness.as_dict()["kind"] == "maximize"
    assert set(wellness.as_dict()) == {"id", "kind", "variable", "description"}
    assert catalog.bins_by_variable["wellness"] == tuple(
        index / 10 for index in range(11)
    )


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
    (tmp_path / "one.json").write_text(
        json.dumps({**base, "id": "one"}), encoding="utf-8"
    )
    (tmp_path / "two.json").write_text(
        json.dumps({**base, "id": "two", "bins": [0, 0.5, 2]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="inconsistent support/bins"):
        load_target_catalog(tmp_path)


def test_shipped_target_scales_are_pinned() -> None:
    catalog = load_target_catalog()
    expected = {
        "age-at-death.survivorship": 11.688116881168808,
        "population.carrying-capacity": 100.0,
        "price.equilibrium": 0.25,
        "tribe.convergence": 0.1,
        "tribe.diversity": 0.1,
        "wealth.egalitarian": 25.0,
        "wealth.skewed-gini-0.5": 33.711466666666816,
    }

    assert {
        target_id: target_scale(target.probs, target.bins)
        for target_id, target in catalog.targets.items()
        if target.kind == "distribution"
    } == pytest.approx(expected)


def test_assignments_default_to_global_and_use_effective_measurement_window() -> None:
    catalog = load_target_catalog()
    targets = resolve_seat_targets(None, seats=2, measurement_window=7, catalog=catalog)

    assert [target.id for target in targets] == [
        "wealth.skewed-gini-0.5",
        "wealth.skewed-gini-0.5",
    ]
    assert all(target.scope == "global" and target.window == 7 for target in targets)


def test_distribution_kind_defaults_and_is_serialized_explicitly() -> None:
    target = load_target_catalog().get("wealth.skewed-gini-0.5")
    assert target.kind == "distribution"
    assert target.as_dict()["kind"] == "distribution"


@pytest.mark.parametrize("kind", ["maximize", "minimize"])
def test_objective_target_has_minimal_shape(kind: str) -> None:
    raw = {
        "id": f"example.{kind}",
        "kind": kind,
        "variable": "wellness",
        "description": "test objective",
    }
    assert parse_target(raw).as_dict() == raw


def test_objective_target_rejects_distribution_fields() -> None:
    raw = {
        "id": "example.max",
        "kind": "maximize",
        "variable": "wellness",
        "description": "test objective",
        "bins": [0, 1],
    }
    with pytest.raises(ValueError, match="fields not allowed for maximize: bins"):
        parse_target(raw)


def test_inline_objective_must_name_a_measured_variable() -> None:
    raw = {
        "id": "unknown.max",
        "kind": "maximize",
        "variable": "unknown",
        "description": "test objective",
    }
    with pytest.raises(ValueError, match='unknown variable "unknown"'):
        resolve_seat_targets(
            [raw], seats=1, measurement_window=5, catalog=load_target_catalog()
        )
