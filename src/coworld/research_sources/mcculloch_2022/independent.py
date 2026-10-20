"""Independent implementation of the released paper model, including its ID collisions.

This study-specific model does not invoke Mesa or DTL. It preserves the released
model's semantics for comparison; the frozen author implementation remains the oracle.
"""

from functools import lru_cache
from pathlib import Path
import random

from pydantic import BaseModel


class Citizen(BaseModel):
    x: int
    y: int
    sugar: int
    metabolism: int
    vision: int


@lru_cache(maxsize=4096)
def neighborhood(x, y, vision, width, height):
    """Bounded Manhattan neighborhood in the released model's enumeration order."""
    return tuple((x + dx, y + dy, dx * dx + dy * dy)
                 for dy in range(-vision, vision + 1)
                 for dx in range(-vision, vision + 1)
                 if 0 < abs(dx) + abs(dy) <= vision
                 and 0 <= x + dx < width and 0 <= y + dy < height)


class PaperModel:
    def __init__(self, seed, max_metabolism, max_vision):
        columns = [[int(value) for value in line.split()] for line in
                   (Path(__file__).parent / "sugarscape_cg/sugar-map.txt").read_text().splitlines()]
        self.width, self.height = len(columns), len(columns[0])
        self.capacity = [value for column in columns for value in column]
        self.sugar = self.capacity.copy()
        self.occupancy = [0] * len(self.sugar)
        self.random = random.Random(seed)
        self.agents: dict[tuple[int, int], Citizen] = {}
        for _ in range(100):
            x, y = self.random.randrange(self.width), self.random.randrange(self.height)
            citizen = Citizen(x=x, y=y, sugar=self.random.randrange(6, 25),
                              metabolism=self.random.randrange(1, max_metabolism + 1),
                              vision=self.random.randrange(1, max_vision + 1))
            self.occupancy[x * self.height + y] += 1
            # Replacing the scheduled ID leaves the preceding citizen physically
            # present but inactive, exactly as in the released reference.
            self.agents[x, y] = citizen

    def step(self):
        # Sugar activation is shuffled in the reference even though growth commutes.
        # Consume that RNG sequence to make full state comparisons possible.
        sugar_order = list(range(len(self.sugar)))
        self.random.shuffle(sugar_order)
        self.sugar = [min(value + 1, capacity) for value, capacity in zip(self.sugar, self.capacity)]
        order = list(self.agents)
        self.random.shuffle(order)
        for identity in order:
            citizen = self.agents[identity]
            candidates = [(x, y, distance) for x, y, distance in
                          neighborhood(citizen.x, citizen.y, citizen.vision, self.width, self.height)
                          if self.occupancy[x * self.height + y] == 0]
            candidates.append((citizen.x, citizen.y, 0))
            richest = max(self.sugar[x * self.height + y] for x, y, _ in candidates)
            candidates = [(x, y, distance) for x, y, distance in candidates
                          if self.sugar[x * self.height + y] == richest]
            closest = min(distance for _, _, distance in candidates)
            candidates = [(x, y) for x, y, distance in candidates if distance == closest]
            self.random.shuffle(candidates)
            self.occupancy[citizen.x * self.height + citizen.y] -= 1
            citizen.x, citizen.y = candidates[0]
            destination = citizen.x * self.height + citizen.y
            self.occupancy[destination] += 1
            citizen.sugar += self.sugar[destination] - citizen.metabolism
            self.sugar[destination] = 0
            if citizen.sugar <= 0:
                self.occupancy[destination] -= 1
                del self.agents[identity]
