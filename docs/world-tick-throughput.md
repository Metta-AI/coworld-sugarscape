# Whole-world throughput

The acceptance target is 30,000 completed whole-world ticks per wall-clock
second, summed across parallel environments on one GPU machine. Agent count
never multiplies this counter. The current Python engine runs on CPUs.

Run a bounded batch from the repository root:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/benchmark_world_ticks.py \
  --variant commonwealth --workers 16 --worlds 32 --timesteps 1000 \
  --output build/benchmarks/commonwealth-16.json
```

The output path must not exist. Each world uses a distinct seed beginning at
1729 and the bundled baseline policy for its target. The report records resolved
configurations, rulesets, final populations, completed ticks, result/replay
hashes, source hashes, Python version and CPU metadata.

The denominator includes process startup and shutdown, world construction,
simulation, statistics, scoring, replay compression and result transfer.
Counted ticks are actual completions; extinction does not earn unexecuted ticks.
This is an end-to-end batch measurement, not a warmed simulation-kernel measurement.
It includes neither learning nor neural-policy inference. Record GPU model,
allocation, occupancy and CPU affinity alongside reports from GPU machines.

Processes isolate DTL's global random generator and agent-class substitution.
Threads cannot provide that isolation. Worker count must not change per-world
results or replay hashes. Compare identical seed ranges and configurations
before interpreting throughput differences.

The feature compiler records each ruleset's dependencies. Agent and world
feature groups are evaluated only when referenced; candidate cells sanitize
only referenced features. DTL's time-to-live state update still runs for every
custom movement ranking, even when the policy does not read it.

## Path to the target

The pinned upstream engine schedules agents sequentially: each agent observes
mutations made by previous agents in the same tick. Parallelizing those turns
would change the model. Independent worlds are the available parallel dimension.

A native or GPU implementation needs its own per-world state and random stream,
with ordered agent turns inside each world. It must reproduce movement ties,
combat, trade, lending, reproduction, death, replacements, disease, environmental
updates and measurements. Validate trajectories against the pinned Python
reference before claiming throughput for the same game.

Keep `src/sugarscape` unchanged as the reference. Archived implementations are
not substitutes for current-game correctness or performance measurements.
