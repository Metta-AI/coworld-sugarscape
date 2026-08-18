from __future__ import annotations

from dataclasses import dataclass

import pytest

from coworld.measurement import VARIABLES, RollingMeasurements
from coworld.targets import load_target_catalog


@dataclass
class FakeAgent:
    seat: int
    sugar: float
    spice: float
    ID: int = 0
    age: int = 20
    tribe: int = 0
    sick: bool = False
    tradeVolume: float = 0
    spicePrice: float = 0
    sugarPrice: float = 0
    happiness: float = 0
    healthHappiness: float = 0
    conflictHappiness: float = 0
    socialHappiness: float = 0
    familyHappiness: float = 0
    wealthHappiness: float = 0

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
    assert (
        catalog.support_by_variable["age"]
        == catalog.support_by_variable["age_at_death"]
    )
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
    assert all(
        set(entry["variables"]) == set(VARIABLES) for entry in histograms["by_seat"]
    )


def test_wellness_normalization_clamps_bounds_including_depressed_values() -> None:
    measurement = RollingMeasurements(1, 1, load_target_catalog())
    measurement.record_tick(
        FakeWorld(
            [
                FakeAgent(0, 0, 0, ID=1, happiness=-5),
                FakeAgent(0, 0, 0, ID=2, happiness=0),
                FakeAgent(0, 0, 0, ID=3, happiness=5),
                FakeAgent(0, 0, 0, ID=4, happiness=-3 * 0.5763 - 2),
                FakeAgent(0, 0, 0, ID=5, happiness=3 * 0.5763 + 2),
                FakeAgent(0, 0, 0, ID=6, happiness=-100),
                FakeAgent(0, 0, 0, ID=7, happiness=100),
            ]
        )
    )
    means = {agent.agent_id: agent.wellness for agent in measurement.wellness_means()}
    assert means[1] == 0 and means[2] == 0.5 and means[3] == 1
    assert means[4] == pytest.approx(0.12711)
    assert means[5] == pytest.approx(0.87289)
    assert means[6] == 0 and means[7] == 1


def test_wellness_means_are_per_agent_and_filter_final_survivors() -> None:
    measurement = RollingMeasurements(1, 3, load_target_catalog())
    always = FakeAgent(
        0, 0, 0, ID=1, happiness=-5, healthHappiness=-1, conflictHappiness=-1
    )
    dies = FakeAgent(0, 0, 0, ID=2, happiness=5, healthHappiness=1)
    born = FakeAgent(0, 0, 0, ID=3, happiness=5, healthHappiness=1, familyHappiness=0.5)
    measurement.record_tick(FakeWorld([always, dies]))
    always.happiness = 5
    always.healthHappiness = 1
    always.conflictHappiness = 1
    measurement.record_tick(FakeWorld([always]))
    measurement.record_tick(FakeWorld([always, born]))
    all_means = {agent.agent_id: agent for agent in measurement.wellness_means()}
    assert all_means[1].wellness == pytest.approx(2 / 3)
    assert all_means[2].wellness == 1 and all_means[3].wellness == 1
    summary = measurement.wellness_summary([always, born], seat=0)
    assert summary.survivor_count == 2
    assert summary.score == pytest.approx(5 / 3)
    assert summary.mean_wellness == pytest.approx(5 / 6)
    assert summary.component_dict() == pytest.approx(
        {"health": 2 / 3, "conflict": 1 / 6, "social": 0, "family": 0.25, "wealth": 0}
    )
    assert measurement.histogram("wellness", scope="global").sample_count == 3


def test_wellness_window_evicts_old_samples_and_handles_extinction() -> None:
    measurement = RollingMeasurements(2, 2, load_target_catalog())
    agent = FakeAgent(1, 0, 0, ID=9, happiness=-5)
    measurement.record_tick(FakeWorld([agent]))
    agent.happiness = 5
    measurement.record_tick(FakeWorld([agent]))
    measurement.record_tick(FakeWorld([]))
    assert measurement.wellness_means(seat=1)[0].wellness == 1
    summary = measurement.wellness_summary([], seat=1)
    assert summary.score == 0 and summary.survivor_count == 0
