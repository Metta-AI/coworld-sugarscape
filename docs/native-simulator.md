# Native Sugarscape simulator

The Nim simulator implements the first parity slice of the pinned DTL
Sugarscape engine. It exists to establish correctness and measure the ceiling
of a native simulation loop before adding the remaining mechanics.

The current mode is `reduced_two_resource_v7`. It supports sugar and spice,
cardinal movement and vision, toroidal wrapping, sequential turns, welfare
ranking, harvest, metabolism, growback, tagging, combat, trade, and disease
progression. It also supports reproduction, lending, children inheritance,
starvation, aging, extinction, and multiple seats. Policies may be null or use
the exact unconditional `cell.welfare` movement rule. Trait rules may initialize
agent state. It rejects replacement, scheduled disease introduction, pollution,
seasons, non-children inheritance, and other SugarLang movement.

The adapter exports every field needed to resume the supported model:

- the pinned DTL commit, the 624-word CPython MT19937 state, and its index;
- the shuffled live-agent order;
- sugar and spice cells in DTL's x-major order, including occupancy;
- agents sorted by ID, with post-depression base traits and separate disease
  modifiers for movement, vision, metabolism, aggression, and fertility;
- cached trade state, disease definitions, ordered infection records, immune
  systems, and infected membership;
- parent, child, mate, and ordered loan relations, including dead-creditor
  tombstones needed to resume inherited debts;
- canonical configuration and seat-ordered ruleset SHA-256 hashes;
- each origin cell's candidate range and neighbors in DTL insertion order; and
- ordered starvation, aging, and combat events with agent ID, seat, age, and cause.

Python records the canonical hashes. Nim validates their lowercase SHA-256
shape and preserves them, but cannot recompute them without the source
configuration and normalized rulesets.

Native output is parsed through the same closed schema. Targeted tests and four
consecutive one-tick tests compare Nim with pinned DTL. Each boundary compares
physical state, occupancy, live order, candidates, and the MT19937 state and
index. Snapshots require an empty Gaussian cache. Separate cases force
starvation and aging for every agent. They compare event order, occupancy clearing,
survivors, and extinction. A two-resource fixture makes the spice-weighted welfare winner differ from the
sugar-only winner. Another fixture proves that exact-zero spice causes
starvation when spice metabolism is positive. Targeted one-tick fixtures compare
trade metrics, disease progression, inherited debt, births, and loan repayment
directly with pinned DTL. The Commonwealth seed-1729 gate compares every tick
through timestep 22, including its first births and loan repayments.

Build and run the focused checks:

```sh
nim c -d:release -o:native/bin/sugarscape-native native/sugarscape_native.nim
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q tests/test_native_simulator.py
```

Compare Python and Nim implementations of the same reduced contract:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/native_benchmark.py \
  --ticks 1000000 --repeats 5 --output build/benchmarks/native-v7.json
```

Both timers cover the same state transition contract and begin after world
construction. The Nim timer also excludes input parsing and output
serialization. Process startup, replay, compression, observers, and result
scoring are excluded. Every measured pair must finish with identical state.
The report uses actual completed ticks, so extinction cannot inflate throughput.
The one-million-tick parity check compares Nim with the reduced Python oracle,
not directly with DTL.

Measure the canonical Commonwealth configuration across synchronized native
processes with:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/benchmark_native_commonwealth.py \
  --ticks 1000 --worlds 8 --workers 8 --seeds 1729 \
  --output build/benchmarks/native-commonwealth.json
```

A single seed expands consecutively to the requested world count. A comma-separated
list supplies one seed per world. Each native process parses and validates its v7
snapshot, reports ready, and waits for the shared start release. The denominator is
the sum of parent-observed wave windows. Each window starts immediately before the
first start dispatch and ends when the parent receives the final finished line. This
conservative window includes barrier dispatch and result-line inter-process
communication. World construction, process startup, snapshot parsing, final state
serialization, replay, and compression remain outside it. Worker timers are reported
only as diagnostics. The report also includes actual completed ticks, per-world state
hashes, canonical configuration and ruleset hashes, source hashes, and host metadata.
Source provenance covers the benchmark driver, native adapter, schema and oracle,
configuration and ruleset loaders, and baseline player. Host metadata records CPU
affinity, the active Slurm allocation variables, and GPU names and UUIDs reported by
`nvidia-smi`. GPU inventory is empty when `nvidia-smi` is unavailable.

On an Apple M4 Pro, three paired 1,000,000-tick v7 runs measured 43,310.8
ticks/second for the reduced Python oracle and 307,292.4 for Nim. Nim was 7.10×
faster, and every pair ended in identical state. Trade, disease, reproduction,
and lending were inactive in this long-running fixture.

The full canonical configuration measured 1,014.95 aggregate ticks/second on
the same host with eight worlds and eight workers. Each world ran 1,000 ticks
from seeds 1729–1736. The run completed 8,000 ticks in a 7.882-second shared
window. This is 29.6× below the 30,000 target. A separate seed-1729 run matched
the pinned DTL final snapshot after 1,000 ticks.

On the RTX 4090 host CPU, five 10,000,000-tick v5 runs produced a median of
445,738.5 ticks/second. Results ranged from 427,982.1 to 515,866.8 on the shared
one-CPU allocation. The GPU identifies the machine class and was reserved but
unused by the simulator. Both results use the 7×7, four-agent reduced fixture
and do not qualify Commonwealth.

## Commonwealth qualification

Reduced-mode throughput does not qualify the complete Commonwealth Coworld for
the 30,000 whole-world ticks/second target. Qualification requires all of the
following evidence:

The seed-1729 Commonwealth tick-zero audit has 250 agents, including 25
depressed agents, 50 infected agents, and 50 agents with active modifiers. Its
configuration hash is
`21d01473529dff583f4c50021bb7e9aac618559c4eafb714ffba056566e3e74c`.
Its only ruleset hash is
`f13b0a218f455a9d06fe379d635043c1a5194d905e1dec1ea32f4a2efc671a37`.
Schema v7 accepts the canonical Commonwealth tick-zero world. Runtime
statistics, happiness, wellness scoring, replay, and broad fixed-seed coverage
remain outside the native contract, so this is not Commonwealth qualification.

1. The native loader accepts the canonical Commonwealth configuration and its
   bundled SugarLang policies without reducing features or population.
2. Reproduction, trade, lending, disease, tagging, combat, depression, effective
   trait modifiers, and the baseline SugarLang rule have parity tests beyond
   the current seed-1729, timestep-22 gate.
3. Multiple fixed seeds match DTL after every tick for state, random state,
   live order, deaths, runtime statistics, happiness, and wellness scoring.
4. A GPU-host benchmark runs that exact configuration across parallel worlds.
   It counts actual completed ticks over one shared wall-clock interval.
5. Simulation throughput reaches 30,000 aggregate world ticks/second. Replay
   capture and compression are measured in a separate result.
