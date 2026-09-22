# Native Sugarscape simulator

The Nim simulator implements the first parity slice of the pinned DTL
Sugarscape engine. It exists to establish correctness and measure the ceiling
of a native simulation loop before adding the remaining mechanics.

The current mode is `reduced_two_resource_v3`. It supports sugar and spice,
cardinal movement and vision, toroidal wrapping, sequential turns, welfare
ranking, harvest, metabolism, growback, starvation, aging, extinction, and
multiple seats. Policies may be null or the exact unconditional `cell.welfare`
movement rule. It rejects replacement, reproduction, trade, lending, disease,
pollution, seasons, combat, trait overrides, and other SugarLang movement.

The adapter exports every field needed to resume the supported model:

- the pinned DTL commit and full CPython MT19937 state;
- the shuffled live-agent order;
- sugar and spice cells in DTL's x-major order, including occupancy;
- agents sorted by ID, with both metabolisms and every welfare input;
- each origin cell's candidate range in DTL insertion order and distance; and
- ordered starvation and aging events with agent ID, seat, age, and cause.

Native output is parsed through the same closed schema. Four consecutive
one-tick tests compare the native result with the pinned Python engine. Each
boundary compares physical state, occupancy, live order, candidates, and the
complete random state. Separate cases force starvation and aging for every
agent. They compare event order, occupancy clearing, survivors, and extinction.
A two-resource fixture makes the spice-weighted welfare winner differ from the
sugar-only winner. Another fixture proves that exact-zero spice causes
starvation when spice metabolism is positive.

Build and run the focused checks:

```sh
nim c -d:release -o:native/bin/sugarscape-native native/sugarscape_native.nim
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q tests/test_native_simulator.py
```

Compare Python and Nim implementations of the same reduced contract:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/native_benchmark.py \
  --ticks 1000000 --repeats 5 --output build/benchmarks/native-v3.json
```

Both timers cover the same state transition contract and begin after world
construction. The Nim timer also excludes input parsing and output
serialization. Process startup, replay, compression, observers, and result
scoring are excluded. Every measured pair must finish with identical state.
The report uses actual completed ticks, so extinction cannot inflate throughput.

On the RTX 4090 GPU host, five 10,000,000-tick v1 runs produced a median of
1,465,047.5 whole-world ticks/second for the 7×7, four-agent reference world.
The current Nim loop runs on the host CPU; the GPU identifies the target machine
class and is not used by this reduced simulator.

## Commonwealth qualification

Reduced-mode throughput does not qualify the complete Commonwealth Coworld for
the 30,000 whole-world ticks/second target. Qualification requires all of the
following evidence:

The seed-1729 Commonwealth world starts with 250 agents, two resources, 50
diseases, finite ages, tagging, trade, lending, fertility, and 10% depression.
Its first tick has 8 starvation deaths, 2 combat deaths, 45 trades, and 12
disease spreaders. Native v3 covers sugar, spice, welfare, starvation, and
aging only.

1. The native loader accepts the canonical Commonwealth configuration and its
   bundled SugarLang policies without reducing features or population.
2. Reproduction, trade, lending, disease, tagging, combat, depression, effective
   trait modifiers, and the baseline SugarLang rule have parity tests.
3. Multiple fixed seeds match DTL after every tick for state, random state,
   live order, deaths, runtime statistics, happiness, and wellness scoring.
4. A GPU-host benchmark runs that exact configuration across parallel worlds.
   It counts actual completed ticks over one shared wall-clock interval.
5. Simulation throughput reaches 30,000 aggregate world ticks/second. Replay
   capture and compression are measured in a separate result.
