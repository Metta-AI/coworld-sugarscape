# Native Sugarscape simulator

The Nim simulator implements the first parity slice of the pinned DTL
Sugarscape engine. It exists to establish correctness and measure the ceiling
of a native simulation loop before adding the remaining mechanics.

The current mode is `reduced_fixed_population_v1`. It supports one sugar
resource, cardinal movement and vision, toroidal wrapping, sequential turns,
harvest, metabolism, growback, and multiple seats with null SugarLang rules.
It rejects spice, death, replacement, reproduction, trade, lending, disease,
pollution, seasons, combat, finite maximum age, trait overrides, and custom
SugarLang movement.

The adapter exports every field needed to resume the supported model:

- the pinned DTL commit and full CPython MT19937 state;
- the shuffled live-agent order;
- cells in DTL's x-major order, including occupancy;
- agents sorted by ID, with movement, vision, age, and welfare inputs; and
- each origin cell's candidate range in DTL insertion order and distance.

Native output is parsed through the same closed schema. Four consecutive
one-tick tests compare the native result with the pinned Python engine. Each
boundary compares physical state, occupancy, live order, candidates, and the
complete random state. This catches latent divergence before a later tick
makes it visible.

Build and run the focused checks:

```sh
nim c -d:release -o:native/bin/sugarscape-native native/sugarscape_native.nim
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q tests/test_native_simulator.py
```

Measure the native simulation loop:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/native_benchmark.py \
  --ticks 1000000 --output build/benchmarks/native-v1.json
```

The Nim monotonic timer begins after input parsing and ends before snapshot
serialization. Process startup, Python setup, replay, compression, observers,
and result scoring are excluded. The report counts one completed world tick per
simulation step and reports single-world throughput.

On the RTX 4090 GPU host, five 10,000,000-tick runs produced a median of
1,465,047.5 whole-world ticks/second for the 7×7, four-agent reference world.
The current Nim loop runs on the host CPU; the GPU identifies the target machine
class and is not used by this reduced simulator.

This reduced result is not evidence that the complete Commonwealth Coworld
meets the 30,000 whole-world ticks/second target. The full engine must add each
rejected mechanic with tick-by-tick parity before its throughput can be
compared with that acceptance target.
