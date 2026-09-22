# Whole-world throughput

The acceptance target is 30,000 completed whole-world ticks per wall-clock
second, summed across parallel environments on one GPU machine. Agent count
never multiplies this counter. The target excludes replay recording and
compression; replay overhead is measured separately. The current Python engine
runs on CPUs.

Run a bounded batch from the repository root:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/benchmark_world_ticks.py \
  --mode simulation --variant commonwealth --workers 16 --worlds 16 --timesteps 1000 \
  --output build/benchmarks/commonwealth-16.json
```

The output path must not exist. Each world uses a distinct seed beginning at
1729 and the bundled baseline policy for its target. The report records resolved
configurations, rulesets, final populations, completed ticks, result/replay
hashes, source hashes, Python version and CPU metadata.

Simulation mode creates one world per worker before a shared start signal;
`--worlds` must equal `--workers`. The denominator runs from that signal through
the last completed tick. It excludes process/world setup, observer measurements,
scoring, replay, result hashing and transfer. Intrinsic DTL statistics remain
because subsequent agent decisions consume them. Neither mode includes learning
or neural-policy inference.

Run the same seeds, worlds and timesteps with `--mode episodes` to measure the
complete episode path, including setup, observers, scoring and replay. Its
additional wall time includes all episode overhead, not only replay. Per-worker
replay phase timings identify capture and serialization costs separately;
summing those overlapping durations does not yield elapsed wall time.

Counted ticks are actual completions; extinction does not earn unexecuted ticks.
Record GPU model, allocation, occupancy and CPU affinity alongside host reports.

Processes isolate DTL's global random generator and agent-class substitution.
Threads cannot provide that isolation. Worker count must not change per-world
simulation state/RNG hashes, results or replay hashes. Compare identical seed ranges and configurations
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
