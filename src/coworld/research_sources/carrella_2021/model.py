"""Independent Carrella study model; Python RNG is not NetLogo replay-equivalent.

Rules audited against CarrKnight/nofreelunch 0400f750, Sugarscape trade.nlogo.
The author model carries a CC BY-NC-SA 3.0 notice. See the study README.
"""
import argparse
import csv
import math
import random
from pathlib import Path

from pydantic import BaseModel, Field


class Parameters(BaseModel):
    population: int = Field(ge=0, le=2500)
    mutation: float = Field(ge=0, le=1)
    maximum_sugar: int = Field(gt=5)
    maximum_spice: int = Field(ge=5)
    reproduction: float = Field(ge=0)
    seed: int


class Agent(BaseModel):
    identifier: int
    x: int
    y: int
    sugar: float
    spice: float
    sugar_metabolism: int
    spice_metabolism: int
    vision: int
    wealth: float
    potential_sugar: float = 0
    potential_spice: float = 0


def utility(sugar, spice, sugar_metabolism, spice_metabolism):
    if sugar <= 0 or spice <= 0:
        return 0.0
    total = sugar_metabolism + spice_metabolism
    return sugar ** (sugar_metabolism / total) * spice ** (spice_metabolism / total)


def distance_squared(a, b):
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return min(dx, 50 - dx) ** 2 + min(dy, 50 - dy) ** 2


class Model:
    def __init__(self, parameters: Parameters):
        self.parameters = parameters
        self.random = random.Random(parameters.seed)
        self.cells = [(x, y) for x in range(50) for y in range(50)]
        self.capacity_sugar = dict.fromkeys(self.cells, 0)
        self.capacity_spice = dict.fromkeys(self.cells, 0)
        for capacities, peaks in [(self.capacity_sugar, [(38, 38), (12, 12)]),
                                   (self.capacity_spice, [(12, 38), (38, 12)])]:
            for peak in peaks:
                for radius, amount in [(4, 4), (8, 3), (12, 2), (16, 1)]:
                    for cell in self.cells:
                        if distance_squared(cell, peak) <= radius * radius and (radius == 4 or capacities[cell] == 0):
                            capacities[cell] = amount
        self.sugar = self.capacity_sugar.copy()
        self.spice = self.capacity_spice.copy()
        self.agents: dict[int, Agent] = {}
        self.occupied: dict[tuple[int, int], int] = {}
        self.next_id = 0
        self.tick = 0
        self.prices: list[float] = []
        self.mean_price = 0.0
        for identifier in range(parameters.population):
            x, y = self.random.choice([cell for cell in self.cells if cell not in self.occupied])
            sugar = self.random.randint(5, parameters.maximum_sugar)
            spice = self.random.randint(5, parameters.maximum_spice)
            sm, pm, vision = self.random.randint(1, 4), self.random.randint(1, 4), self.random.randint(1, 6)
            agent = Agent(identifier=identifier, x=x, y=y, sugar=sugar, spice=spice,
                          sugar_metabolism=sm, spice_metabolism=pm, vision=vision,
                          wealth=utility(sugar, spice, sm, pm))
            self.agents[identifier] = agent
            self.occupied[x, y] = identifier
            self.next_id += 1

    def order(self):
        identifiers = list(self.agents)
        self.random.shuffle(identifiers)
        return identifiers

    def remove(self, agent):
        del self.occupied[agent.x, agent.y]
        del self.agents[agent.identifier]

    def step(self):
        if not self.agents:
            return
        for cell in self.cells:
            self.sugar[cell] = min(self.capacity_sugar[cell], self.sugar[cell] + 1)
            self.spice[cell] = min(self.capacity_spice[cell], self.spice[cell] + 1)
        for identifier in self.order():
            agent = self.agents[identifier]
            origin = agent.x, agent.y
            candidates = {origin}
            for distance in range(1, agent.vision + 1):
                for dx, dy in [(0, distance), (distance, 0), (0, -distance), (-distance, 0)]:
                    cell = (agent.x + dx) % 50, (agent.y + dy) % 50
                    if cell not in self.occupied:
                        candidates.add(cell)
            scores = {cell: utility(agent.sugar + self.sugar[cell], agent.spice + self.spice[cell],
                                   agent.sugar_metabolism, agent.spice_metabolism) for cell in candidates}
            maximum = max(scores.values())
            winners = [cell for cell in sorted(candidates) if scores[cell] == maximum]
            nearest = min(distance_squared(origin, cell) for cell in winners)
            destination = self.random.choice([cell for cell in winners if distance_squared(origin, cell) == nearest])
            del self.occupied[origin]
            agent.x, agent.y = destination
            self.occupied[destination] = identifier
            agent.sugar += self.sugar[destination] - agent.sugar_metabolism
            agent.spice += self.spice[destination] - agent.spice_metabolism
            self.sugar[destination] = self.spice[destination] = 0
            if agent.sugar <= 0 or agent.spice <= 0:
                self.remove(agent)
        self.prices = []
        for identifier in self.order():
            caller = self.agents[identifier]
            neighbors = [self.occupied[cell] for cell in
                         [((caller.x + dx) % 50, (caller.y + dy) % 50)
                          for dx in [-1, 0, 1] for dy in [-1, 0, 1] if dx or dy]
                         if cell in self.occupied]
            self.random.shuffle(neighbors)
            for neighbor in neighbors:
                partner = self.agents[neighbor]
                first = (caller.spice / caller.spice_metabolism) / (caller.sugar / caller.sugar_metabolism)
                second = (partner.spice / partner.spice_metabolism) / (partner.sugar / partner.sugar_metabolism)
                price = math.sqrt(first * second)
                if first != second:
                    buyer, seller = (caller, partner) if first > second else (partner, caller)
                    sugar_amount, spice_amount = (1, price) if price >= 1 else (1 / price, 1)
                    buyer.potential_sugar, buyer.potential_spice = buyer.sugar + sugar_amount, buyer.spice - spice_amount
                    seller.potential_sugar, seller.potential_spice = seller.sugar - sugar_amount, seller.spice + spice_amount
                # Equal rates leave prior potentials untouched in the author procedure.
                first_wealth = utility(caller.potential_sugar, caller.potential_spice, caller.sugar_metabolism, caller.spice_metabolism)
                second_wealth = utility(partner.potential_sugar, partner.potential_spice, partner.sugar_metabolism, partner.spice_metabolism)
                if first_wealth >= caller.wealth and second_wealth >= partner.wealth:
                    caller.sugar, caller.spice, caller.wealth = caller.potential_sugar, caller.potential_spice, first_wealth
                    partner.sugar, partner.spice, partner.wealth = partner.potential_sugar, partner.potential_spice, second_wealth
                    self.prices.append(price)
        for identifier in self.order():
            agent = self.agents[identifier]
            if agent.sugar <= 0 or agent.spice <= 0:
                self.remove(agent)
                continue
            if agent.wealth > self.parameters.reproduction:
                empty = [cell for cell in self.cells if cell not in self.occupied
                         and distance_squared((agent.x, agent.y), cell) <= 9]
                if empty:
                    agent.sugar /= 2
                    agent.spice /= 2
                    child = agent.model_copy(deep=True)
                    child.identifier = self.next_id
                    self.next_id += 1
                    child.x, child.y = self.random.choice(empty)
                    for trait in ['sugar_metabolism', 'spice_metabolism', 'vision']:
                        if self.random.random() < self.parameters.mutation:
                            setattr(child, trait, getattr(child, trait) + self.random.choice([-1, 1]))
                    child.sugar_metabolism = max(1, child.sugar_metabolism)
                    child.spice_metabolism = max(1, child.spice_metabolism)
                    child.vision = min(6, child.vision)
                    child.wealth = utility(child.sugar, child.spice, child.sugar_metabolism, child.spice_metabolism)
                    self.agents[child.identifier] = child
                    self.occupied[child.x, child.y] = child.identifier
        for agent in self.agents.values():
            agent.wealth = utility(agent.sugar, agent.spice, agent.sugar_metabolism, agent.spice_metabolism)
        if self.prices:
            self.mean_price = sum(self.prices) / len(self.prices)
        self.tick += 1
        assert len(self.agents) == len(self.occupied)
        assert {(a.x, a.y): a.identifier for a in self.agents.values()} == self.occupied

    def observation(self):
        wealths = sorted(a.wealth for a in self.agents.values())
        n, total = len(wealths), sum(wealths)
        gini = 0.0
        if n:
            cumulative = 0.0
            area = 0.0
            for index, wealth in enumerate(wealths, 1):
                cumulative += wealth
                area += index / n - cumulative / total
            gini = 2 * area / n
        return [self.tick, n, gini, sum(self.sugar.values()), sum(self.spice.values()), len(self.prices), self.mean_price]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parameters', type=Path, help='Validated study Parameters JSON')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    model = Model(Parameters.model_validate_json(args.parameters.read_text()))
    with args.output.open('x', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(['tick', 'population', 'gini', 'landscape_sugar', 'landscape_spice', 'trade_count', 'mean_price'])
        for _ in range(501):
            writer.writerow(model.observation())
            model.step()
