# Native Sugarscape core

This directory contains the deterministic Nim simulation core. Its v3 wire
schema supports sugar and spice, Cobb-Douglas welfare, starvation, aging, and
population decline. It remains a pre-Commonwealth parity slice until the other
mechanics listed below are implemented.

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

`bench` uses the same input and returns `ticks`, `elapsedNs`, and the final
snapshot. Its monotonic timer covers only simulation steps, excluding process
startup, input parsing, snapshot encoding, and output. `ticks` reports actual
completed ticks and can be less than requested when the population becomes
extinct.

Snapshots contain x-major cells, agents sorted by ID, the current shuffled
`liveOrder`, exact ordered candidate lists exported from DTL, and the complete
Python `random.Random` MT19937 state. Reloading a snapshot continues the same
random stream.

Both resources grow first. The engine shuffles the agent list, then processes each agent
sequentially. It shuffles the four cardinal rays within the agent's vision and
movement range, with toroidal wrapping. The agent selects the cell with the
Cobb-Douglas welfare, then the shortest distance. It stays put only when no
candidate is available. Movement, harvesting, and metabolism update the world
immediately.

`deaths` contains the most recently completed tick's removals in DTL removal
order. Starvation clears the occupied cell immediately and skips aging. Aging
increments age before checking finite `maxAge`.

This slice does not implement replacement, reproduction, trade, lending,
disease, pollution, seasons, combat, leaders, inheritance, or SugarLang
policies. The closed snapshot schema rejects additional fields, RNGs, and
Gaussian cache state.
