# Paired ruleset experiments

Compare a Ruleset Studio export against the bundled target-aware baseline before
submitting it to a league. Each seed runs two separate worlds with the same
configuration. Candidate rules apply to every seat; baseline seats use the canned
policy for their assigned target. This is not a head-to-head match.

## Run the Commonwealth preset

Save a ruleset from Ruleset Studio, or start with `rulesets/worked-example.json`.
From the repository root:

```sh
PYTHONHASHSEED=0 .venv/bin/python tools/compare_rulesets.py \
  --variant commonwealth --ruleset rulesets/worked-example.json \
  --seeds 1729 1730 1731 --out build/experiments/commonwealth-example
```

The preset is the canonical `commonwealth` configuration in
`coworld_manifest.json`, using the implemented
[Commonwealth wellness objective](designs/2026-08-18-commonwealth-league.md).
This is a ruleset comparison, not a replication of a published paper.
A paper replication needs a named experiment, original parameters, and an agreed
comparison metric before its results can be claimed.

For a short smoke run, add `--timesteps 20` and use a different output directory.
This changes the experiment duration; it does not measure the ranked preset.
Use `--variant solo-ladder` or `--variant duo-ladder` for distribution scenarios.
Scenario selection remains the engine's `seed % scenario_count` rule. Select
seeds covering the intended scenarios; a handful of seeds does not cover the
80-scenario pool.

## Inspect the results

- `comparison.json` contains the input configuration, candidate ruleset, seeds,
  per-seed measurements, and paired summaries. Delta means candidate minus baseline.
- `<seed>/config.json` records the resolved configuration, including scenario
  overrides and upstream defaults.
- `<seed>/{baseline,candidate}.rulesets.json` records each seat's exact submission.
- `<seed>/{baseline,candidate}.results.json` contains full results without
  wall-clock timings, including seat scores, histograms, and wellness components.
- `<seed>/{baseline,candidate}.replay` contains the normal compressed v3 replay.
- `provenance.json` records the interpreter, platform, both Git revisions, and
  hashes of runtime source and data. Preserve the checkout alongside the report;
  hashes identify local edits but do not reconstruct them.

The runner refuses duplicate seeds and existing output directories. A failed run
may leave partial episode artifacts; only a completed CLI run writes both summary
and provenance. Keep partial evidence and rerun into a fresh directory.

The score, population, Gini coefficient, and mean wealth summaries show means and
sample standard deviations of paired differences. One pair has no sample standard
deviation, represented as `null`. These descriptive statistics do not establish
statistical significance or guarantee performance on unseen seeds. Wellness
scores reward surviving population as well as wellness; inspect both.

For reproducibility use Python 3.13.5, the same source/data hashes and
`PYTHONHASHSEED=0`. The runner rejects an unset or different hash seed. The offline
tests verify that identical policies produce identical replays and zero deltas,
and repeating an experiment preserves deterministic results.

## Reproduce a published decision-model experiment

Nate Kremer-Herman, Ankur Gupta, and Eric Severson published
[Blueprints for Machine Ethics](https://digital-terraria-lab.github.io/assets/papers/kremer-herman%3A2024%3Ablueprints-for-machine-ethics.pdf)
in IEEE Access (2024). Section VII-A compares four homogeneous societies;
Table 3 uses 500 seeds and 5,000 timesteps. Section IX provides exact configuration
archives and identifies the engine release as v2024.1.

The published models are implemented in upstream's decision layer. Coworld's
SugarLang layer replaces that decision layer, so the comparison above does not
replicate those models. Use an untouched historical engine for that experiment:

```sh
git clone --branch Glucose/v2024.1 --depth 1 \
  https://github.com/digital-terraria-lab/sugarscape.git ../sugarscape-paper-engine
curl -LfsS \
  https://raw.githubusercontent.com/digital-terraria-lab/datasets/026e5b3632494a4abe25802c0bd3b29c6240583b/blueprints-homogeneous.zip \
  -o ../blueprints-homogeneous.zip
PYTHONHASHSEED=0 .venv/bin/python tools/reproduce_blueprints.py \
  --engine ../sugarscape-paper-engine --archive ../blueprints-homogeneous.zip \
  --seeds 158402133555746433 --timesteps 20 \
  --out build/experiments/blueprints-smoke
```

This seed is an actual archived seed. All four archived models run, with only
log destinations and the explicit smoke duration changed. Omit `--timesteps`
for the paper's full 5,000 ticks, using a fresh output directory. Each model has
a 3,600-second subprocess limit; change `--timeout-seconds` explicitly if needed.
The runner checks the exact paper engine revision and refuses local edits or
nonignored untracked files. It also checks the authors' pinned archive SHA-256
and verifies the archived configurations request 5,000 ticks.
It preserves original configurations, executed configurations, complete
trajectories, interpreter metadata, hashes, and subprocess output. The initial `request.json`
records all planned seeds, models, timeout, and duration override even if a run
times out. A final `report.json` exists only after every selected run completes.

A one-seed run validates the reproduction path. It does not reproduce the paper's
aggregate 500-seed findings. Python version and platform differences may also
prevent exact historical numerical agreement; retain that provenance. Do not
replace the current Coworld engine pin with the historical release.

Completed paper runs report monotonic wall seconds and world ticks per second.
Timing covers the historical Python subprocess, including startup and log output.
A world tick advances the entire society; it is not an individual agent step.
These CPU measurements do not establish GPU training throughput. Timings vary
between runs; compare trajectory hashes when checking reproducibility.
