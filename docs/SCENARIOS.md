# Ladder scenarios

The `solo-ladder` variant draws one of 80 scenarios (12 hand-tuned base worlds
crossed with mechanic packs) for each episode. A submission receives the
resolved public configuration and its assigned target, then submits one
SugarLang ruleset before the simulation runs. Competitive submissions therefore
need to adapt to the observed world rather than memorize one map.

The `duo-ladder` variant reuses those 80 worlds with two seats and two distinct
global targets. Both policies observe the same resolved world configuration,
but each receives only its own assigned target and submits its own ruleset. The
game measures one shared outcome and scores each seat independently against its
target. Target order alternates between scenarios so one seat is not permanently
associated with the solo objective.

`solo-wealth` remains the fixed, single-target introductory variant.

## Selection

Scenario selection is deterministic: the game uses
`scenario_pool[seed % 80]`. Selection consumes no simulation randomness. The
resolved result and replay include `scenario_index`; players do not receive the
seed or the undisclosed pool.

Both pools are fixed manifest data. They do not generate new parameters at
episode time.

## Duo target pairs

The duo pool keeps the solo target and adds a distinct catalog target that the
same world can measure:

| Solo family | Duo targets |
|---|---|
| Wealth | `wealth.skewed-gini-0.5` and `wealth.egalitarian` |
| Carrying capacity | `population.carrying-capacity` and `wealth.skewed-gini-0.5` |
| Survivorship | `age-at-death.survivorship` and `wealth.egalitarian` |
| Price equilibrium | `price.equilibrium` and `wealth.skewed-gini-0.5` |
| Tribes | `tribe.convergence` and `tribe.diversity` |

These are global targets by design: the two policies compete to steer the same
macro outcome, and their objectives may be compatible, orthogonal, or directly
in tension. All current bases have even starting populations. The generator
still increments an odd starting population by one in a duo copy so the initial
population always divides evenly between two seats.

## Families

Each family contributes two hand-tuned base worlds. Mechanic packs layer fixed
override deltas over those bases without changing their targets.

| Family | Base worlds | Target | Base regime |
|---|---|---|---|
| Wealth, skewed | `wealth-skewed.twin-peaks`, `wealth-skewed.scarce-lowland` | `wealth.skewed-gini-0.5` | Finite lives with replacement to the starting population |
| Wealth, egalitarian | `wealth-egalitarian.central-plateau`, `wealth-egalitarian.scarce-income` | `wealth.egalitarian` | Short finite lives, replacement, narrow endowments, and universal income |
| Carrying capacity | `capacity.compact-regrow-1`, `capacity.sparse-regrow-2` | `population.carrying-capacity` | Immortal agents with no replacement or reproduction |
| Survivorship | `survivorship.young-frontier`, `survivorship.long-lived` | `age-at-death.survivorship` | Replacement populations with distinct finite lifespan ranges |
| Price equilibrium | `price.overlapping-peaks`, `price.four-markets` | `price.equilibrium` | Immortal agents with sugar, spice, and bilateral trade |
| Tribes | `tribe-convergence.three-way-mixed`, `tribe-diversity.opposite-quadrants` | `tribe.convergence`, `tribe.diversity` | Reproducing tagged populations; mixed starts for convergence and separated quadrants for diversity |

| Pack | What it enables | Standalone pack families |
|---|---|---|
| `baseline` | No delta; preserves the bare base id and regime | All |
| `spice` | Mirrors sugar peaks at swapped coordinates, sorted into DTL's canonical order; sets `environmentMaxSpice` from `environmentMaxSugar`, `environmentSpiceRegrowRate` to 1, `agentSpiceMetabolism` to `[1, 4]`, and `agentStartingSpice` to `[10, 30]` | All except price, where spice is already on |
| `market` | Adds the `spice` delta, `agentTradeFactor [1, 1]`, and trade trait `[0, 1]` | All except price, where trade is already on |
| `combat` | Sets `agentAggressionFactor` and the aggression trait to `[0, 2]` and `environmentMaxCombatLoot` to 2; non-tribe bases also gain `agentTagging true`, `agentTagStringLength 11`, and `environmentMaxTribes 2` because DTL permits combat prey only from another tribe | All |
| `disease` | Sets `startingDiseases` to 40, `startingDiseasesPerAgent` to `[0, 3]`, `agentImmuneSystemLength` to 35, metabolism penalties to `[1, 3]`, and transmission chance to `[1.0, 1.0]`; aggression, fertility, movement, and vision side effects stay `[0, 0]`, and spiceless worlds use `diseaseSpiceMetabolismPenalty [0, 0]` so disease cannot create an unsupplied spice need | Wealth-egalitarian, survivorship, price, tribes |
| `pollution` | Enables sugar production and consumption pollution with `environmentPollutionTimeframe [0, 1000]`, `environmentPollutionDiffusionTimeframe [50, 1000]`, and `environmentPollutionDiffusionDelay 10`; spice pollution is also enabled when spice is present | Wealth-skewed, carrying capacity |
| `seasons` | Sets `environmentSeasonInterval` to 50 and `environmentSeasonalGrowbackDelay` to 8 | Wealth-egalitarian, carrying capacity, survivorship, price, tribes |
| `reproduction` | Enables fertility factor `[1, 1]` and fertility trait `[0, 1]`, and disables automatic replacement | Wealth-skewed |
| `everything` | Combines market, combat, disease, pollution, and seasons while preserving price bases' tuned spice/trade values, tribe counts, and every base's existing reproduction regime | All |

The two egalitarian income intervals are both enabled because DTL's endowment
machinery otherwise creates a zero-spice time-to-live edge case even when spice
metabolism is disabled.

## Source of truth

`tools/generate_scenario_pool.py` owns the ordered scenario definitions and
derives the duo target assignments from them. Both manifest pools are generated
output. From the repository root:

```console
.venv/bin/python tools/generate_scenario_pool.py --write
.venv/bin/python tools/generate_scenario_pool.py --check
```

`--write` changes only the `solo-ladder` and `duo-ladder` scenario pools and
preserves the rest of `coworld_manifest.json`. `--check` exits nonzero and
summarizes drift.

To change the pool, edit the generator first, run `--write`, update this catalog,
and run the scenario-pool tests. Changing the pool size also changes the
selection modulus and pool-cycle duration, so update both here and in the
approved design before shipping.
