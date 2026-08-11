"""Rolling global and per-seat outcome measurement."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .scoring import Histogram, make_histogram
from .targets import TargetCatalog


VARIABLES = (
    "wealth",
    "age",
    "population",
    "age_at_death",
    "majority_tribe_share",
    "sick_fraction",
    "mean_trade_price",
)


@dataclass(frozen=True, slots=True)
class TickMeasurements:
    global_values: Mapping[str, tuple[float, ...]]
    seat_values: tuple[Mapping[str, tuple[float, ...]], ...]


class RollingMeasurements:
    """Retain only the final W ticks while pooling samples within that window."""

    def __init__(self, seats: int, window: int, catalog: TargetCatalog) -> None:
        self.seats = seats
        self.window = window
        self.catalog = catalog
        missing = set(VARIABLES) - set(catalog.bins_by_variable)
        if missing:
            raise ValueError(f"target catalog has no canonical bins for: {', '.join(sorted(missing))}")
        self._ticks: deque[TickMeasurements] = deque(maxlen=window)
        self._pending_global_deaths: list[float] = []
        self._pending_seat_deaths: list[list[float]] = [[] for _ in range(seats)]

    def record_deaths(self, dead_agents: Iterable[Any]) -> None:
        """Capture age-at-death events before DTL clears its death list."""

        for agent in dead_agents:
            age = float(agent.age)
            self._pending_global_deaths.append(age)
            self._pending_seat_deaths[agent.seat].append(age)

    def record_tick(self, world: Any) -> None:
        """Measure all variables after one completed DTL tick."""

        agents = list(world.agents)
        by_seat = [[agent for agent in agents if agent.seat == seat] for seat in range(self.seats)]
        global_values = self._values_for_agents(agents, self._pending_global_deaths)
        global_values["population"] = (float(len(agents)),)
        seat_values: list[Mapping[str, tuple[float, ...]]] = []
        for seat, seat_agents in enumerate(by_seat):
            values = self._values_for_agents(seat_agents, self._pending_seat_deaths[seat])
            values["population"] = (float(len(seat_agents)),)
            seat_values.append(values)
        self._ticks.append(TickMeasurements(global_values, tuple(seat_values)))
        self._pending_global_deaths.clear()
        for deaths in self._pending_seat_deaths:
            deaths.clear()

    def histogram(self, variable: str, *, scope: str, seat: int | None = None) -> Histogram:
        """Build a normalized histogram from the retained tick samples."""

        if variable not in self.catalog.bins_by_variable:
            raise ValueError(f'unknown measured variable "{variable}"')
        if scope == "seat" and (seat is None or not 0 <= seat < self.seats):
            raise ValueError("seat scope requires a valid seat")
        if scope not in {"global", "seat"}:
            raise ValueError('scope must be "global" or "seat"')
        samples: list[float] = []
        for tick in self._ticks:
            if scope == "global":
                values = tick.global_values[variable]
            else:
                assert seat is not None
                values = tick.seat_values[seat][variable]
            samples.extend(values)
        return make_histogram(samples, self.catalog.bins_by_variable[variable])

    def all_histograms(self) -> dict[str, object]:
        """Return every canonical variable globally and for every seat."""

        global_histograms = {
            variable: self.histogram(variable, scope="global").as_dict()
            for variable in VARIABLES
        }
        by_seat = [
            {
                "seat": seat,
                "variables": {
                    variable: self.histogram(variable, scope="seat", seat=seat).as_dict()
                    for variable in VARIABLES
                },
            }
            for seat in range(self.seats)
        ]
        return {"global": global_histograms, "by_seat": by_seat}

    @staticmethod
    def _values_for_agents(agents: list[Any], deaths: list[float]) -> dict[str, tuple[float, ...]]:
        wealth = tuple(float(agent.sugar + agent.spice) for agent in agents)
        ages = tuple(float(agent.age) for agent in agents)
        if agents:
            tribes = Counter(agent.tribe for agent in agents)
            majority_share = (max(tribes.values()) / len(agents),)
            sick_fraction = (sum(1 for agent in agents if agent.isSick()) / len(agents),)
            traders = [agent for agent in agents if agent.tradeVolume > 0]
            mean_price = (
                sum(max(agent.spicePrice, agent.sugarPrice) for agent in traders) / len(traders)
                if traders
                else 0.0
            )
            trade_price = (float(mean_price),)
        else:
            majority_share = ()
            sick_fraction = ()
            trade_price = ()
        return {
            "wealth": wealth,
            "age": ages,
            "age_at_death": tuple(deaths),
            "majority_tribe_share": majority_share,
            "sick_fraction": sick_fraction,
            "mean_trade_price": trade_price,
        }
