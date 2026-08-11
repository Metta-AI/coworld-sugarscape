from __future__ import annotations

from dataclasses import dataclass

from coworld.measurement import RollingMeasurements, VARIABLES
from coworld.targets import load_target_catalog


@dataclass
class FakeAgent:
    seat: int
    sugar: float
    spice: float
    age: int = 20
    tribe: int = 0
    sick: bool = False
    tradeVolume: float = 0
    spicePrice: float = 0
    sugarPrice: float = 0

    def isSick(self) -> bool:
        return self.sick


@dataclass
class FakeWorld:
    agents: list[FakeAgent]


def test_final_window_pools_agents_and_retains_per_tick_population() -> None:
    measurement = RollingMeasurements(2, 2, load_target_catalog())
    measurement.record_tick(
        FakeWorld([FakeAgent(0, 10, 10, age=10), FakeAgent(1, 20, 20, age=20)])
    )
    measurement.record_tick(FakeWorld([FakeAgent(0, 30, 30, age=30)]))
    measurement.record_tick(
        FakeWorld([FakeAgent(1, 40, 40, age=40), FakeAgent(1, 50, 50, age=50)])
    )

    global_wealth = measurement.histogram("wealth", scope="global")
    global_age = measurement.histogram("age", scope="global")
    seat_zero_wealth = measurement.histogram("wealth", scope="seat", seat=0)
    seat_one_age = measurement.histogram("age", scope="seat", seat=1)
    seat_zero_population = measurement.histogram("population", scope="seat", seat=0)

    assert global_wealth.sample_count == 3
    assert global_age.sample_count == 3
    assert seat_zero_wealth.sample_count == 1
    assert seat_one_age.sample_count == 2
    assert seat_zero_population.sample_count == 2


def test_living_age_uses_age_at_death_canonical_support_and_bins() -> None:
    catalog = load_target_catalog()

    assert "age" not in {target.variable for target in catalog.targets.values()}
    assert catalog.support_by_variable["age"] == catalog.support_by_variable["age_at_death"]
    assert catalog.bins_by_variable["age"] == catalog.bins_by_variable["age_at_death"]


def test_age_at_death_events_follow_the_same_rolling_tick_window() -> None:
    measurement = RollingMeasurements(2, 2, load_target_catalog())
    death = FakeAgent(1, 0, 0, age=73)
    measurement.record_deaths([death])
    measurement.record_tick(FakeWorld([]))
    assert measurement.histogram("age_at_death", scope="global").sample_count == 1
    assert measurement.histogram("age_at_death", scope="seat", seat=1).sample_count == 1

    measurement.record_tick(FakeWorld([]))
    measurement.record_tick(FakeWorld([]))
    assert measurement.histogram("age_at_death", scope="global").empty


def test_all_histograms_contains_every_variable_globally_and_per_seat() -> None:
    measurement = RollingMeasurements(2, 2, load_target_catalog())
    measurement.record_tick(FakeWorld([FakeAgent(0, 10, 10, tribe=1, sick=True)]))
    histograms = measurement.all_histograms()

    assert set(histograms["global"]) == set(VARIABLES)
    assert [entry["seat"] for entry in histograms["by_seat"]] == [0, 1]
    assert all(set(entry["variables"]) == set(VARIABLES) for entry in histograms["by_seat"])
