"""Target catalog schema, validation, and assignment resolution."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "targets"
DEFAULT_TARGET_ID = "wealth.skewed-gini-0.5"
MEASUREMENT_BIN_ALIASES = {"age": "age_at_death"}
TARGET_KINDS = {"distribution", "maximize", "minimize"}

# Measurement-only variables with no shipped target keep fixed canonical bins
# so results histograms stay complete. sick_fraction lost its catalog source
# when the disease targets were shelved (2026-08-11) but remains measured.
MEASUREMENT_ONLY_BINS: dict[str, tuple[tuple[float, ...], tuple[float, float]]] = {
    "sick_fraction": (tuple(i / 10 for i in range(11)), (0.0, 1.0)),
    "wellness": (tuple(i / 10 for i in range(11)), (0.0, 1.0)),
}


@dataclass(frozen=True, slots=True)
class Target:
    """One validated distribution or scalar-objective target."""

    id: str
    kind: str
    variable: str
    description: str | None = None
    scope: str | None = None
    support: tuple[float, float] | None = None
    bins: tuple[float, ...] | None = None
    probs: tuple[float, ...] | None = None
    window: int | None = None
    source: str | None = None
    provisional: bool | None = None
    generation: Mapping[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        """Return the pure-data representation sent to players and replays."""

        common = {
            "id": self.id,
            "kind": self.kind,
            "variable": self.variable,
        }
        if self.kind != "distribution":
            assert self.description is not None
            return {**common, "description": self.description}
        assert self.scope is not None
        assert self.support is not None
        assert self.bins is not None
        assert self.probs is not None
        assert self.window is not None
        assert self.source is not None
        assert self.provisional is not None
        assert self.generation is not None
        return {
            **common,
            "scope": self.scope,
            "support": list(self.support),
            "bins": list(self.bins),
            "probs": list(self.probs),
            "window": self.window,
            "source": self.source,
            "provisional": self.provisional,
            "generation": dict(self.generation),
        }


@dataclass(frozen=True, slots=True)
class TargetCatalog:
    """Targets plus the canonical support/binning for every variable."""

    targets: Mapping[str, Target]
    bins_by_variable: Mapping[str, tuple[float, ...]]
    support_by_variable: Mapping[str, tuple[float, float]]

    def get(self, target_id: str) -> Target:
        try:
            return self.targets[target_id]
        except KeyError as error:
            raise ValueError(f'unknown target id "{target_id}"') from error


def load_target_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> TargetCatalog:
    """Load all JSON targets and reject duplicate or inconsistent entries."""

    directory = Path(path)
    targets: dict[str, Target] = {}
    bins_by_variable: dict[str, tuple[float, ...]] = {}
    support_by_variable: dict[str, tuple[float, float]] = {}
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ValueError(f"target catalog contains no JSON files: {directory}")
    for file in files:
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot load target {file}: {error}") from error
        target = parse_target(raw, location=file.name)
        if target.id in targets:
            raise ValueError(f'duplicate target id "{target.id}"')
        if target.kind == "distribution":
            assert target.bins is not None and target.support is not None
            expected_bins = bins_by_variable.setdefault(target.variable, target.bins)
            expected_support = support_by_variable.setdefault(
                target.variable, target.support
            )
            if target.bins != expected_bins or target.support != expected_support:
                raise ValueError(
                    f'target "{target.id}" uses inconsistent support/bins for variable "{target.variable}"'
                )
        targets[target.id] = target
    for variable, source_variable in MEASUREMENT_BIN_ALIASES.items():
        try:
            bins_by_variable[variable] = bins_by_variable[source_variable]
            support_by_variable[variable] = support_by_variable[source_variable]
        except KeyError as error:
            raise ValueError(
                f'measurement variable "{variable}" requires canonical bins for '
                f'"{source_variable}"'
            ) from error
    for variable, (bins, support) in MEASUREMENT_ONLY_BINS.items():
        if variable in bins_by_variable and bins_by_variable[variable] != bins:
            raise ValueError(
                f'target catalog bins for "{variable}" conflict with its '
                f"measurement-only canonical bins"
            )
        bins_by_variable.setdefault(variable, bins)
        support_by_variable.setdefault(variable, support)
    for target in targets.values():
        if target.variable not in bins_by_variable:
            raise ValueError(
                f'target "{target.id}" uses unknown variable "{target.variable}"'
            )
    return TargetCatalog(targets, bins_by_variable, support_by_variable)


def parse_target(raw: object, *, location: str = "target") -> Target:
    """Validate one decoded target object with actionable field errors."""

    if not isinstance(raw, Mapping):
        raise ValueError(f"{location}: target must be an object")
    kind = raw.get("kind", "distribution")
    if not isinstance(kind, str) or kind not in TARGET_KINDS:
        raise ValueError(
            f'{location}.kind must be "distribution", "maximize", or "minimize"'
        )
    if kind != "distribution":
        required = {"id", "kind", "variable", "description"}
        missing = sorted(required - set(raw))
        if missing:
            raise ValueError(f"{location}: missing fields: {', '.join(missing)}")
        unknown = sorted(set(raw) - required)
        if unknown:
            raise ValueError(
                f"{location}: fields not allowed for {kind}: {', '.join(unknown)}"
            )
        return Target(
            id=_nonempty_string(raw["id"], f"{location}.id"),
            kind=kind,
            variable=_nonempty_string(raw["variable"], f"{location}.variable"),
            description=_nonempty_string(raw["description"], f"{location}.description"),
        )
    required = {
        "id",
        "variable",
        "support",
        "bins",
        "probs",
        "window",
        "source",
        "provisional",
        "generation",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"{location}: missing fields: {', '.join(missing)}")
    target_id = _nonempty_string(raw["id"], f"{location}.id")
    variable = _nonempty_string(raw["variable"], f"{location}.variable")
    scope = raw.get("scope", "global")
    if scope not in {"global", "seat"}:
        raise ValueError(f'{location}.scope must be "global" or "seat"')
    support_values = _number_array(raw["support"], f"{location}.support", length=2)
    support = (support_values[0], support_values[1])
    if support[0] >= support[1]:
        raise ValueError(f"{location}.support must be strictly increasing")
    bins = tuple(_number_array(raw["bins"], f"{location}.bins"))
    if len(bins) < 2 or any(left >= right for left, right in zip(bins, bins[1:])):
        raise ValueError(
            f"{location}.bins must contain at least two strictly increasing edges"
        )
    if bins[0] != support[0] or bins[-1] != support[1]:
        raise ValueError(f"{location}.bins must start and end at the declared support")
    probs = tuple(_number_array(raw["probs"], f"{location}.probs"))
    if len(probs) != len(bins) - 1:
        raise ValueError(f"{location}.probs must have exactly len(bins)-1 entries")
    if any(probability < 0 for probability in probs):
        raise ValueError(f"{location}.probs cannot contain negative values")
    if not math.isclose(sum(probs), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{location}.probs must sum to 1")
    window = raw["window"]
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ValueError(f"{location}.window must be a positive integer")
    source = _nonempty_string(raw["source"], f"{location}.source")
    provisional = raw["provisional"]
    if not isinstance(provisional, bool):
        raise ValueError(f"{location}.provisional must be a boolean")
    generation = raw["generation"]
    if not isinstance(generation, Mapping) or not generation.get("description"):
        raise ValueError(
            f"{location}.generation must describe how the histogram was produced"
        )
    return Target(
        id=target_id,
        kind="distribution",
        variable=variable,
        scope=scope,
        support=support,
        bins=bins,
        probs=probs,
        window=window,
        source=source,
        provisional=provisional,
        generation=dict(generation),
    )


def resolve_seat_targets(
    assignments: object,
    *,
    seats: int,
    measurement_window: int,
    catalog: TargetCatalog,
) -> tuple[Target, ...]:
    """Resolve target IDs or inline targets to one effective target per seat."""

    if assignments is None:
        entries: Sequence[object] = [DEFAULT_TARGET_ID] * seats
    elif isinstance(assignments, Sequence) and not isinstance(
        assignments, (str, bytes)
    ):
        entries = assignments
    else:
        raise ValueError("targets must be an array with one assignment per seat")
    # A single-entry array broadcasts to every seat, so a variant keeps one
    # canonical target while the platform varies the episode's seat count
    # (e.g. multi-seat self-play qualification rounds).
    if len(entries) == 1 and seats > 1:
        entries = list(entries) * seats
    if len(entries) != seats:
        raise ValueError("targets must contain one assignment per seat")
    resolved: list[Target] = []
    for seat, entry in enumerate(entries):
        if isinstance(entry, str):
            target = catalog.get(entry)
        else:
            target = parse_target(entry, location=f"targets[{seat}]")
            canonical_bins = catalog.bins_by_variable.get(target.variable)
            canonical_support = catalog.support_by_variable.get(target.variable)
            if canonical_bins is None:
                raise ValueError(
                    f'targets[{seat}] uses unknown variable "{target.variable}"'
                )
            if target.kind == "distribution" and (
                target.bins != canonical_bins or target.support != canonical_support
            ):
                raise ValueError(
                    f"targets[{seat}] does not use the catalog's canonical support/bins"
                )
        resolved.append(
            replace(target, window=measurement_window)
            if target.kind == "distribution"
            else target
        )
    return tuple(resolved)


def _nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _number_array(
    value: object, path: str, *, length: int | None = None
) -> list[float]:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        suffix = f" with {length} entries" if length is not None else ""
        raise ValueError(f"{path} must be an array{suffix}")
    numbers: list[float] = []
    for index, item in enumerate(value):
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
        ):
            raise ValueError(f"{path}[{index}] must be a finite number")
        numbers.append(float(item))
    return numbers
