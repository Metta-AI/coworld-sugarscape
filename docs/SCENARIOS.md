# Ladder scenarios

The `solo-ladder` variant draws one of 24 curated world/target scenarios for
each episode. A submission receives the resolved public configuration and its
assigned target, then submits one SugarLang ruleset before the simulation runs.
Competitive submissions therefore need to adapt to the observed world rather
than memorize one map.

The `duo-ladder` variant reuses those 24 worlds with two seats and two distinct
global targets. Both policies observe the same resolved world configuration,
but each receives only its own assigned target and submits its own ruleset. The
game measures one shared outcome and scores each seat independently against its
target. Target order alternates between scenarios so one seat is not permanently
associated with the solo objective.

`solo-wealth` remains the fixed, single-target introductory variant.

## Selection

Scenario selection is deterministic: the game uses
`scenario_pool[seed % 24]`. Selection consumes no simulation randomness. The
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
in tension. `capacity.wide-regrow-1` uses 276 starting agents in the duo copy
instead of 275 so the initial population divides evenly between two seats.

## Families

Every family contains four distinct worlds. Grid dimensions stay between 40 and
60 cells per side, and starting populations stay between 200 and 400 agents.

| Family | Scenarios | Target | Mechanical regime |
|---|---|---|---|
| Wealth, skewed | `twin-peaks`, `mega-peak`, `four-corners`, `scarce-lowland` | `wealth.skewed-gini-0.5` | Finite lives and replacement to the starting population |
| Wealth, egalitarian | `offset-twins`, `central-plateau`, `four-basins`, `scarce-income` | `wealth.egalitarian` | Short finite lives, replacement, narrow endowments, and universal income |
| Carrying capacity | `compact-regrow-1`, `wide-regrow-1`, `dense-regrow-2`, `sparse-regrow-2` | `population.carrying-capacity` | Immortal agents, no replacement, and no reproduction |
| Survivorship | `young-frontier`, `long-lived`, `scarce`, `seasonal-migration` | `age-at-death.survivorship` | Finite varied lifespans and replacement; one seasonal world |
| Price equilibrium | `overlapping-peaks`, `scarce-markets`, `four-markets`, `split-centers` | `price.equilibrium` | Immortal agents with sugar, spice, and bilateral trade |
| Tribes | `three-way-mixed`, `two-way-mixed`, `opposite-quadrants`, `three-quadrants` | `tribe.convergence` twice and `tribe.diversity` twice | Cultural tagging; mixed starts for convergence and quadrant-separated starts for diversity |

Scenarios explicitly pin the mechanics their targets require and disable
unwanted hazards such as disease, pollution, combat, lending, and unrelated
spice or seasonal behavior. The two egalitarian income intervals are both
enabled because DTL's endowment machinery otherwise creates a zero-spice
time-to-live edge case even when spice metabolism is disabled.

## Source of truth

`tools/generate_scenario_pool.py` owns the ordered scenario definitions and
derives the duo target assignments from them. Both manifest pools are generated
output. From the repository root:

```console
.venv/bin/python tools/generate_scenario_pool.py --write
.venv/bin/python tools/generate_scenario_pool.py --check
.venv/bin/python tools/generate_scenario_pool.py --emit-configs
```

`--write` changes only the `solo-ladder` and `duo-ladder` scenario pools and
preserves the rest of `coworld_manifest.json`. `--check` exits nonzero and
summarizes drift.
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
greedy baseline, evolved ceiling, skill gradient, and role.

A scenario passes when its evolved ceiling is at least `0.50` — the target is
demonstrably approachable in that world. The evolved score is a lower bound on
what is achievable, so a pass is trustworthy; a failing scenario must be
retuned or replaced before rotation, and passing one member never waives
validation for another member of its family.

The gradient (ceiling minus null floor) classifies rather than gates:

- **`skill`** (gradient ≥ `0.05`): a competent ruleset visibly beats doing
  nothing; these scenarios differentiate the ladder.
- **`anchor`** (gradient < `0.05`): the null ruleset already matches the
  target, typically because the world is close to the regime that generated
  it. Anchors stay in the pool deliberately — they are regression guards. A
  policy that matches them loses nothing, while a policy that *breaks* them
  scores worse than the baseline and is punished for it. First observed
  2026-08-13: the entire wealth-skewed family probed as anchors (null floors
  0.96–0.99), because an engine-generated target paired with its native
  regime is nearly self-fulfilling.

The shipped pool's full probe table lives in
[`docs/probe-reports/2026-08-14-solo-ladder-pool.md`](probe-reports/2026-08-14-solo-ladder-pool.md):
18 anchors, 6 skill scenarios, all 24 passing the ceiling gate.
