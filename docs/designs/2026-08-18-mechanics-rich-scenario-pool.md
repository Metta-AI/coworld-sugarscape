# Mechanics-rich scenario pool (reachability removed)

Status: approved design, implementation in progress (2026-08-18).
Supersedes the pool structure and reachability gate described in
[2026-08-13-solo-ladder-scenario-pool.md](2026-08-13-solo-ladder-scenario-pool.md).

## Problem

The 24-scenario ladder pool was curated under a "pin only what the target
needs" principle: every mechanic not required by a scenario's target family
(spice, trade, combat, disease, pollution, seasons, reproduction outside
tribes) was explicitly zeroed, and every pool change was gated on an
expensive evolutionary reachability probe. The result is that ~83% of ranked
episodes never exercise most of the SugarLang observable surface, and worlds
are far less varied than the DTL simulation supports.

Decision: reachability is not a gate. If a target proves badly unreachable in
some scenario, that is a balance patch later, not an up-front proof
obligation. The pool should instead maximize mechanical variety per target.

## Goals

- Remove the reachability probe: tools, tests, docs, and the generator's
  probe-support mode.
- Keep the existing seven target distributions unchanged.
- Regenerate the pool as families: per target, hand-tuned base worlds crossed
  with declarative mechanic packs that turn other DTL components on.
- Keep the deterministic selection contract (`scenario_pool[seed % N]`) and
  the duo companion-target derivation.

## Non-goals

- No target or scoring changes (w1-scoring-v2 is a separate design).
- No new DTL mechanics; only existing pinned-simulation knobs are used.
- No per-episode parameter randomization; the pool stays fixed manifest data.

## Removal scope

Delete outright:

- `tools/probe_pool.py`, `tools/probe_reachability.py`
- `tests/test_probe.py`
- `docs/probe-reports/`
- `generate_scenario_pool.py --emit-configs` (existed only to feed the probe;
  `tools/benchmark_replay_viewer.py` currently imports it and must switch to
  building its merged config in memory)

Rewrite or scrub:

- `docs/SCENARIOS.md`: drop the "Reachability gate" section and the
  "disable unwanted hazards" framing; document the family × pack structure.
- `docs/TARGETS.md`, `docs/what-is-a-coworld.md`: remove probe references.
- `docs/designs/2026-08-13-solo-ladder-scenario-pool.md`: superseded note at
  the top only; the body stays as a historical record.

Explicitly untouched:

- `src/coworld/server.py` and its tests: the "viewer probe" there is the
  hosted certifier's WebSocket check, unrelated to reachability.
- `tools/generate_targets.py`: already states targets need not be reachable.

## Pool structure

`tools/generate_scenario_pool.py` remains the source of truth and the
manifest pools remain generated output, but the literal 24-scenario list is
replaced by a programmatic cross:

```
scenario = base world (hand-tuned, 2 per family) × mechanic pack
id       = <family>.<base>.<pack>     (baseline pack keeps the bare
                                       <family>.<base> id for continuity)
```

Base worlds are carried over verbatim from the current pool (the most
mechanically distinct pair of each family's four):

| Family | Bases kept | Target |
|---|---|---|
| wealth-skewed | `twin-peaks`, `scarce-lowland` | `wealth.skewed-gini-0.5` |
| wealth-egalitarian | `central-plateau`, `scarce-income` | `wealth.egalitarian` |
| capacity | `compact-regrow-1`, `sparse-regrow-2` | `population.carrying-capacity` |
| survivorship | `young-frontier`, `long-lived` | `age-at-death.survivorship` |
| price | `overlapping-peaks`, `four-markets` | `price.equilibrium` |
| tribes | `three-way-mixed` (convergence), `opposite-quadrants` (diversity) | `tribe.convergence` / `tribe.diversity` |

`survivorship.seasonal-migration` is dropped as a base because the `seasons`
pack now covers that axis.

## Mechanic packs

A pack is a declarative override delta merged onto the base world's
`config_overrides` (pack keys win). Packs apply on top of each family's
required mechanics; a pack that is a no-op for a family (already-on
mechanics) is skipped rather than emitted as a duplicate scenario.

Core packs (every family):

- **`baseline`** — no delta; today's world, bare id preserved.
- **`spice`** — spice terrain mirroring the base's sugar peaks
  (`environmentSpicePeaks` = sugar peaks at swapped coordinates, sorted into
  DTL's canonical list order, `environmentMaxSpice` = base
  `environmentMaxSugar`, `environmentSpiceRegrowRate` 1),
  `agentSpiceMetabolism [1, 4]`, `agentStartingSpice [10, 30]`. Skipped for
  price (already on).
- **`market`** — `spice` plus `agentTradeFactor [1, 1]` and trade trait
  `[0, 1]`. Skipped for price (already on).
- **`combat`** — `agentTagging true`, `agentTagStringLength 11`,
  `environmentMaxTribes 2`, `agentAggressionFactor [0, 2]`, aggression trait
  `[0, 2]`, `environmentMaxCombatLoot 2`. Tagging is required because DTL
  combat only permits prey in a different tribe (`isNeighborValidPrey`).
  For tribes, the pack adds only the aggression/loot knobs.
- **`everything`** — union of `market` + `combat` + `disease` + `pollution`
  + `seasons`, where each layer is skipped or reduced if the base already
  runs it (price keeps its own tuned spice/trade values; tribe bases keep
  their tribe counts and their existing reproduction). Reproduction is
  deliberately never *added or altered* so each base keeps its population
  regime; one chaos world per base.

Situational packs (two per family, chosen for target relevance):

- **`disease`** — `startingDiseases 40`, `startingDiseasesPerAgent [0, 3]`,
  pinned disease penalty/transmission knobs (sugar/spice metabolism penalty
  `[1, 3]`, `diseaseTransmissionChance [1.0, 1.0]`,
  `agentImmuneSystemLength 35`). The DTL default side-effect penalties
  (aggression, fertility, movement, vision) are pinned to `[0, 0]`:
  metabolism is the intended disease pressure, and the default positive
  fertility modifier would silently enable reproduction in fertility-zero
  worlds. In spiceless worlds the spice-metabolism penalty is also `[0, 0]`
  (it would create metabolism with no supply).
- **`pollution`** — `environmentSugarProductionPollutionFactor 1`,
  `environmentSugarConsumptionPollutionFactor 1`,
  `environmentPollutionTimeframe [0, 1000]`,
  `environmentPollutionDiffusionTimeframe [50, 1000]`,
  `environmentPollutionDiffusionDelay 10` (diffusion is inert without a
  positive delay; bounds are explicit and non-negative because DTL
  normalizes negative shorthand, which would break manifest/DTL value
  equality). Spice pollution factors too when the family has spice.
- **`seasons`** — `environmentSeasonInterval 50`,
  `environmentSeasonalGrowbackDelay 8` (values from the retired
  `seasonal-migration` world).
- **`reproduction`** — `agentFertilityFactor [1, 1]`, fertility trait
  `[0, 1]`, `agentReplacements 0`; finite lifespans come from the base.
  Population becomes endogenous.

| Family | Situational packs | Rationale |
|---|---|---|
| wealth-skewed | `reproduction`, `pollution` | inheritance dynamics; terrain decay vs. Gini |
| wealth-egalitarian | `disease`, `seasons` | shocks vs. enforced equality |
| capacity | `pollution`, `seasons` | eroding and oscillating capacity |
| survivorship | `disease`, `seasons` | mortality shocks; migration pressure |
| price | `seasons`, `disease` | seasonal markets; sick traders |
| tribes | `disease`, `seasons` | tribes already reproduce (fertility is on in the bases), so `reproduction` would be a no-op |

Pool arithmetic: four families × 7 packs × 2 bases = 56; price × 5 packs
(spice/market skipped) × 2 = 10; tribes × 7 packs × 2 = 14. **Total: 80
scenarios.** Selection stays `scenario_pool[seed % 80]`.

## Duo pool

Unchanged derivation: the duo pool reuses the solo list with the existing
`DUO_COMPANION_TARGETS` map and alternating target order. The
`capacity.wide-regrow-1` even-population special case disappears with that
base; any new odd starting population in a duo copy gets the same +1
adjustment rule if needed.

## Testing

- `tests/test_scenario_pool.py` updated for the new structure: generator
  `--check` round-trip against the manifest, pool size 80, id uniqueness and
  `<family>.<base>.<pack>` shape, duo target alternation.
- New pack invariants: every `combat`/`everything` scenario has tagging on;
  every `market` scenario has nonzero spice metabolism and trade; `baseline`
  ids carry no pack suffix; skipped no-op packs emit no duplicate configs.
- Smoke: each of the 80 merged configs must construct and step a short
  episode on the pinned interpreter (guards against DTL key typos), bounded
  to a handful of ticks so the suite stays fast.

## Risks

- Some target/pack combinations will score poorly for everyone (e.g. Gini
  0.5 under heavy pollution). Accepted by decision above; EWMA laddering is
  relative, and persistent pathologies are balance patches.
- New keys (`startingDiseases`, fertility ages, combat loot) must survive
  the v3 config merge and public-config disclosure; the implementation must
  verify each key reaches the simulation and appears in the resolved config
  players see.
- Pool size changes the selection modulus and pool-cycle duration; SCENARIOS
  documentation and any hard-coded 24s in tests must move to the generated
  count.
