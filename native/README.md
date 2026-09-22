# Native Sugarscape core

This directory contains the deterministic Nim simulation core. Its v7 wire
schema supports sugar and spice, Cobb-Douglas welfare, trait modifiers,
tagging, combat, trade, disease progression, reproduction, lending, children
inheritance, starvation, aging, population change, SugarLang movement, and
per-agent happiness. Complete episode results and replay remain on Python.

Build and test it with Nim 2.2 or newer:

```sh
nim c -d:release -o:native/bin/sugarscape-native native/sugarscape_native.nim
nim r -d:release native/tests/test_rng.nim
nim r -d:release native/tests/test_world.nim
```

The command reads one JSON snapshot from standard input and writes the final
snapshot to standard output:

```sh
native/bin/sugarscape-native step --ticks 100 < input.json > output.json
```

The [canonical Commonwealth benchmark](../docs/native-simulator.md) uses the
`bench-worker` protocol to count completed ticks across isolated worlds. A
world can complete fewer ticks than requested when its population becomes extinct.

Snapshots contain x-major cells, ID-sorted agents, and the current shuffled
`liveOrder`. They preserve DTL's ordered candidate and neighbor lists. They also
contain the 624-word Python MT19937 state and its index. The Gaussian cache must
be empty. Reloading a snapshot continues the same random stream.

Python records canonical configuration and per-seat ruleset hashes. The snapshot
also carries each normalized ruleset and prior-tick world statistics. Nim validates
and preserves this input. It cannot recompute the hashes from a snapshot.

Both resources grow first. The engine shuffles the agent list, then processes
each agent sequentially. It shuffles the four cardinal rays within the agent's vision and
movement range, with toroidal wrapping. The agent ranks cells with its submitted
SugarLang policy, then the shortest distance. Null policies use DTL's stock
Cobb-Douglas welfare. Movement, harvesting, and metabolism update the world
immediately.

Movement, vision, and both metabolism traits retain their post-depression base
values and separate signed modifiers. Each action derives the effective value
as `max(0, base + modifier)`. Disease definitions, ordered infection records,
immune state, and infected membership round-trip in snapshots. Incubation, repeated activation, immune
adaptation, recovery, and transmission preserve DTL ordering and RNG draws.

`deaths` contains the most recently completed tick's removals in DTL removal
order. Starvation clears the occupied cell immediately and skips aging. Aging
increments age before checking finite `maxAge`.

Tagging shuffles DTL's ordered neighbors, including duplicates on wrapped small
grids, copies one tag bit per occupied neighbor, and updates tribes immediately.
Combat applies eligibility, retaliation, capped two-resource loot, immediate
death, and end-of-tick removal order. Inheritance may be `none` or `children`.

Trade preserves cached marginal rates of substitution, base-metabolism lethal
checks, repeated transactions, and DTL attempted-price metrics.

Reproduction preserves DTL's per-field deterministic inheritance, global seat
draw, kinship relations, newborn harvest, and birth-tick action suppression.
Lending preserves ordered loan lists, repayment, refinancing, and children debt
inheritance. Dead-creditor tombstones retain the relations needed after resume.
Ordered friend state and all five happiness components also round-trip and update
with DTL ordering.

This slice does not implement replacement, scheduled disease introduction,
pollution, seasons, leaders, or non-children inheritance. It evaluates the
complete validated SugarLang movement language carried by the snapshot. The
closed snapshot schema rejects additional fields, RNGs, and Gaussian cache state.
