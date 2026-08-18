"""Rolling global and per-seat outcome measurement."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .scoring import (
    AgentWellnessMean,
    Histogram,
    WellnessScore,
    make_histogram,
    score_wellness,
)
from .targets import TargetCatalog

VARIABLES = (
    "wealth",
    "age",
    "population",
    "age_at_death",
    "majority_tribe_share",
    "sick_fraction",
    "mean_trade_price",
    "wellness",
)


@dataclass(frozen=True, slots=True)
class AgentWellnessSample:
    seat: int
    wellness: float
    components: tuple[float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class TickMeasurements:
    global_values: Mapping[str, tuple[float, ...]]
    seat_values: tuple[Mapping[str, tuple[float, ...]], ...]
    wellness_by_agent: Mapping[int, AgentWellnessSample]


class RollingMeasurements:
    """Retain only the final W ticks while pooling samples within that window."""

    def __init__(self, seats: int, window: int, catalog: TargetCatalog) -> None:
        self.seats = seats
        self.window = window
        self.catalog = catalog
        missing = set(VARIABLES) - set(catalog.bins_by_variable)
        if missing:
            raise ValueError(
                f"target catalog has no canonical bins for: {', '.join(sorted(missing))}"
            )
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
        by_seat = [
            [agent for agent in agents if agent.seat == seat]
            for seat in range(self.seats)
        ]
        global_values = self._values_for_agents(agents, self._pending_global_deaths)
        global_values["population"] = (float(len(agents)),)
        seat_values: list[Mapping[str, tuple[float, ...]]] = []
        for seat, seat_agents in enumerate(by_seat):
            values = self._values_for_agents(
                seat_agents, self._pending_seat_deaths[seat]
            )
            values["population"] = (float(len(seat_agents)),)
            seat_values.append(values)
        wellness_by_agent = {
            agent.ID: AgentWellnessSample(
                seat=agent.seat,
                wellness=_normalized_wellness(agent.happiness),
                components=(
                    float(agent.healthHappiness),
                    float(agent.conflictHappiness),
                    float(agent.socialHappiness),
                    float(agent.familyHappiness),
                    float(agent.wealthHappiness),
                ),
            )
            for agent in agents
        }
        self._ticks.append(
            TickMeasurements(global_values, tuple(seat_values), wellness_by_agent)
        )
        self._pending_global_deaths.clear()
        for deaths in self._pending_seat_deaths:
            deaths.clear()

    def histogram(
        self, variable: str, *, scope: str, seat: int | None = None
    ) -> Histogram:
        """Build a normalized histogram from the retained tick samples."""

        if variable not in self.catalog.bins_by_variable:
            raise ValueError(f'unknown measured variable "{variable}"')
        if scope == "seat" and (seat is None or not 0 <= seat < self.seats):
            raise ValueError("seat scope requires a valid seat")
        if scope not in {"global", "seat"}:
            raise ValueError('scope must be "global" or "seat"')
        samples: list[float] = []
        if variable == "wellness":
            means = self.wellness_means(seat=seat if scope == "seat" else None)
            return make_histogram(
                (agent.wellness for agent in means),
                self.catalog.bins_by_variable[variable],
            )
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
                    variable: self.histogram(
                        variable, scope="seat", seat=seat
                    ).as_dict()
                    for variable in VARIABLES
                },
            }
            for seat in range(self.seats)
        ]
        return {"global": global_histograms, "by_seat": by_seat}

    def wellness_means(
        self, *, seat: int | None = None, survivor_ids: set[int] | None = None
    ) -> tuple[AgentWellnessMean, ...]:
        """Return one retained-window mean per observed, optionally surviving agent."""
        if seat is not None and not 0 <= seat < self.seats:
            raise ValueError("seat must be valid")
        samples: dict[int, list[AgentWellnessSample]] = {}
        for tick in self._ticks:
            for agent_id, sample in tick.wellness_by_agent.items():
                if seat is not None and sample.seat != seat:
                    continue
                if survivor_ids is not None and agent_id not in survivor_ids:
                    continue
                samples.setdefault(agent_id, []).append(sample)
        means = []
        for agent_id in sorted(samples):
            agent_samples = samples[agent_id]
            count = len(agent_samples)
            means.append(
                AgentWellnessMean(
                    agent_id=agent_id,
                    seat=agent_samples[-1].seat,
                    wellness=sum(sample.wellness for sample in agent_samples) / count,
                    components=tuple(
                        sum(sample.components[index] for sample in agent_samples)
                        / count
                        for index in range(5)
                    ),
                )
            )
        return tuple(means)

    def wellness_summary(
        self, living_agents: Iterable[Any], *, seat: int
    ) -> WellnessScore:
        """Score the retained means for one seat's agents alive at this instant."""
        survivor_ids = {agent.ID for agent in living_agents if agent.seat == seat}
        return score_wellness(self.wellness_means(seat=seat, survivor_ids=survivor_ids))

    @staticmethod
    def _values_for_agents(
        agents: list[Any], deaths: list[float]
    ) -> dict[str, tuple[float, ...]]:
        wealth = tuple(float(agent.sugar + agent.spice) for agent in agents)
        ages = tuple(float(agent.age) for agent in agents)
        if agents:
            tribes = Counter(agent.tribe for agent in agents)
            majority_share = (max(tribes.values()) / len(agents),)
            sick_fraction = (
                sum(1 for agent in agents if agent.isSick()) / len(agents),
            )
            traders = [agent for agent in agents if agent.tradeVolume > 0]
            mean_price = (
                sum(max(agent.spicePrice, agent.sugarPrice) for agent in traders)
                / len(traders)
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


def _normalized_wellness(happiness: float) -> float:
    """Map DTL composite happiness's [-5, 5] contract into [0, 1]."""
    return min(1.0, max(0.0, (float(happiness) + 5.0) / 10.0))
