"""SugarscapeAITax: an extended Sugarscape model with AI agents and taxation.

Derived from the Mesa `sugarscape_g1mt` example
(mesa/examples/advanced/sugarscape_g1mt/model.py).
Copyright 2014-2024 Core Mesa Team and contributors, licensed under the
Apache License, Version 2.0. See NOTICE and LICENSES/Apache-2.0.txt.

This file has been modified: it adds displacement/reinstatement transition
dynamics, seven policy regimes with taxation and redistribution, endogenous
resource regeneration, and a cause-of-death diagnostic.
"""

from pathlib import Path

import numpy as np

import mesa
from mesa.discrete_space import OrthogonalVonNeumannGrid
from mesa.discrete_space.property_layer import PropertyLayer

from .agents import (
    Trader, HumanAgent, AIAugmentedAgent, AutonomousAgent, OwnerHumanAgent,
)


# ---------------------------------------------------------------------------
# Helper functions for DataCollector
# ---------------------------------------------------------------------------

def compute_gini(model):
    """Gini coefficient over all agents (working humans, AI-aug, autonomous,
    and owner humans).  OwnerHumanAgents are included because they hold real
    economic wealth."""
    wealths = sorted(a.sugar + a.spice for a in model.agents)
    n = len(wealths)
    if n == 0:
        return 0.0
    total = sum(wealths)
    if total == 0:
        return 0.0
    cumsum = sum((2 * (i + 1) - n - 1) * w for i, w in enumerate(wealths))
    return cumsum / (n * total)


def flatten(list_of_lists):
    return [item for sublist in list_of_lists for item in sublist]


def geometric_mean(list_of_prices):
    if not list_of_prices:
        return 0.0
    return float(np.exp(np.log(list_of_prices).mean()))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class SugarscapeAITax(mesa.Model):
    """
    Stage 5: Sugarscape with transition dynamics — AutonomousAgent growth via
    displacement rule, reinstatement channel for WorkingHumanAgents, and
    endogenous grid regeneration.

    New in Stage 5
    --------------
    k (displacement interval): every k steps, one WorkingHumanAgent is converted
        to an AutonomousAgent; a new OwnerHumanAgent is created simultaneously.
        The converted agent's wealth goes to treasury.  This is NOT a death —
        the replacement rule does not fire.

    m (reinstatement interval): every m steps, one WorkingHumanAgent is converted
        to an AIAugmentedAgent (same cell, same wealth, fresh metabolic params).

    When k and m fire on the same step, displacement runs first so reinstatement
    draws from the already-reduced pool.

    r_base / r_effective: regeneration rate is now endogenous.
        phi = fraction of grid cells at max capacity.
        r_effective = r_base * (1 + (1 - phi)), capped at 2 * r_base.
        This increases regrowth when the grid is depleted.

    UBI fix: AutonomousAgents are excluded from UBI recipients (Stage 5 carry-in).

    Tax regimes (additions)
    -----------------------
    "displacement_levy": no per-step tax; a one-time levy is charged to each
        incoming OwnerHumanAgent at each displacement event.  Paired with
        means_tested redistribution.

    "uhi_scenario": progressive wealth tax (Stage 4 rates) applied each step to
        all agents.  Treasury is then distributed to WorkingHumanAgents and
        OwnerHumanAgents at a fixed per-agent rate (uhi_transfer_rate).

    Population dynamics
    -------------------
    Initial: n_working + n_ai_aug + n_autonomous + n_owners = 200
    Displacement events grow total population by 1 per event (+1 autonomous,
        +1 owner, -1 working).  On-grid population (excludes owners) stays
        constant.
    Reinstatement events keep total population constant (-1 working, +1 ai_aug).
    """

    def __init__(
        self,
        width=50,
        height=50,
        initial_population=200,
        # --- initial composition (sensitivity; defaults preserve 120/40/20/20) ---
        frac_autonomous=0.10,   # fraction of initial pop that is autonomous (= owners)
        frac_ai_aug=0.20,       # fraction of initial pop that is AI-augmented
        endowment_min=25,
        endowment_max=50,
        enable_trade=True,
        # --- tax ---
        tax_regime="none",
        income_threshold=None,
        wealth_threshold_lower=50,
        wealth_threshold_upper=None,
        # --- redistribution ---
        redistribution_mode="none",
        # --- sovereign wealth fund ---
        swf_endowment=0.0,
        ubi_fixed_rate=0.0,
        # --- Stage 5 transition dynamics ---
        k=10,               # displacement interval (steps per conversion)
        m=10,               # reinstatement interval (steps per conversion)
        r_base=1,           # baseline regeneration rate
        displacement_levy_rate=50.0,   # scaling factor for displacement levy
        uhi_transfer_rate=0.0,         # fixed per-agent transfer for UHI scenario
        # --- autonomous agent welfare function (sensitivity) ---
        autonomous_welfare_mode="geometric_mean",  # or "linear"
        # --- reproducibility ---
        seed=42,
    ):
        super().__init__(rng=seed)

        self.width = width
        self.height = height
        self.enable_trade = enable_trade
        self.running = True

        self._endowment_min = endowment_min
        self._endowment_max = endowment_max

        # Tax / redistribution config
        self.tax_regime = tax_regime
        self.income_threshold = income_threshold if income_threshold is not None else 0.0
        self.wealth_threshold_lower = wealth_threshold_lower
        self.wealth_threshold_upper = wealth_threshold_upper
        self.redistribution_mode = redistribution_mode

        # SWF mode
        self.ubi_fixed_rate = ubi_fixed_rate

        # Stage 5 parameters
        self.k = k
        self.m = m
        self.r_base = r_base
        self.displacement_levy_rate = displacement_levy_rate
        self.uhi_transfer_rate = uhi_transfer_rate

        # Autonomous welfare mode (sensitivity check; see agents.py)
        if autonomous_welfare_mode not in ("geometric_mean", "linear"):
            raise ValueError(
                f"autonomous_welfare_mode must be 'geometric_mean' or 'linear', "
                f"got {autonomous_welfare_mode!r}"
            )
        self.autonomous_welfare_mode = autonomous_welfare_mode

        # Treasury and step-level trackers
        self.treasury = float(swf_endowment)
        self.step_tax_revenue = 0.0
        self.step_redistribution = 0.0
        self.step_labour_tax_revenue = 0.0
        self.step_wealth_tax_revenue = 0.0
        self.step_ownerless_transfers = 0.0
        self.step_natural_deaths = 0
        self.step_starvation_deaths = 0
        self.step_starvation_wealth_sum = 0.0
        # Per-resource starvation diagnostics (Session B instrumentation)
        self.step_starvation_sugar_sum = 0.0   # surviving sugar at death
        self.step_starvation_spice_sum = 0.0   # surviving spice at death
        self.step_deaths_sugar_only = 0        # sugar<=0 AND spice>0
        self.step_deaths_spice_only = 0        # spice<=0 AND sugar>0
        self.step_deaths_both = 0              # both<=0
        # Trade-volume trackers (exchanges = one unit-of-sugar-vs-units-of-spice swap)
        self.step_trade_exchanges_total = 0
        self.step_trade_exchanges_mortal_auto = 0   # exchanges where one side is AutonomousAgent

        # Stage 5 step-level trackers
        self._current_step = 0
        self.cumulative_displacement_conversions = 0
        self.cumulative_reinstatement_conversions = 0
        self.step_displacement_conversions = 0
        self.step_reinstatement_conversions = 0
        self.step_phi = 0.0
        self.step_r_effective = float(r_base)

        # Grid
        self.grid = OrthogonalVonNeumannGrid(
            (self.width, self.height), torus=True, random=self.random
        )

        # Landscape
        self.sugar_distribution = np.genfromtxt(
            Path(__file__).parent / "sugar-map.txt"
        )
        self.spice_distribution = np.flip(self.sugar_distribution, 1)

        self.grid.add_property_layer(
            PropertyLayer.from_data("sugar", self.sugar_distribution)
        )
        self.grid.add_property_layer(
            PropertyLayer.from_data("spice", self.spice_distribution)
        )

        # --- Population split ---
        # Fractions are parametrised for the initial-composition sensitivity
        # check; defaults (0.10, 0.20) reproduce the canonical 120/40/20/20 split.
        self.frac_autonomous = frac_autonomous
        self.frac_ai_aug = frac_ai_aug
        n_auto = min(int(initial_population * frac_autonomous), initial_population)
        n_ai_aug = int(initial_population * frac_ai_aug)
        n_human_total = initial_population - n_auto - n_ai_aug
        n_owners = n_auto
        n_working = n_human_total - n_owners

        all_cells = self.grid.all_cells.cells

        # Working HumanAgents (on-grid, mortal)
        for _ in range(n_working):
            HumanAgent(
                self,
                cell=self.random.choice(all_cells),
                sugar=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                spice=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                metabolism_sugar=int(self.rng.integers(1, 4, endpoint=True)),
                metabolism_spice=int(self.rng.integers(1, 4, endpoint=True)),
                vision=int(self.rng.integers(1, 3, endpoint=True)),
                max_age=int(self.rng.integers(60, 100, endpoint=True)),
            )

        # AIAugmentedAgents (on-grid, mortal)
        for _ in range(n_ai_aug):
            AIAugmentedAgent(
                self,
                cell=self.random.choice(all_cells),
                sugar=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                spice=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                metabolism_sugar=int(self.rng.integers(1, 2, endpoint=True)),
                metabolism_spice=int(self.rng.integers(1, 2, endpoint=True)),
                vision=int(self.rng.integers(4, 6, endpoint=True)),
                max_age=int(self.rng.integers(60, 100, endpoint=True)),
            )

        # AutonomousAgents (on-grid, immortal)
        autonomous_agents = []
        for _ in range(n_auto):
            a = AutonomousAgent(
                self,
                cell=self.random.choice(all_cells),
                sugar=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                spice=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                vision=max(width, height),
            )
            autonomous_agents.append(a)

        # OwnerHumanAgents (off-grid, one per AutonomousAgent)
        for auto_agent in autonomous_agents:
            owner = OwnerHumanAgent(
                self,
                sugar=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                spice=int(self.rng.integers(endowment_min, endowment_max, endpoint=True)),
                max_age=int(self.rng.integers(60, 100, endpoint=True)),
            )
            auto_agent.owner = owner

        # Store initial working human count for displacement levy formula
        self.initial_working_humans = n_working

        # Legacy field for compatibility with Stage 4 reporters
        self.initial_human_pop = sum(
            1 for a in self.agents
            if isinstance(a, (HumanAgent, OwnerHumanAgent))
        )

        # DataCollector
        self.datacollector = mesa.DataCollector(
            model_reporters={
                "Gini": compute_gini,
                # --- population counts ---
                "n_HumanAgent": lambda m: sum(
                    1 for a in m.agents
                    if isinstance(a, (HumanAgent, OwnerHumanAgent))
                ),
                "n_WorkingHumanAgent": lambda m: sum(
                    1 for a in m.agents if isinstance(a, HumanAgent)
                ),
                "n_OwnerHumanAgent": lambda m: sum(
                    1 for a in m.agents if isinstance(a, OwnerHumanAgent)
                ),
                "n_AIAugmentedAgent": lambda m: sum(
                    1 for a in m.agents if isinstance(a, AIAugmentedAgent)
                ),
                "n_AutonomousAgent": lambda m: sum(
                    1 for a in m.agents if isinstance(a, AutonomousAgent)
                ),
                # --- treasury / tax ---
                "TaxRevenue": lambda m: m.step_tax_revenue,
                "LabourTaxRevenue": lambda m: m.step_labour_tax_revenue,
                "WealthTaxRevenue": lambda m: m.step_wealth_tax_revenue,
                "OwnerlessTransfers": lambda m: m.step_ownerless_transfers,
                "Redistribution": lambda m: m.step_redistribution,
                "Treasury": lambda m: m.treasury,
                # --- wealth distribution ---
                "MedianWealth": lambda m: (
                    float(np.median([a.sugar + a.spice for a in m.agents]))
                    if len(m.agents) > 0 else 0.0
                ),
                "MedianIncome": lambda m: (
                    float(np.median([
                        a.step_income for a in m.agents
                        if not isinstance(a, AutonomousAgent)
                    ]))
                    if sum(1 for a in m.agents if not isinstance(a, AutonomousAgent)) > 0
                    else 0.0
                ),
                "AutoWealthShare": lambda m: (
                    sum(a.sugar + a.spice for a in m.agents if isinstance(a, AutonomousAgent))
                    / max(sum(a.sugar + a.spice for a in m.agents), 1e-9)
                ),
                "HumanWealthShare": lambda m: (
                    sum(a.sugar + a.spice for a in m.agents
                        if isinstance(a, (HumanAgent, OwnerHumanAgent)))
                    / max(sum(a.sugar + a.spice for a in m.agents), 1e-9)
                ),
                "WorkingHumanWealthShare": lambda m: (
                    sum(a.sugar + a.spice for a in m.agents if isinstance(a, HumanAgent))
                    / max(sum(a.sugar + a.spice for a in m.agents), 1e-9)
                ),
                "OwnerWealthShare": lambda m: (
                    sum(a.sugar + a.spice for a in m.agents if isinstance(a, OwnerHumanAgent))
                    / max(sum(a.sugar + a.spice for a in m.agents), 1e-9)
                ),
                "AIAugWealthShare": lambda m: (
                    sum(a.sugar + a.spice for a in m.agents if isinstance(a, AIAugmentedAgent))
                    / max(sum(a.sugar + a.spice for a in m.agents), 1e-9)
                ),
                # --- demographics ---
                "InitialHumanPop": lambda m: m.initial_human_pop,
                "DisplacementRate": lambda m: (
                    max(0.0, (m.initial_human_pop
                              - sum(1 for a in m.agents
                                    if isinstance(a, (HumanAgent, OwnerHumanAgent))))
                        / m.initial_human_pop)
                    if m.initial_human_pop > 0 else 0.0
                ),
                # --- deaths ---
                "NaturalDeaths": lambda m: m.step_natural_deaths,
                "StarvationDeaths": lambda m: m.step_starvation_deaths,
                "MeanWealthAtStarvationDeath": lambda m: (
                    m.step_starvation_wealth_sum / m.step_starvation_deaths
                    if m.step_starvation_deaths > 0 else 0.0
                ),
                "MeanSugarAtStarvationDeath": lambda m: (
                    m.step_starvation_sugar_sum / m.step_starvation_deaths
                    if m.step_starvation_deaths > 0 else 0.0
                ),
                "MeanSpiceAtStarvationDeath": lambda m: (
                    m.step_starvation_spice_sum / m.step_starvation_deaths
                    if m.step_starvation_deaths > 0 else 0.0
                ),
                "StarvationDeaths_SugarOnly": lambda m: m.step_deaths_sugar_only,
                "StarvationDeaths_SpiceOnly": lambda m: m.step_deaths_spice_only,
                "StarvationDeaths_Both": lambda m: m.step_deaths_both,
                "TradeExchanges": lambda m: m.step_trade_exchanges_total,
                "TradeExchanges_MortalAuto": lambda m: m.step_trade_exchanges_mortal_auto,
                # --- owner income ---
                "MeanOwnerTransfer": lambda m: (
                    float(np.mean([
                        a.step_income for a in m.agents
                        if isinstance(a, OwnerHumanAgent)
                    ]))
                    if sum(1 for a in m.agents if isinstance(a, OwnerHumanAgent)) > 0
                    else 0.0
                ),
                "n_OwnerlessAutonomous": lambda m: sum(
                    1 for a in m.agents
                    if isinstance(a, AutonomousAgent) and a.owner is None
                ),
                # --- Stage 5 additions ---
                "DisplacementConversions": lambda m: m.cumulative_displacement_conversions,
                "ReinstatemntConversions": lambda m: m.cumulative_reinstatement_conversions,
                "phi": lambda m: m.step_phi,
                "MeanRegenerationRate": lambda m: m.step_r_effective,
            },
            agent_reporters={
                "AgentType": lambda a: type(a).__name__,
                "Wealth": lambda a: a.sugar + a.spice,
                "Sugar": lambda a: a.sugar,
                "Spice": lambda a: a.spice,
                "TaxPaid": lambda a: a.tax_paid,
                "TransferReceived": lambda a: a.transfer_received,
                "StepIncome": lambda a: a.step_income,
            },
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _compute_phi(self):
        """Fraction of grid capacity currently filled (averaged over sugar and spice)."""
        sugar_at_max = np.sum(self.grid.sugar.data >= self.sugar_distribution)
        spice_at_max = np.sum(self.grid.spice.data >= self.spice_distribution)
        total_cells = self.width * self.height
        return (sugar_at_max + spice_at_max) / (2.0 * total_cells)

    def _collect_tax(self, agent):
        """Deduct progressive labour or wealth tax from agent."""
        agent.tax_paid = 0.0

        if self.tax_regime == "none":
            return
        if self.tax_regime == "displacement_levy":
            return  # levy collected at displacement events, not per-step

        tax = 0.0

        if self.tax_regime == "labour":
            # AutonomousAgents have no taxable income (harvest goes to owner)
            if isinstance(agent, AutonomousAgent):
                return
            income = agent.step_income
            if income <= 0:
                return
            threshold = self.income_threshold
            if income <= threshold:
                tax = 0.15 * income
            else:
                tax = 0.15 * threshold + 0.30 * (income - threshold)
            self.step_labour_tax_revenue += tax

        elif self.tax_regime in ("wealth", "uhi_scenario"):
            w = agent.wealth
            lo = self.wealth_threshold_lower
            hi = self.wealth_threshold_upper
            if w <= lo:
                return
            if hi is None or w <= hi:
                tax = 0.01 * (w - lo)
            else:
                tax = 0.01 * (hi - lo) + 0.03 * (w - hi)
            self.step_wealth_tax_revenue += tax

        if tax <= 0:
            return

        total_w = agent.wealth
        tax = min(tax, max(total_w, 0.0))

        if tax > 0.0 and total_w > 0.0:
            ratio = tax / total_w
            agent.sugar -= agent.sugar * ratio
            agent.spice -= agent.spice * ratio

        agent.tax_paid = tax
        self.treasury += tax
        self.step_tax_revenue += tax

    def _transfer_autonomous_harvest(self, agent: AutonomousAgent):
        """Transfer AutonomousAgent's full step harvest to its owner (or treasury)."""
        total_harvest = agent.harvest_sugar + agent.harvest_spice
        if total_harvest <= 0:
            return

        if agent.owner is not None:
            agent.owner.sugar += agent.harvest_sugar
            agent.owner.spice += agent.harvest_spice
            agent.owner.step_income = total_harvest
            agent.owner.harvest_sugar = agent.harvest_sugar
            agent.owner.harvest_spice = agent.harvest_spice
        else:
            self.treasury += total_harvest
            self.step_ownerless_transfers += total_harvest

        # Remove the harvest from the autonomous agent's own stock
        agent.sugar -= agent.harvest_sugar
        agent.spice -= agent.harvest_spice

    def _redistribute(self):
        """Distribute treasury to eligible agents."""
        # UHI scenario: fixed-rate distribution to working + owner humans
        if self.tax_regime == "uhi_scenario" and self.uhi_transfer_rate > 0.0:
            living_humans = [
                a for a in self.agents
                if isinstance(a, (HumanAgent, OwnerHumanAgent))
            ]
            n = len(living_humans)
            if n == 0:
                self.step_redistribution = 0.0
                return
            per_agent = (
                min(self.uhi_transfer_rate, self.treasury / n)
                if self.treasury > 0.0 else 0.0
            )
            if per_agent > 0.0:
                for a in living_humans:
                    a.sugar += per_agent * 0.5
                    a.spice += per_agent * 0.5
                    a.transfer_received = per_agent
                total_paid = per_agent * n
                self.step_redistribution = total_paid
                self.treasury -= total_paid
            else:
                self.step_redistribution = 0.0
            return

        if self.redistribution_mode == "none":
            self.step_redistribution = 0.0
            return

        if self.treasury <= 0.0:
            self.step_redistribution = 0.0
            return

        if self.ubi_fixed_rate > 0.0:
            distribute = min(self.treasury, self.ubi_fixed_rate)
        else:
            distribute = self.treasury

        if distribute <= 0.0:
            self.step_redistribution = 0.0
            return

        if self.redistribution_mode == "ubi":
            # Stage 5 fix: exclude AutonomousAgents from UBI recipients
            living = [a for a in self.agents if not isinstance(a, AutonomousAgent)]
            n = len(living)
            if n == 0:
                return
            transfer = distribute / n
            for a in living:
                a.sugar += transfer * 0.5
                a.spice += transfer * 0.5
                a.transfer_received = transfer
            self.step_redistribution = distribute
            self.treasury -= distribute

        elif self.redistribution_mode == "means_tested":
            living = list(self.agents)
            if not living:
                return
            median_w = float(np.median([a.sugar + a.spice for a in living]))
            eligible = [
                a for a in living
                if isinstance(a, HumanAgent) and (a.sugar + a.spice) < median_w
            ]
            if not eligible:
                return
            transfer = distribute / len(eligible)
            for a in eligible:
                a.sugar += transfer * 0.5
                a.spice += transfer * 0.5
                a.transfer_received = transfer
            self.step_redistribution = distribute
            self.treasury -= distribute

    def _spawn_replacement(self, dead_agent, orphaned_auto=None):
        """Create a new agent to replace a dead mortal agent."""
        new_max_age = int(self.rng.integers(60, 100, endpoint=True))
        es = int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True))
        ep = int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True))

        if isinstance(dead_agent, OwnerHumanAgent):
            new_owner = OwnerHumanAgent(self, sugar=es, spice=ep, max_age=new_max_age)
            if orphaned_auto is not None:
                orphaned_auto.owner = new_owner
            return

        unoccupied = [c for c in self.grid.all_cells.cells if c.is_empty]
        if not unoccupied:
            return

        cell = self.random.choice(unoccupied)

        if isinstance(dead_agent, HumanAgent):
            HumanAgent(
                self, cell,
                sugar=es, spice=ep,
                metabolism_sugar=int(self.rng.integers(1, 4, endpoint=True)),
                metabolism_spice=int(self.rng.integers(1, 4, endpoint=True)),
                vision=int(self.rng.integers(1, 3, endpoint=True)),
                max_age=new_max_age,
            )
        elif isinstance(dead_agent, AIAugmentedAgent):
            AIAugmentedAgent(
                self, cell,
                sugar=es, spice=ep,
                metabolism_sugar=int(self.rng.integers(1, 2, endpoint=True)),
                metabolism_spice=int(self.rng.integers(1, 2, endpoint=True)),
                vision=int(self.rng.integers(4, 6, endpoint=True)),
                max_age=new_max_age,
            )

    def _process_death(self, agent, cause: str):
        """Record death, handle ownership, remove agent, spawn replacement."""
        if cause == "starvation":
            self.step_starvation_deaths += 1
            self.step_starvation_wealth_sum += agent.wealth
            # Per-resource classification — clip surviving stock at zero so the
            # mean reflects "wealth still on hand" rather than negative metabolism.
            self.step_starvation_sugar_sum += max(agent.sugar, 0.0)
            self.step_starvation_spice_sum += max(agent.spice, 0.0)
            sugar_zero = agent.sugar <= 0
            spice_zero = agent.spice <= 0
            if sugar_zero and spice_zero:
                self.step_deaths_both += 1
            elif sugar_zero:
                self.step_deaths_sugar_only += 1
            elif spice_zero:
                self.step_deaths_spice_only += 1
        else:
            self.step_natural_deaths += 1

        orphaned_auto = None
        if isinstance(agent, OwnerHumanAgent):
            self.treasury += agent.wealth
            for a in self.agents:
                if isinstance(a, AutonomousAgent) and a.owner is agent:
                    a.owner = None
                    orphaned_auto = a
                    break

        agent.remove()
        self._spawn_replacement(agent, orphaned_auto=orphaned_auto)

    def _apply_displacement(self):
        """Convert one WorkingHumanAgent → AutonomousAgent + new OwnerHumanAgent.

        The converted agent's wealth goes to the treasury.  A displacement levy
        (if tax_regime == 'displacement_levy') is charged to the new owner
        immediately after creation.
        """
        working = [a for a in self.agents if isinstance(a, HumanAgent)]
        if not working:
            return

        chosen = self.random.choice(working)

        # Levy is proportional to cumulative displacement fraction
        if self.tax_regime == "displacement_levy":
            n_displaced_after = self.cumulative_displacement_conversions + 1
            levy_amount = (
                self.displacement_levy_rate
                * n_displaced_after
                / self.initial_working_humans
            )
        else:
            levy_amount = 0.0

        # Transfer displaced agent's wealth to treasury
        self.treasury += chosen.wealth
        chosen.remove()

        # Find a free cell for the new AutonomousAgent
        unoccupied = [c for c in self.grid.all_cells.cells if c.is_empty]
        if not unoccupied:
            # Abort: can't place new autonomous agent (extremely unlikely on 50×50)
            self.cumulative_displacement_conversions += 1
            self.step_displacement_conversions += 1
            return

        target_cell = self.random.choice(unoccupied)

        new_auto = AutonomousAgent(
            self, target_cell,
            sugar=int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True)),
            spice=int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True)),
            vision=max(self.width, self.height),
        )

        new_owner = OwnerHumanAgent(
            self,
            sugar=int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True)),
            spice=int(self.rng.integers(self._endowment_min, self._endowment_max, endpoint=True)),
            max_age=int(self.rng.integers(60, 100, endpoint=True)),
        )
        new_auto.owner = new_owner

        # Charge displacement levy to new owner
        if levy_amount > 0.0 and new_owner.wealth > 0.0:
            ratio = min(1.0, levy_amount / new_owner.wealth)
            new_owner.sugar -= new_owner.sugar * ratio
            new_owner.spice -= new_owner.spice * ratio
            self.treasury += levy_amount * ratio
            self.step_tax_revenue += levy_amount * ratio

        self.cumulative_displacement_conversions += 1
        self.step_displacement_conversions += 1

    def _apply_reinstatement(self):
        """Convert one WorkingHumanAgent → AIAugmentedAgent.

        Same grid cell, same wealth carried over; fresh metabolic parameters.
        No treasury transfer.
        """
        working = [a for a in self.agents if isinstance(a, HumanAgent)]
        if not working:
            return

        chosen = self.random.choice(working)
        current_cell = chosen.cell
        current_sugar = chosen.sugar
        current_spice = chosen.spice
        chosen.remove()

        AIAugmentedAgent(
            self, current_cell,
            sugar=current_sugar,
            spice=current_spice,
            metabolism_sugar=int(self.rng.integers(1, 2, endpoint=True)),
            metabolism_spice=int(self.rng.integers(1, 2, endpoint=True)),
            vision=int(self.rng.integers(4, 6, endpoint=True)),
            max_age=int(self.rng.integers(60, 100, endpoint=True)),
        )

        self.cumulative_reinstatement_conversions += 1
        self.step_reinstatement_conversions += 1

    # -----------------------------------------------------------------------
    # Step
    # -----------------------------------------------------------------------

    def step(self):
        # --- Increment step counter ---
        self._current_step += 1

        # --- Reset step-level trackers ---
        self.step_tax_revenue = 0.0
        self.step_redistribution = 0.0
        self.step_labour_tax_revenue = 0.0
        self.step_wealth_tax_revenue = 0.0
        self.step_ownerless_transfers = 0.0
        self.step_natural_deaths = 0
        self.step_starvation_deaths = 0
        self.step_starvation_wealth_sum = 0.0
        self.step_starvation_sugar_sum = 0.0
        self.step_starvation_spice_sum = 0.0
        self.step_deaths_sugar_only = 0
        self.step_deaths_spice_only = 0
        self.step_deaths_both = 0
        self.step_trade_exchanges_total = 0
        self.step_trade_exchanges_mortal_auto = 0
        self.step_displacement_conversions = 0
        self.step_reinstatement_conversions = 0

        for a in self.agents:
            a.tax_paid = 0.0
            a.transfer_received = 0.0
            a.step_income = 0.0
            if hasattr(a, "capital_bonus"):
                a.capital_bonus = 0.0
            if isinstance(a, Trader):
                a.harvest_sugar = 0.0
                a.harvest_spice = 0.0
            elif isinstance(a, OwnerHumanAgent):
                a.harvest_sugar = 0.0
                a.harvest_spice = 0.0

        # --- Compute phi and effective regeneration rate ---
        phi = self._compute_phi()
        self.step_phi = phi
        r_effective = self.r_base * (1.0 + (1.0 - phi))
        r_effective = min(r_effective, 2.0 * self.r_base)
        self.step_r_effective = r_effective

        # --- Landscape regrowth (endogenous rate) ---
        self.grid.sugar.data = np.minimum(
            self.grid.sugar.data + r_effective, self.sugar_distribution
        )
        self.grid.spice.data = np.minimum(
            self.grid.spice.data + r_effective, self.spice_distribution
        )

        # --- Phase 1: On-grid agents move, eat, apply capital bonus ---
        agent_shuffle = list(self.agents.shuffle(inplace=False))
        for agent in agent_shuffle:
            if isinstance(agent, OwnerHumanAgent):
                agent.age += 1
                continue

            agent.prices = []
            agent.trade_partners = []

            if isinstance(agent, AutonomousAgent):
                agent.move()
                agent.eat()
                continue

            # Working HumanAgent or AIAugmentedAgent
            agent.age += 1
            agent.move()
            agent.eat()
            if isinstance(agent, AIAugmentedAgent):
                agent.apply_capital_bonus()

        # --- Phase 2: Compute step_income for on-grid mortals ---
        for agent in self.agents:
            if isinstance(agent, HumanAgent):
                agent.step_income = agent.harvest_sugar + agent.harvest_spice
            elif isinstance(agent, AIAugmentedAgent):
                agent.step_income = (agent.harvest_sugar + agent.harvest_spice
                                     + agent.capital_bonus)

        # --- Phase 3: Transfer AutonomousAgent harvest to owners/treasury ---
        for agent in self.agents:
            if isinstance(agent, AutonomousAgent):
                self._transfer_autonomous_harvest(agent)

        # --- Phase 3.5: Displacement rule ---
        # Runs first so reinstatement draws from the already-reduced pool
        if self.k > 0 and self._current_step % self.k == 0:
            self._apply_displacement()

        # --- Phase 3.6: Reinstatement rule ---
        if self.m > 0 and self._current_step % self.m == 0:
            self._apply_reinstatement()

        # --- Phase 4: Collect tax from all agents ---
        for agent in self.agents:
            self._collect_tax(agent)

        # --- Phase 5: Check deaths, spawn replacements ---
        pending_deaths = []
        for agent in self.agents:
            if isinstance(agent, AutonomousAgent):
                continue
            if isinstance(agent, OwnerHumanAgent):
                if agent.age >= agent.max_age:
                    pending_deaths.append((agent, "natural"))
            elif agent.is_starved():
                pending_deaths.append((agent, "starvation"))
            elif agent.age >= agent.max_age:
                pending_deaths.append((agent, "natural"))

        for agent, cause in pending_deaths:
            self._process_death(agent, cause)

        # --- Phase 6: Redistribute treasury ---
        self._redistribute()

        # --- Phase 7: Trade (on-grid agents only) ---
        if self.enable_trade:
            trade_shuffle = list(self.agents.shuffle(inplace=False))
            for agent in trade_shuffle:
                if not isinstance(agent, OwnerHumanAgent):
                    agent.trade_with_neighbors()

        self.datacollector.collect(self)

    def run_model(self, step_count=200):
        for _ in range(step_count):
            self.step()
