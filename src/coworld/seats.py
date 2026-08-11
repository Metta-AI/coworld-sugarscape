"""Seat ownership and trait-range invariants for Sugarscape agents."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from .ruleset import CompiledRuleset, TRAIT_NAMES


@dataclass(frozen=True, slots=True)
class TraitRange:
    """Inclusive bounds for one player-controlled trait."""

    minimum: float
    maximum: float

    def clamp(self, value: float) -> float:
        return min(self.maximum, max(self.minimum, value))


def parse_trait_ranges(raw: Mapping[str, object] | None) -> dict[str, TraitRange]:
    """Validate and normalize the four variant-controlled trait ranges."""

    if raw is not None and not isinstance(raw, Mapping):
        raise ValueError("trait_ranges must be an object")
    source = raw if raw is not None else {name: [0.0, 1.0] for name in TRAIT_NAMES}
    ranges: dict[str, TraitRange] = {}
    unknown = set(source) - set(TRAIT_NAMES)
    if unknown:
        raise ValueError(f"unknown trait_ranges entries: {', '.join(sorted(unknown))}")
    for name in TRAIT_NAMES:
        bounds = source.get(name)
        if not isinstance(bounds, Sequence) or isinstance(bounds, (str, bytes)) or len(bounds) != 2:
            raise ValueError(f"trait_ranges.{name} must be a two-number array")
        low, high = bounds
        if isinstance(low, bool) or not isinstance(low, (int, float)):
            raise ValueError(f"trait_ranges.{name}[0] must be a number")
        if isinstance(high, bool) or not isinstance(high, (int, float)):
            raise ValueError(f"trait_ranges.{name}[1] must be a number")
        if not math.isfinite(low) or not math.isfinite(high):
            raise ValueError(f"trait_ranges.{name} bounds must be finite")
        if low > high:
            raise ValueError(f"trait_ranges.{name} minimum must not exceed maximum")
        ranges[name] = TraitRange(float(low), float(high))
    return ranges


class SeatManager:
    """Assign seats without consuming the DTL simulation random stream."""

    def __init__(
        self,
        seat_count: int,
        rulesets: Sequence[CompiledRuleset],
        trait_ranges: Mapping[str, TraitRange],
    ) -> None:
        if seat_count <= 0:
            raise ValueError("seats must be a positive integer")
        if len(rulesets) != seat_count:
            raise ValueError("one compiled ruleset is required for each seat")
        self.seat_count = seat_count
        self.rulesets = tuple(rulesets)
        self.trait_ranges = dict(trait_ranges)
        self._initial_assignments = 0
        self._replacement_seats: deque[int] = deque()

    def seat_for_spawn(self, configuration: Mapping[str, object]) -> int:
        """Resolve explicit birth, queued replacement, or round-robin ownership."""

        explicit = configuration.get("_coworld_seat")
        if explicit is not None:
            return self._validate_seat(explicit)
        if self._replacement_seats:
            return self._replacement_seats.popleft()
        seat = self._initial_assignments % self.seat_count
        self._initial_assignments += 1
        return seat

    def queue_replacements(self, dead_agents: Sequence[object], count: int) -> None:
        """Pair replacements with the first K deaths in DTL removal order."""

        if self._replacement_seats:
            raise RuntimeError("replacement seat queue was not fully consumed")
        if count > len(dead_agents):
            raise RuntimeError("DTL requested more replacements than current-tick deaths")
        for dead_agent in dead_agents[:count]:
            self._replacement_seats.append(self._validate_seat(getattr(dead_agent, "seat")))

    def ruleset(self, seat: int) -> CompiledRuleset:
        return self.rulesets[self._validate_seat(seat)]

    def _validate_seat(self, seat: object) -> int:
        if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < self.seat_count:
            raise ValueError(f"seat must be an integer in [0, {self.seat_count - 1}]")
        return seat
