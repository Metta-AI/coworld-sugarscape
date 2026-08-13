# Solo-ladder scenarios

The `solo-ladder` variant draws one of 24 curated world/target scenarios for
each episode. A submission receives the resolved public configuration and its
assigned target, then submits one SugarLang ruleset before the simulation runs.
Competitive submissions therefore need to adapt to the observed world rather
than memorize one map.

`solo-wealth` remains the fixed, single-target introductory variant.

## Selection

Scenario selection is deterministic: the game uses
`scenario_pool[seed % 24]`. Selection consumes no simulation randomness. The
resolved result and replay include `scenario_index`; players do not receive the
seed or the undisclosed pool.

The pool is fixed manifest data. It does not generate new parameters at episode
time.

## Families

Every family contains four distinct worlds. Grid dimensions stay between 40 and
60 cells per side, and starting populations stay between 200 and 400 agents.

| Family | Scenarios | Target | Mechanical regime |
|---|---|---|---|
| Wealth, skewed | `twin-peaks`, `mega-peak`, `four-corners`, `scarce-lowland` | `wealth.skewed-gini-0.5` | Finite lives and replacement to the starting population |
| Wealth, egalitarian | `offset-twins`, `central-plateau`, `four-basins`, `scarce-income` | `wealth.egalitarian` | Short finite lives, replacement, narrow endowments, and universal income |
| Carrying capacity | `compact-regrow-1`, `wide-regrow-1`, `dense-regrow-2`, `sparse-regrow-2` | `population.carrying-capacity` | Immortal agents, no replacement, and no reproduction |
| Survivorship | `young-frontier`, `long-lived`, `scarce`, `seasonal-migration` | `age-at-death.survivorship` | Finite varied lifespans and replacement; one seasonal world |
| Price equilibrium | `overlapping-peaks`, `opposite-corners`, `four-markets`, `split-centers` | `price.equilibrium` | Immortal agents with sugar, spice, and bilateral trade |
| Tribes | `three-way-mixed`, `two-way-mixed`, `opposite-quadrants`, `three-quadrants` | `tribe.convergence` twice and `tribe.diversity` twice | Cultural tagging; mixed starts for convergence and quadrant-separated starts for diversity |

Scenarios explicitly pin the mechanics their targets require and disable
unwanted hazards such as disease, pollution, combat, lending, and unrelated
spice or seasonal behavior. The two egalitarian income intervals are both
enabled because DTL's endowment machinery otherwise creates a zero-spice
time-to-live edge case even when spice metabolism is disabled.

## Source of truth

`tools/generate_scenario_pool.py` owns the ordered scenario definitions. The
manifest pool is generated output. From the repository root:

```console
.venv/bin/python tools/generate_scenario_pool.py --write
.venv/bin/python tools/generate_scenario_pool.py --check
.venv/bin/python tools/generate_scenario_pool.py --emit-configs
```

`--write` changes only `solo-ladder.game_config.scenario_pool` and preserves the
rest of `coworld_manifest.json`. `--check` exits nonzero and summarizes drift.
`--emit-configs [DIR]` writes one standalone merged config per scenario, by
default under `build/scenario-pool/`; emitted configs contain neither `seed` nor
`scenario_pool` because the probe supplies its own seeds.

To add or replace a scenario, edit the generator first, run `--write`, update
this catalog, and run the scenario-pool tests. Changing the pool size also
changes the selection modulus and pool-cycle duration, so update both here and
in the approved design before shipping.

## Reachability gate

Run the full pool probe before putting a changed pool into ranked rotation:

```console
.venv/bin/python tools/probe_pool.py
```

The default budget is 24 candidates, 12 generations, and episode seeds 11 and
42 per scenario. `--only <scenario-id>` restricts a smoke or diagnostic run.
Each scenario invokes `tools/probe_reachability.py` in its own subprocess and
keeps that probe's detailed report and best ruleset under
`build/probe-pool/<scenario-id>/`. The wrapper writes the combined
`build/probe-pool/report.json` and prints a table containing the null floor,
greedy baseline, evolved ceiling, and skill gradient.

A scenario passes only when both conditions hold:

- Evolved ceiling is at least `0.50`.
- Evolved ceiling minus null floor is at least `0.05`.

The evolved score is a lower bound on what is achievable. A passing result
demonstrates reachability and a real skill gradient; a failure is conservative,
but the scenario must still be retuned or replaced before rotation. Passing one
member never waives validation for another member of its family.
