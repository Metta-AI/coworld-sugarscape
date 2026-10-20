"""Agents for the Sugarscape AI Tax model.

Derived from the Mesa `sugarscape_g1mt` example
(mesa/examples/advanced/sugarscape_g1mt/agents.py).
Copyright 2014-2024 Core Mesa Team and contributors, licensed under the
Apache License, Version 2.0. See NOTICE and LICENSES/Apache-2.0.txt.

This file has been modified: the single trader agent of the original example
has been replaced by four agent types (HumanAgent, AIAugmentedAgent,
AutonomousAgent, OwnerHumanAgent) with type-specific welfare and metabolism.
"""

import math

import mesa
from mesa.discrete_space import CellAgent


def get_distance(cell_1, cell_2):
    x1, y1 = cell_1.coordinate
    x2, y2 = cell_2.coordinate
    dx = x1 - x2
    dy = y1 - y2
    return math.sqrt(dx**2 + dy**2)


# ---------------------------------------------------------------------------
# On-grid base class
# ---------------------------------------------------------------------------

class Trader(CellAgent):
    """
    Trader:
    - has a metabolism of sugar and spice
    - harvest and trade sugar and spice to survive

    Stage 4 additions
    -----------------
    age        : steps lived so far (incremented by model each step)
    max_age    : maximum lifespan, drawn from U[60, 100] at creation
    step_income: total income earned this step (harvest + capital bonus);
                 used as the base for the progressive labour tax
    """

    def __init__(
        self,
        model,
        cell,
        sugar=0,
        spice=0,
        metabolism_sugar=0,
        metabolism_spice=0,
        vision=0,
        max_age=80,
    ):
        super().__init__(model)
        self.cell = cell
        self.sugar = sugar
        self.spice = spice
        self.metabolism_sugar = metabolism_sugar
        self.metabolism_spice = metabolism_spice
        self.vision = vision
        self.max_age = max_age
        self.age = 0
        self.prices = []
        self.trade_partners = []
        # Per-step tracking for data collection and tax
        self.harvest_sugar = 0.0
        self.harvest_spice = 0.0
        self.step_income = 0.0
        self.capital_bonus = 0.0
        self.tax_paid = 0.0
        self.transfer_received = 0.0

    @property
    def wealth(self):
        return self.sugar + self.spice

    def get_trader(self, cell):
        for agent in cell.agents:
            if isinstance(agent, Trader):
                return agent

    def calculate_welfare(self, sugar, spice):
        m_total = self.metabolism_sugar + self.metabolism_spice
        return sugar ** (self.metabolism_sugar / m_total) * spice ** (
            self.metabolism_spice / m_total
        )

    def is_starved(self):
        return (self.sugar <= 0) or (self.spice <= 0)

    def calculate_MRS(self, sugar, spice):
        return (spice / self.metabolism_spice) / (sugar / self.metabolism_sugar)

    def calculate_sell_spice_amount(self, price):
        if price >= 1:
            sugar = 1
            spice = int(price)
        else:
            sugar = int(1 / price)
            spice = 1
        return sugar, spice

    def sell_spice(self, other, sugar, spice):
        self.sugar += sugar
        other.sugar -= sugar
        self.spice -= spice
        other.spice += spice

    def maybe_sell_spice(self, other, price, welfare_self, welfare_other):
        sugar_exchanged, spice_exchanged = self.calculate_sell_spice_amount(price)

        self_sugar = self.sugar + sugar_exchanged
        other_sugar = other.sugar - sugar_exchanged
        self_spice = self.spice - spice_exchanged
        other_spice = other.spice + spice_exchanged

        if (
            (self_sugar <= 0)
            or (other_sugar <= 0)
            or (self_spice <= 0)
            or (other_spice <= 0)
        ):
            return False

        both_agents_better_off = (
            welfare_self < self.calculate_welfare(self_sugar, self_spice)
        ) and (welfare_other < other.calculate_welfare(other_sugar, other_spice))

        mrs_not_crossing = self.calculate_MRS(
            self_sugar, self_spice
        ) > other.calculate_MRS(other_sugar, other_spice)

        if not (both_agents_better_off and mrs_not_crossing):
            return False

        self.sell_spice(other, sugar_exchanged, spice_exchanged)
        return True

    def trade(self, other):
        # Guard against zero-wealth agents (can occur after tax on immortal agents)
        if (
            self.sugar <= 0
            or self.spice <= 0
            or other.sugar <= 0
            or other.spice <= 0
        ):
            return

        # Iterative version of the original recursive trade loop.
        # Semantics are identical; avoids hitting Python's recursion limit when
        # AutonomousAgents (linear MRS) require many small trades to converge.
        # 500-iteration cap prevents runaway loops when one party has extreme wealth.
        for _ in range(500):
            assert self.sugar > 0
            assert self.spice > 0
            assert other.sugar > 0
            assert other.spice > 0

            mrs_self = self.calculate_MRS(self.sugar, self.spice)
            mrs_other = other.calculate_MRS(other.sugar, other.spice)

            welfare_self = self.calculate_welfare(self.sugar, self.spice)
            welfare_other = other.calculate_welfare(other.sugar, other.spice)

            if math.isclose(mrs_self, mrs_other):
                break

            price = math.sqrt(mrs_self * mrs_other)

            if mrs_self > mrs_other:
                sold = self.maybe_sell_spice(other, price, welfare_self, welfare_other)
            else:
                sold = other.maybe_sell_spice(self, price, welfare_other, welfare_self)

            if not sold:
                break

            self.prices.append(price)
            self.trade_partners.append(other.unique_id)

            # Trade-volume instrumentation (§2.4 sensitivity diagnostic)
            self.model.step_trade_exchanges_total += 1
            if isinstance(self, AutonomousAgent) ^ isinstance(other, AutonomousAgent):
                self.model.step_trade_exchanges_mortal_auto += 1

            # Re-check guard after each trade
            if (
                self.sugar <= 0
                or self.spice <= 0
                or other.sugar <= 0
                or other.spice <= 0
            ):
                break

    def move(self):
        neighboring_cells = [
            cell
            for cell in self.cell.get_neighborhood(self.vision, include_center=True)
            if cell.is_empty
        ]

        if not neighboring_cells:
            return

        welfares = [
            self.calculate_welfare(
                self.sugar + cell.sugar,
                self.spice + cell.spice,
            )
            for cell in neighboring_cells
        ]

        max_welfare = max(welfares)
        candidates = [
            cell
            for cell, welfare in zip(neighboring_cells, welfares)
            if math.isclose(welfare, max_welfare)
        ]

        min_dist = min(get_distance(self.cell, cell) for cell in candidates)

        final_candidates = [
            cell
            for cell in candidates
            if math.isclose(get_distance(self.cell, cell), min_dist, rel_tol=1e-02)
        ]

        self.cell = self.random.choice(final_candidates)

    def eat(self):
        self.harvest_sugar = self.cell.sugar
        self.harvest_spice = self.cell.spice
        self.sugar += self.cell.sugar
        self.cell.sugar = 0
        self.sugar -= self.metabolism_sugar
        self.spice += self.cell.spice
        self.cell.spice = 0
        self.spice -= self.metabolism_spice

    def maybe_die(self):
        """Check starvation and max-age; route through model._process_death()."""
        if self.is_starved():
            self.model._process_death(self, "starvation")
        elif self.age >= self.max_age:
            self.model._process_death(self, "natural")

    def trade_with_neighbors(self):
        if self.sugar <= 0 or self.spice <= 0:
            return
        for a in self.cell.get_neighborhood(radius=self.vision).agents:
            self.trade(a)


# ---------------------------------------------------------------------------
# On-grid mortal agents
# ---------------------------------------------------------------------------

class HumanAgent(Trader):
    """Working HumanAgent — on-grid, mortal, harvests land."""
    pass


class AIAugmentedAgent(Trader):
    """
    Human using AI tools.
    Higher vision U[4,6], lower metabolism U[1,2], earns a 10% capital
    accumulation bonus on current step's harvest income.
    """

    def __init__(
        self,
        model,
        cell,
        sugar=0,
        spice=0,
        metabolism_sugar=0,
        metabolism_spice=0,
        vision=0,
        max_age=80,
    ):
        super().__init__(
            model, cell, sugar, spice, metabolism_sugar, metabolism_spice,
            vision, max_age,
        )

    def apply_capital_bonus(self):
        """Add 10% of this step's harvest income as capital bonus.
        Split proportional to sugar/spice harvest fractions."""
        harvested = self.harvest_sugar + self.harvest_spice
        if harvested <= 0:
            self.capital_bonus = 0.0
            return
        bonus = 0.10 * harvested
        self.capital_bonus = bonus
        sugar_frac = self.harvest_sugar / harvested
        spice_frac = self.harvest_spice / harvested
        self.sugar += bonus * sugar_frac
        self.spice += bonus * spice_frac


# ---------------------------------------------------------------------------
# On-grid immortal agent
# ---------------------------------------------------------------------------

class AutonomousAgent(Trader):
    """
    Fully autonomous AI system.
    Full-grid vision, zero metabolism, immortal.
    Each step its full harvest is transferred to its linked OwnerHumanAgent
    (or to the treasury if the owner has died).
    """

    def __init__(
        self,
        model,
        cell,
        sugar=0,
        spice=0,
        vision=50,
    ):
        super().__init__(
            model, cell, sugar, spice,
            metabolism_sugar=0, metabolism_spice=0,
            vision=vision,
            max_age=None,   # immortal — max_age not used
        )
        # Set by model after construction; direct reference to OwnerHumanAgent
        self.owner: "OwnerHumanAgent | None" = None

    # --- Welfare / MRS overrides (avoid division by zero with metabolism=0) ---
    # Two modes, selected at model construction (model.autonomous_welfare_mode):
    #   "geometric_mean": equal-metabolism limit of Cobb-Douglas (default; trades
    #                     toward balanced stocks).
    #   "linear":         constant marginal utility (sensitivity check; autonomous
    #                     values both resources equally regardless of stock).

    def calculate_welfare(self, sugar, spice):
        if self.model.autonomous_welfare_mode == "linear":
            return float(max(sugar, 0) + max(spice, 0))
        return math.sqrt(max(sugar, 0) * max(spice, 0))

    def calculate_MRS(self, sugar, spice):
        if self.model.autonomous_welfare_mode == "linear":
            return 1.0
        if sugar <= 0:
            return float("inf")
        return spice / sugar

    # --- Mortality overrides ---

    def is_starved(self):
        return False  # Cannot starve

    def maybe_die(self):
        pass  # Immortal — replacement rule does not apply

    # --- Trading override ---
    # Autonomous agents do not initiate trades; they can still be approached
    # as trade partners by other agents calling trade_with_neighbors.
    def trade_with_neighbors(self):
        pass


# ---------------------------------------------------------------------------
# Off-grid owner agent
# ---------------------------------------------------------------------------

class OwnerHumanAgent(mesa.Agent):
    """
    Off-grid HumanAgent that owns one AutonomousAgent.

    Design (Stage 4)
    ----------------
    * Zero metabolism, zero vision — does not move, does not harvest land,
      cannot starve.
    * Exists purely as an accounting identity; NOT placed on the grid.
    * Each step receives the full harvest of its linked AutonomousAgent as
      passive income (step_income).  If the owner has died, harvest is
      redirected to the treasury.
    * Subject to labour tax on step_income and wealth tax on stock.
    * Dies only at max_age (drawn from U[60, 100] at creation).
    * On death, replaced by a new working HumanAgent; the linked
      AutonomousAgent becomes permanently ownerless and its harvest flows
      to the treasury from that point on.
    """

    def __init__(self, model, sugar=0, spice=0, max_age=80):
        super().__init__(model)
        self.sugar = float(sugar)
        self.spice = float(spice)
        self.age = 0
        self.max_age = max_age
        # Per-step tracking
        self.step_income = 0.0      # autonomous harvest received this step
        self.tax_paid = 0.0
        self.transfer_received = 0.0
        # Book-keeping attributes kept for interface consistency
        self.harvest_sugar = 0.0
        self.harvest_spice = 0.0
        self.capital_bonus = 0.0
        self.metabolism_sugar = 0
        self.metabolism_spice = 0
        self.vision = 0

    @property
    def wealth(self) -> float:
        return self.sugar + self.spice
