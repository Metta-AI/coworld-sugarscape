# Sugarscape compatibility contract

## Authority and scope

This repository is a native Nim port of the Digital Terraria Lab (DTL)
Sugarscape implementation at commit
`a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8`.

That pinned implementation is the behavioral oracle. Epstein and Axtell's
canonical Sugarscape rules explain the model, but they do not override behavior
in the pinned DTL source. Where the literature and implementation differ, this
port reproduces the implementation.

Compatibility covers:

- configuration parsing, legacy option aliases, normalization, and validation;
- seeded random-number generation and every operation that consumes randomness;
- environment construction, cell ranges, wraparound, seasons, growback,
  pollution, and resource accounting;
- agent initialization, activation order, movement, collection, metabolism,
  tagging, trade, reproduction, lending, disease, aging, death, inheritance,
  replacement, happiness, social networks, and runtime statistics;
- the `Agent`, `Asimov`, `Bentham`, `Temperance`, and `Leader` decision models;
- aggregate and per-agent JSON and CSV logs, including key order, whitespace,
  numeric formatting, delimiter placement, and termination behavior;
- deterministic replay from the same normalized configuration and seed;
- environment-file loading and the headless `--conf` configuration-file
  workflow.

The DTL Tk GUI is a presentation layer, not part of byte-level output
compatibility. The Coworld browser spectator exposes the core resource grid,
pollution, selectable agent attributes, social relationships, live statistics,
wealth histogram, Lorenz curve, and replay controls without changing simulation
state or random-number consumption.

The upstream desktop GUI, screenshots, profiling hooks, diagnostic debug text,
and individual command-line configuration override flags are outside the
compatibility boundary. They do not affect the canonical headless model state
or logs used by Coworld.

## Core loop

The simulation uses asynchronous, shuffled activation. For each timestep:

1. Stop if the configured maximum timestep has already been reached.
2. Increment the timestep.
3. Stop if the simulation was ended, or the population is empty and
   `keepAlivePostExtinction` is false.
4. Update seasons, pollution, and cell resource growback.
5. Shuffle living agents with the compatibility RNG.
6. Add diseases whose scheduled start timestep has arrived.
7. If enabled, let the `Leader` compute predetermined moves.
8. Activate each non-leader agent in shuffled order.
9. Remove dead agents and create configured replacements.
10. Compute aggregate and optional experimental/control-group statistics.
11. Emit aggregate and per-agent log records using the upstream boundary rules.

Each normal agent activation preserves this order:

1. choose and perform a move;
2. refresh immediate neighbors;
3. collect cell resources;
4. receive universal income;
5. metabolize resources and stop immediately on death;
6. tag neighbors;
7. trade;
8. reproduce;
9. lend and service debt;
10. transmit, progress, or recover from disease;
11. age and stop immediately on death;
12. refresh visible cells;
13. update happiness;
14. update runtime statistics;
15. update decision-model state.

No simultaneous-action approximation is compatible.

## World and agents

- The world is a rectangular lattice with at most one agent per cell.
- Cardinal and radial vision/movement modes, von Neumann and Moore immediate
  neighborhoods, and optional toroidal wraparound behave exactly like the
  oracle.
- Sugar and spice capacities are constructed from configured peaks or loaded
  from an environment JSON file.
- Agent endowments, sexes, tags, racial tags, immune systems, decision models,
  placement cells, diseases, and replacement endowments consume randomness in
  oracle order.
- Movement candidates are filtered, valued, shuffled, and ranked exactly as in
  the oracle. A caller-provided predetermined cell bypasses internal selection
  exactly where the upstream `predeterminedMove` hook does.
- Rule-triggered interactions after movement are not promoted into new player
  actions. In the default Coworld contract each policy chooses destinations
  for one initial agent; the native rules continue to perform trade,
  reproduction, combat, lending, tagging, and disease behavior.

## Termination and scoring

DTL Sugarscape has no native win condition. A run stops at its configured
timestep, or at extinction unless keep-alive behavior is enabled. The native
runtime statistics and logs are compatibility outputs, not a newly invented
reward.

Coworld grading is additive and derives scores from recorded canonical state.
It must not mutate the simulation or consume random numbers. The default
Coworld policy contract opens one authenticated player connection per initial
agent. Population-by-decision-model slots remain available as a non-default
adapter mode.

## Configuration and outputs

- Unknown JSON keys are ignored, as in the oracle.
- Missing keys receive the oracle's command-line defaults, not `config.json`
  defaults.
- Top-level `sugarscapeOptions` is accepted.
- `agentEthicalTheory` and `agentEthicalFactor` retain their upstream alias
  behavior.
- Validation preserves upstream sorting, clamping, special negative values,
  timeframe normalization, and RNG consumption.
- Seed `-1` is nondeterministic; every integer seed reproduces CPython 3.12's
  `random.Random` sequence used by the oracle.
- JSON output is byte-identical to CPython 3.12 `json.dumps` for values emitted
  by the simulation. CSV headers and rows are byte-identical as well.
- The final record and closing bracket preserve the oracle's special handling;
  a structurally equivalent reserialization is insufficient.

## Variant and implementation order

Compatibility is developed in dependency order. These are test partitions, not
alternate semantics:

| Layer | Depends on | Compatibility surface |
| --- | --- | --- |
| `base` | none | config, CPython RNG, grid, sugar, movement, metabolism, aging, logs |
| `spice` | base | spice welfare and dual-resource metabolism |
| `demography` | base | reproduction, inheritance, replacement, friends |
| `culture` | demography | tags, tribes, races, group bias |
| `economy` | spice, demography | trade, lending, debt, universal income |
| `health` | demography | disease, immune systems, depression, zombie virus |
| `ecology` | base, spice | seasons, pollution formation and diffusion |
| `ethics` | all prior layers | Asimov, Bentham variants, Temperance, Leader |
| `full` | all layers | every shipped example and mixed-model determinism fixture |
| `coworld` | full | player-policy RPC, health/results, compact replay artifact, static browser viewer |

The default executable exposes the full upstream configuration surface.
Layer names organize verification; users do not opt into a different ruleset by
selecting a layer.

## Fidelity gates

A layer is complete only when:

1. focused state-transition tests match the Python oracle;
2. JSON and CSV fixtures are byte-identical for representative seeds;
3. same-seed repeated Nim runs are byte-identical;
4. the relevant upstream example configurations match through termination;
5. release-mode benchmark results show the native layer is faster than the
   pinned CPython 3.12 oracle on the same machine and configuration;
6. optimizations do not change random calls, floating-point operation order,
   collection iteration order, log ordering, or observable state.

The full port is complete only when all 29 upstream example configurations,
the mixed-model determinism configuration, aggregate logs, agent logs, the
headless configuration-file CLI, Coworld adapters, and spectator/replay state
have been verified.

## Performance constraints

The implementation uses contiguous value storage and stable integer IDs for
cells, agents, diseases, and relationships. Hot loops avoid reference chasing,
temporary allocations, and hash-table iteration. Range tables and static
neighborhood data are precomputed. Release builds use the fastest safe Nim
memory-management mode demonstrated by parity and benchmark tests.

Correctness comes first: no optimization may reorder floating-point operations
or random-number consumption relative to the oracle. Benchmarks always run
outside the byte-comparison process and never enable alternate simulation
semantics.

Optimized builds disable fused multiply-add contraction because CPython rounds
after each primitive floating-point operation. Python integer-versus-float
provenance is observable in logs and must be preserved even when the numeric
values compare equal.
