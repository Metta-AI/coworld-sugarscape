from __future__ import annotations

from copy import copy
from types import SimpleNamespace

import pytest

from coworld import dtl
from coworld.config import build_dtl_config, resolve_episode_config
from coworld.disease import Disease, ZombieVirus
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape

MODIFIERS = {
    "aggression": "aggressionFactorModifier",
    "fertility": "fertilityFactorModifier",
    "friendliness": "friendlinessModifier",
    "happiness": "happinessModifier",
    "movement": "movementModifier",
    "spiceMetabolism": "spiceMetabolismModifier",
    "sugarMetabolism": "sugarMetabolismModifier",
    "vision": "visionModifier",
}


@pytest.fixture
def agent():
    value = dtl.Agent.__new__(dtl.Agent)
    for attribute in MODIFIERS.values():
        setattr(value, attribute, 0)
    value.cell = SimpleNamespace(neighbors={})
    value.timestep = 0
    value.diseases = []
    return value


@pytest.fixture
def illness():
    config = {name + "Penalty": index + 1 for index, name in enumerate(MODIFIERS)}
    config.update(incubationPeriod=0, startTimestep=0, tags=None, transmissionChance=1)
    return Disease(17, config)


def test_active_disease_does_not_stack_and_recovery_clears_every_modifier(
    agent, illness
):
    illness.infect(agent)
    illness.trigger(agent)
    agent.diseases = [{"disease": illness, "caught": 0, "incubation": 0}]
    for tick in [1, 2, 3]:
        agent.timestep = tick
        dtl.Agent.doDisease(agent)
        for name, attribute in MODIFIERS.items():
            assert getattr(agent, attribute) == getattr(illness, name + "Penalty")
    illness.recover(agent)
    assert illness.infected == [] and illness._active_agents == set()
    assert all(getattr(agent, attribute) == 0 for attribute in MODIFIERS.values())


def test_incubating_death_does_not_remove_unapplied_penalties(agent, illness):
    illness.infect(agent)
    illness.recover(agent)
    assert illness.infected == [] and illness._active_agents == set()
    assert all(getattr(agent, attribute) == 0 for attribute in MODIFIERS.values())


def test_reinfection_applies_once_again(agent, illness):
    for _ in range(2):
        illness.infect(agent)
        illness.trigger(agent)
        illness.trigger(agent)
        assert agent.sugarMetabolismModifier == illness.sugarMetabolismPenalty
        illness.recover(agent)
        assert agent.sugarMetabolismModifier == 0


def test_zombie_incubation_and_irrecoverable_active_phase(agent):
    illness = ZombieVirus("zombieVirus", {})
    illness.infect(agent)
    agent.diseases = [{"disease": illness, "caught": 0, "incubation": 3}]
    for tick in range(1, 7):
        agent.timestep = tick
        dtl.Agent.doDisease(agent)
        assert agent.sugarMetabolismModifier == (0 if tick < 3 else -10)
        assert agent.aggressionFactorModifier == (0 if tick < 3 else 100000)
    illness.recover(agent)
    assert agent.sugarMetabolismModifier == agent.aggressionFactorModifier == 0
    assert illness.infected == [] and illness._active_agents == set()


def test_factory_scope_restores_upstream_classes_on_failure():
    previous = dtl.condition_module.Disease, dtl.condition_module.ZombieVirus
    with (
        pytest.raises(RuntimeError, match="fixture failure"),
        dtl.disease_classes(Disease, ZombieVirus),
    ):
        assert dtl.condition_module.Disease is Disease
        raise RuntimeError("fixture failure")
    assert (dtl.condition_module.Disease, dtl.condition_module.ZombieVirus) == previous


def test_real_world_modifiers_equal_current_active_infections(tiny_episode_config):
    config = {
        **tiny_episode_config,
        "seats": 1,
        "startingAgents": 24,
        "startingDiseases": 4,
        "startingDiseasesPerAgent": [1, 2],
        "diseaseSugarMetabolismPenalty": [1, 3],
        "diseaseSpiceMetabolismPenalty": [1, 3],
        "diseaseTagStringLength": [3, 5],
        "agentImmuneSystemLength": 15,
        "timesteps": 20,
    }
    resolved = resolve_episode_config(config)
    world = CoworldSugarscape(
        build_dtl_config(resolved),
        [compile_ruleset(None)],
        parse_trait_ranges(resolved["trait_ranges"]),
    )
    initial_infections = sum(len(agent.diseases) for agent in world.agents)
    assert initial_infections > 0 and all(
        isinstance(d, Disease) for d in world.diseases
    )
    for _ in range(20):
        for value in world.agents:
            for name, attribute in MODIFIERS.items():
                expected = sum(
                    getattr(record["disease"], name + "Penalty")
                    for record in value.diseases
                    if value in record["disease"]._active_agents
                )
                assert getattr(value, attribute) == expected
        world.doTimestep()


def test_independent_infections_and_agents_keep_separate_activation(agent, illness):
    other_agent = copy(agent)
    other_illness = Disease(18, illness.configuration)
    for value in [agent, other_agent]:
        illness.infect(value)
        illness.trigger(value)
    other_illness.infect(agent)
    other_illness.trigger(agent)
    assert agent.sugarMetabolismModifier == 2 * illness.sugarMetabolismPenalty
    illness.recover(agent)
    assert agent.sugarMetabolismModifier == illness.sugarMetabolismPenalty
    assert other_agent.sugarMetabolismModifier == illness.sugarMetabolismPenalty
    other_illness.recover(agent)
    illness.recover(other_agent)
    assert agent.sugarMetabolismModifier == other_agent.sugarMetabolismModifier == 0
    assert illness._active_agents == other_illness._active_agents == set()
