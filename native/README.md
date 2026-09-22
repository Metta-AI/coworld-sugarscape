# Native Sugarscape core

This directory contains the first deterministic Nim simulation core. Its v1
wire schema supports a single resource and a fixed population.

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
startup, input parsing, snapshot encoding, and output.

Snapshots contain x-major cells, agents sorted by ID, the current shuffled
`liveOrder`, exact ordered candidate lists exported from DTL, and the complete
Python `random.Random` MT19937 state. Reloading a snapshot continues the same
random stream.

Cells grow first. The engine shuffles the agent list, then processes each agent
sequentially. It shuffles the four cardinal rays within the agent's vision and
movement range, with toroidal wrapping. The agent selects the cell with the
most sugar, then the shortest distance. It stays put only when no candidate is
available. Movement, harvesting, and metabolism update the world immediately.

This first mode has one resource and a fixed population. It does not implement
death, replacement, reproduction, trade, lending, disease, pollution, seasons,
combat, leaders, or SugarLang policies. The closed snapshot schema rejects
additional fields, modes, RNGs, and Gaussian cache state.
