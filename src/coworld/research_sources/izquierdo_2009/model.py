"""Full growback, movement and replacement model for controlled path witnesses."""

from dataclasses import dataclass
import hashlib
import json
import math
import random


@dataclass(slots=True)
class Agent:
    position: int
    vision: int
    metabolism: int
    wealth: int
    life: int


class Model:
    def __init__(self, capacity, agents, sugar, seed):
        self.capacity = capacity
        self.sugar = list(sugar)
        self.agents = agents
        self.rng = random.Random(seed)
        self.births = 0
        self.harvest = 0
        self.log_choice_probability = 0.0
        self.check()

    def check(self):
        assert len(self.capacity) == len(self.sugar) == 2500
        assert len(self.agents) == len({a.position for a in self.agents}) == 250
        assert all(0 <= s <= c <= 4 for s, c in zip(self.sugar, self.capacity))
        assert all(
            0 <= a.position < 2500
            and 1 <= a.vision <= 6
            and 1 <= a.metabolism <= 4
            and 1 <= a.wealth <= 325
            and 1 <= a.life <= 100
            and a.wealth + 3 * a.life <= 325
            for a in self.agents
        )

    def state_hash(self):
        # The paper's state excludes identifiers and elapsed wall/simulation time.
        occupants = sorted(
            (a.position, a.vision, a.metabolism, a.wealth, a.life) for a in self.agents
        )
        return hashlib.sha256(json.dumps([self.sugar, occupants]).encode()).hexdigest()

    def observation(self, experiment, step):
        return {
            "experiment": experiment,
            "step": step,
            "state_sha256": self.state_hash(),
            "births": self.births,
            "harvest": self.harvest,
            "log_choice_probability": self.log_choice_probability,
            "sugar": list(self.sugar),
            "slots": [
                [a.position, a.vision, a.metabolism, a.wealth, a.life]
                for a in self.agents
            ],
            "occupants": sorted(
                (a.position, a.vision, a.metabolism, a.wealth, a.life)
                for a in self.agents
            ),
        }

    def step(self, birth_policy):
        self.sugar = [min(c, s + 1) for c, s in zip(self.capacity, self.sugar)]
        occupied = {a.position for a in self.agents}
        order = list(range(250))
        self.rng.shuffle(order)
        self.log_choice_probability -= math.lgamma(251)
        events = {
            "activation_order": list(order),
            "destinations": [],
            "replacement_order": [],
            "newborns": [],
        }
        dead = []
        for index in order:
            agent = self.agents[index]
            row, column = divmod(agent.position, 50)
            distances = {agent.position: 0}
            for distance in range(1, agent.vision + 1):
                for y, x in (
                    (row + distance, column),
                    (row - distance, column),
                    (row, column + distance),
                    (row, column - distance),
                ):
                    position = (y % 50) * 50 + x % 50
                    if position not in occupied:
                        distances[position] = distance
            best = max(self.sugar[p] for p in distances)
            nearest = min(d for p, d in distances.items() if self.sugar[p] == best)
            choices = sorted(
                p
                for p, d in distances.items()
                if self.sugar[p] == best and d == nearest
            )
            # Selecting the first eligible tie has strictly positive uniform probability.
            self.log_choice_probability -= math.log(len(choices))
            occupied.remove(agent.position)
            agent.position = choices[0]
            events["destinations"].append(agent.position)
            occupied.add(agent.position)
            collected = self.sugar[agent.position]
            self.sugar[agent.position] = 0
            self.harvest += collected
            agent.wealth += collected - agent.metabolism
            agent.life -= 1
            if agent.wealth <= 0 or agent.life <= 0:
                occupied.remove(agent.position)
                dead.append(index)
        self.rng.shuffle(dead)
        events["replacement_order"] = list(dead)
        self.log_choice_probability -= math.lgamma(len(dead) + 1)
        for index in dead:
            newborn = birth_policy(index, occupied)
            assert newborn.position not in occupied and 0 <= newborn.position < 2500
            assert 1 <= newborn.vision <= 6 and 1 <= newborn.metabolism <= 4
            assert 5 <= newborn.wealth <= 25 and 60 <= newborn.life <= 100
            self.log_choice_probability -= math.log(
                (2500 - len(occupied)) * 6 * 4 * 21 * 41
            )
            events["newborns"].append(
                [
                    newborn.position,
                    newborn.vision,
                    newborn.metabolism,
                    newborn.wealth,
                    newborn.life,
                ]
            )
            self.agents[index] = newborn
            occupied.add(newborn.position)
            self.births += 1
        self.check()
        return events
