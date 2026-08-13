# Solo-ladder scenario pool

**Status:** implemented (2026-08-13); reachability gate and deploy pending
**Date:** 2026-08-13
**Owner:** James Boggs

## Problem

The ladder league (`league_620a74a7…`, round every 5 minutes, EWMA score
ladder with 3-hour half-life) schedules its rounds on the `solo-wealth`
variant. That variant pins one target (`wealth.skewed-gini-0.5`) and no
config overrides, so every ranked episode runs the identical DTL default
map with the identical target; only the seed varies. Rulesets can overfit
one world/target pair, and the ladder measures memorization rather than
the design-brief goal (§8 of `.sugarscape-v3-brief.md`): rank the *most
explanatory ruleset generator* — a submitter who reads the observation and
adapts.

The machinery for per-round variety already exists and is tested:
`resolve_episode_config` (`src/coworld/config.py`) accepts a
`scenario_pool`, picks `pool[seed % len(pool)]` deterministically without
consuming simulation randomness, applies that scenario's
`config_overrides`, and adopts its `targets`. No variant uses it yet.

## Goals

- Ranked rounds draw from a large, varied, *validated* set of
  world/target scenarios.
- Every shipped scenario is demonstrated reachable with a real skill
  gradient before entering rotation.
- Zero changes to platform code or the scheduler; the pool is pure
  manifest data plus repo tooling.

## Non-goals

- Multi-seat pooled play (`duel-4seat` is unchanged).
- New targets or changes to the target catalog, scoring, or measurement.
- Random scenario *generation* at episode time — the pool is a fixed,
  curated list; the only per-episode randomness remains the seed.

## Decisions and rationale

### D1: Full-breadth variation (environment + mechanics + target)

Scenarios vary the map (peaks, geometry, regrowth, seasons), the
mechanics regime (trade, tagging/tribes, replacement, max-age), agent
populations/endowments, AND the assigned target — all 7 catalog targets
appear where mechanics support them.

*Why:* target variety is what forces submissions to be generators.
Environment-only variation leaves one scoring variable, and a wealth-only
specialist stays competitive. The design brief's pooled-variant concept
exists precisely to measure cross-scenario explanatory power inside one
league. The cost — some target/mechanics combinations are unreachable —
is handled by D5 (every scenario is probed, and each family starts from
its target's native mechanical regime).

### D2: 24 scenarios, individually validated

*Why 24:* at a 5-minute round cadence the pool cycles in ~2 hours while
the EWMA half-life is 3 hours, so standings always aggregate across many
scenarios — memorizing any single one is near-worthless even at this
size. And 24 is small enough that the evolutionary reachability probe can
run against *every* scenario (not a sample) in one overnight batch, which
is what "robust" means here: no scenario ships on the assumption that its
archetype-mates being reachable implies it is.

### D3: New `solo-ladder` variant; `solo-wealth` unchanged

*Why:* `solo-wealth`'s name and description honestly describe a simple
fixed-target variant, and it should stay available for casual/manual play
and as the stable simple case. The league is repointed by patching its
commissioner config (`default_variant_id: "solo-ladder"`) via
`coworld patch-commissioner` after the new coworld version is canonical.
The cost is one extra deploy step and a brief window where the league
still schedules `solo-wealth`; the scheduler follows the canonical
version automatically, so the window closes as soon as the patch lands.

### D4: Generator script is the source of truth

`tools/generate_scenario_pool.py` holds the 24 scenario definitions as
explicit Python data and writes them into the manifest.

*Why:* 24 scenarios ≈ 400+ lines of JSON; hand-editing that inside
`coworld_manifest.json` invites drift and copy-paste errors, and the
probe harness needs per-scenario *merged* configs anyway. One script
producing both artifacts (manifest pool + standalone probe configs)
guarantees they agree. A `--check` mode makes drift mechanically
detectable in CI/tests. The generator is deterministic data, not random
jitter — curation stays reviewable in the script's diff.

### D5: Reachability gate before rotation

`tools/probe_pool.py` runs the existing evolutionary probe
(`tools/probe_reachability.py`, unchanged — it already accepts
`--config`) over all 24 merged configs and writes one summary table:
null-ruleset floor, greedy-welfare baseline, and evolved ceiling per
scenario.

*Shipping criteria (revised 2026-08-13 after the first probe results):*
- ceiling ≥ 0.5 — the target is practically approachable in this world.
  This is the only hard gate.
- ceiling − null floor ≥ 0.05 — originally a second hard gate, now a
  *classifier*: scenarios at or above it are `skill` scenarios that
  differentiate the ladder; scenarios below it are `anchor` scenarios.

*Why the revision:* the first probe table showed the entire
wealth-skewed family with null floors of 0.96–0.99 — an engine-generated
target paired with its native regime is nearly self-fulfilling, so no
ruleset can add much. James's call (2026-08-13): keep these scenarios
anyway. They prevent regression — a policy that hits them may
generalize, and a policy that *can't* hit what the null ruleset hits is
worse than baseline and should be scored accordingly. Anchors compress
score spread between competent entrants but never invert an ordering.

*Why ceiling still gates:* the probe's best score is a lower bound on
the achievable ceiling, so passing proves reachability; it can never
disprove it. A scenario failing the ceiling gate is retuned or replaced
before deploy — never shipped "because the family passed."

## The pool: 6 families × 4 variations

Each family is anchored to the mechanical regime its target was
generated under (`targets/*.json` `generation` blocks name the DTL
example config; see `src/sugarscape/examples/`). Within a family, the
four variations perturb the world so no two scenarios share a map:
peak count/coordinates/heights, grid size (40–60), regrow rates,
`startingAgents` (200–400), vision/movement/metabolism ranges, seasons.

| Family | Target(s) | Regime anchor | Variations |
|---|---|---|---|
| Wealth, skewed | `wealth.skewed-gini-0.5` | `agent_replacement.json`: `agentReplacements`, `agentMaxAge` [60,100] | default twin peaks; single mega-peak; four-corner peaks; scarce cap-2 lowland |
| Wealth, egalitarian | `wealth.egalitarian` | same replacement regime | distinct maps from the skewed four + tighter/wider vision & metabolism ranges |
| Carrying capacity | `population.carrying-capacity` | regime actually used by `tools/generate_targets.py`: immortal agents (`agentMaxAge` [-1,-1]), no replacement, no reproduction | regrow rate 1 vs 2; grid 40–60; agents 200–400 |
| Survivorship | `age-at-death.survivorship` | replacement + finite max-age | varied `agentMaxAge` ranges; map scarcity; one seasonal world (`environmentSeasonInterval`) |
| Price equilibrium | `price.equilibrium` | `trade_basic.json`: spice + trade on, `agentMaxAge` [-1,-1] | metabolism ranges; peak separation (sugar/spice overlap vs opposite corners) |
| Tribes | `tribe.convergence` ×2, `tribe.diversity` ×2 | `cultural_tagging.json`: tagging on, `environmentMaxTribes` | convergence: mixed start; diversity: quadrant-separated tribes (`environmentTribePerQuadrant`, `environmentStartingQuadrants`) |

Concrete parameter values are chosen at implementation time inside the
generator, guided by the anchor example configs, and are then subject to
the D5 gate — the probe table, not the author's intuition, decides
whether a parameterization ships.

*Correction (2026-08-13, found during implementation):* the
carrying-capacity anchor is **not** `constant_growback.json` as first
written. `tools/generate_targets.py` overrides that example to immortal
agents when generating `population.carrying-capacity` (finite age with
no replacement and no reproduction would simply depopulate the world).
The family's regime is therefore immortal agents, no replacement, no
reproduction — variation lives entirely in the world parameters. Where a
target's recorded example config and `generate_targets.py` disagree, the
generator script is authoritative: it is what actually produced the
histogram.

Similarly, `probe_pool.py` invokes `probe_reachability.py` as a
subprocess per scenario rather than importing its internals — reusing
the probe's CLI contract keeps one copy of the evolutionary loop and
leaves the probe byte-for-byte unchanged.

**Explicit-pin rule:** every scenario explicitly sets the mechanics its
target depends on *and* pins hazards it does not want, rather than
inheriting DTL defaults. This matters: the pinned DTL defaults include
surprises like `startingDiseases: 50`. The `solo-ladder` base
`game_config` pins the common ground (e.g. `startingDiseases: 0`,
`timesteps: 1000`, `measurement_window: 100`); scenario
`config_overrides` layer on top (`resolve_episode_config` applies base
first, then the drawn scenario's overrides).

## Manifest shape

```jsonc
{
  "id": "solo-ladder",
  "name": "Solo Ladder",
  "description": "One scientist, one drawn world: 24 validated scenarios spanning all seven targets.",
  "game_config": {
    "seed": -1,
    "seats": 1,
    "players": [{"name": "Scientist"}],
    "timesteps": 1000,
    "measurement_window": 100,
    "startingDiseases": 0,
    "scenario_pool": [
      {
        "id": "wealth-skewed.twin-peaks",
        "description": "…",
        "config_overrides": { "...": "..." },
        "targets": ["wealth.skewed-gini-0.5"]
      }
      // … 23 more
    ]
  }
}
```

Notes:
- `id`/`description` inside pool entries are ignored by
  `resolve_episode_config` (it reads only `config_overrides` and
  `targets`) and serve as in-manifest documentation; they also give the
  generator and probe reports stable names.
- `config_overrides` may not set `seed` or `scenario_pool`
  (`config.py` rejects both).
- Every scenario declares `targets` explicitly (1 entry, seats=1) —
  no scenario relies on the `DEFAULT_TARGET_ID` fallback.
- `startingAgents` per scenario; divisibility by seats is trivial at 1.

## Tooling

### `tools/generate_scenario_pool.py`

- Scenario definitions as explicit Python data structures.
- `--write`: rewrites the `solo-ladder` variant's `scenario_pool` inside
  `coworld_manifest.json` (template, repo root), preserving all other
  manifest content and formatting conventions (2-space indent).
- `--check`: exits non-zero with a diff summary if the manifest pool
  differs from the generator's output.
- `--emit-configs <dir>` (default `build/scenario-pool/`): writes one
  standalone merged game config per scenario
  (base `game_config` + `config_overrides` + `targets`, no
  `scenario_pool` key and no `seed` — the probe supplies its own fixed
  episode-seed set) suitable for `probe_reachability.py --config`.

### `tools/probe_pool.py`

- Loops `probe_reachability.py` over every emitted config (one
  subprocess per scenario, keeping the probe byte-for-byte unchanged),
  with per-scenario budget flags
  (defaults: `--population 24 --generations 12 --seeds 11,42`).
- Writes `build/probe-pool/report.json` plus a rendered table
  (scenario id, null floor, greedy score, evolved ceiling, gradient,
  pass/fail against the D5 thresholds) and exits non-zero if any
  scenario fails.

## Tests (offline, in `tests/`)

- All 24 scenarios resolve: for each pool index, a seed selecting it
  passes `resolve_episode_config` → `build_dtl_config` (this runs DTL's
  `verifyConfiguration`, catching invalid option combinations) and
  `resolve_seat_targets` yields 1 target.
- Generator drift: `--check` passes against the committed manifest.
- One short episode per family (6 episodes, reduced `timesteps` via
  test-side override) runs to completion and produces a valid results
  payload.
- Pool invariants: 24 entries, unique ids, unique maps (no two
  scenarios with identical `config_overrides`), every target id exists
  in the catalog, no scenario sets `seed`/`scenario_pool`.

## Deploy plan (after implementation + probe gate)

1. Overnight `tools/probe_pool.py` run; retune/replace failures; commit
   the final pool + probe report.
2. Version **3.1.0** (new variant = feature bump), then the standard
   three-command flow: `coworld build` → `coworld certify` →
   `coworld upload-coworld --wait-hosted-smoke`.
3. `coworld patch-commissioner` on `league_620a74a7…`: set
   `default_variant_id: "solo-ladder"`.
4. Verify: next scheduled rounds report varied `scenario_index` values
   and per-episode targets in results/replays.

## Risks

- **Unreachable pairings slip through:** mitigated by probing every
  scenario, not archetypes; the probe is a lower bound, so passes are
  trustworthy, and fails are conservative (may retune a genuinely fine
  scenario — acceptable).
- **Runtime budget:** bigger grids/populations cost wall-clock; cap at
  60×60 / 400 agents (comfortably inside the 20-minute episode
  timeout; certification smoke stays on the small fixture).
- **Ladder standings mix scenarios of differing difficulty:** intended
  — EWMA over many rounds is the design-brief mechanism for exactly
  this; `min_episodes_per_entrant: 4` plus the 3-hour half-life keeps
  any single hard draw from dominating a standing.
- **League/manifest disagreement window during repoint:** brief and
  benign; rounds during the window run `solo-wealth` as today.

## Documentation

- `docs/SCENARIOS.md`: what the pool is, the family table, how
  scenarios are drawn (`seed % 24`), how to regenerate (`--write`),
  verify (`--check`), and re-probe (`probe_pool.py`) — with the D5
  shipping criteria stated.
- README: one-paragraph pointer under the v3 section.
- This design doc updated if implementation reveals changes.
