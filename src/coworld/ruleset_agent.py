"""DTL Agent subclass controlled by a validated SugarLang ruleset."""

from __future__ import annotations

import random
from typing import Any

from sugarscape.agent import Agent

from .instrumentation import timed_subphase
from .ruleset import FeatureContext


class RulesetAgent(Agent):
    """Attach seat ownership, trait overrides, and custom movement ranking."""

    def __init__(self, agentID: int, birthday: int, cell: Any, configuration: dict[str, Any]) -> None:
        world = cell.environment.sugarscape
        self.seat = world.seat_manager.seat_for_spawn(configuration)
        super().__init__(agentID, birthday, cell, configuration)
        self.ruleset = world.seat_manager.ruleset(self.seat)
        self._feature_context = FeatureContext()
        self._apply_trait_overrides(world.seat_manager.trait_ranges)

    def findChildEndowment(self, mate: Agent) -> dict[str, Any]:
        """Use DTL inheritance, then draw the newborn's parent seat 50/50."""

        configuration = super().findChildEndowment(mate)
        parent = self if random.random() < 0.5 else mate
        configuration["_coworld_seat"] = parent.seat
        return configuration

    def spawnChild(
        self,
        childID: int,
        birthday: int,
        cell: Any,
        configuration: dict[str, Any],
    ) -> RulesetAgent:
        """Keep newborns on the RulesetAgent path used by initial agents."""

        return RulesetAgent(childID, birthday, cell, configuration)

    def sortCellsByWealth(self, cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace only candidate ranking; DTL still supplies the candidate set."""

        if self.ruleset.movement is None:
            return super().sortCellsByWealth(cells)

        world = self.cell.environment.sugarscape
        with timed_subphase(world.instrumentation, "ruleset_evaluation"):
            context = self._feature_context
            self._set_agent_and_world_features(context)
            for record in cells:
                candidate = record["cell"]
                prey = candidate.agent
                context.set_cell_features(
                    sugar=candidate.sugar,
                    spice=candidate.spice,
                    pollution=candidate.pollution,
                    distance=record["range"],
                    occupied=1 if prey is not None else 0,
                    prey_wealth=prey.sugar + prey.spice if prey is not None else 0,
                    welfare=record["wealth"],
                )
                record["wealth"] = self.ruleset.score_cell(context)
        return super().sortCellsByWealth(cells)

    def moveToBestCell(self, predeterminedMove: Any = None) -> None:
        world = self.cell.environment.sugarscape
        with timed_subphase(world.instrumentation, "movement"):
            super().moveToBestCell(predeterminedMove)

    def doTrading(self) -> None:
        with timed_subphase(self.cell.environment.sugarscape.instrumentation, "trade"):
            super().doTrading()

    def doReproduction(self) -> None:
        with timed_subphase(self.cell.environment.sugarscape.instrumentation, "reproduction"):
            super().doReproduction()

    def doLending(self) -> None:
        with timed_subphase(self.cell.environment.sugarscape.instrumentation, "lending"):
            super().doLending()

    def doDisease(self) -> None:
        with timed_subphase(self.cell.environment.sugarscape.instrumentation, "disease"):
            super().doDisease()

    def _apply_trait_overrides(self, trait_ranges: dict[str, Any]) -> None:
        traits = self.ruleset.traits
        assignments = {
            "aggression": "aggressionFactor",
            "trade": "tradeFactor",
            "lending": "lendingFactor",
            "fertility": "fertilityFactor",
        }
        for name, attribute in assignments.items():
            value = getattr(traits, name)
            if value is not None:
                setattr(self, attribute, trait_ranges[name].clamp(value))

    def _set_agent_and_world_features(self, context: FeatureContext) -> None:
        sugar_metabolism = self.findSugarMetabolism()
        spice_metabolism = self.findSpiceMetabolism()
        sugar_need = self.sugar / sugar_metabolism if sugar_metabolism > 0 else 1
        spice_need = self.spice / spice_metabolism if spice_metabolism > 0 else 1
        mrs = self.tradeFactor * (spice_need / sugar_need) if sugar_need != 0 else 0
        context.set_agent_features(
            sugar=self.sugar,
            spice=self.spice,
            wealth=self.sugar + self.spice,
            sugar_metabolism=sugar_metabolism,
            spice_metabolism=spice_metabolism,
            vision=self.findVision(),
            movement=self.findMovement(),
            age=self.age,
            ttl=self.findTimeToLive(),
            mrs=mrs,
        )
        cache = self.cell.environment.sugarscape.world_features
        context.set_world_features(
            timestep=cache.timestep,
            population=cache.population,
            gini=cache.gini,
            mean_wealth=cache.mean_wealth,
        )
