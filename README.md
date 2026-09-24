> [!WARNING]
> **ARCHIVAL ONLY.** Everything under `archived/` is frozen: the original
> implementation at [`archived/v1/`](archived/v1/README.md), and the
> complete-but-never-implemented v2 design at
> [`archived/v2/`](archived/v2/README.md). Do not extend, release, or
> implement from either.

# Coworld Sugarscape

The repository root is reserved for the from-scratch successor (v3). Two
prior generations are retained for reference:

- [`archived/v1/`](archived/v1/) — the complete previous implementation:
  source, tests, tools, manifests, replay viewer, bundled player, and the
  pinned Python reference.
- [`archived/v2/`](archived/v2/) — a full redesign (agent-level player
  control, phased timestep, negotiation protocols) that reached
  design-complete but was backburnered on 2026-08-11 before implementation.

New implementation work belongs outside `archived/`.

Start with [`docs/what-is-a-coworld.md`](docs/what-is-a-coworld.md) — the
platform contract, current conventions, and an assessment of v1 — before
touching platform-facing code.

## Sugarscape v3

The current implementation is a Python coworld in `src/coworld/` backed by the
unmodified upstream DTL simulation, pulled in as a git submodule at
`src/sugarscape/` and pinned by commit. Each seat receives
one target and submits one declarative SugarLang ruleset; the world then runs
without player I/O. Distribution leagues score how closely the measured outcome
matches the target, while Commonwealth scores the wellness produced by a fixed
constitution.

CI runs the Python suite and workflow lint on PRs to `main` and main pushes;
every PR also builds the game image and checks its headless import. See
[`docs/dtl-sync.md`](docs/dtl-sync.md) for pinned tools, local checks, and the
upstream sync implementation status, read-only detection, and disposable
candidate preparation, and [Docker verification setup](docs/dtl-sync.md#independent-verification).
Container verification excludes timing tests and records that exclusion; host/CI
checks retain them. The [Git tree publisher](docs/dtl-sync.md#validated-git-tree-publication)
validates evidence before pushing. [PR delivery and alert recovery](docs/dtl-sync.md#pr-state-and-delivery)
include review context and persisted retry receipts, and are tested with fake services;
the [four-job workflow](docs/dtl-sync.md#sync-workflow) is implemented locally.
Hosted acceptance and activation remain pending; schedules are gated by
`DTL_SYNC_ENABLED`. The [controller module map](docs/dtl-sync.md#controller-modules)
identifies the trusted CLI, shared contracts, and delivery code. The
[rollout checklist](docs/dtl-sync.md#hosted-acceptance-and-week-one-checks) covers
activation and recovery. CI runs functional tests in parallel and performance
tests serially to avoid CPU contention in timing assertions.

New here? Start with [`docs/getting-started.md`](docs/getting-started.md) —
the game, the three leagues, local runs, the Ruleset Studio, and how to join
a league (with or without a coding agent).

Ranked distribution play uses a deterministic pool of 80 scenarios: 12
hand-tuned base worlds spanning all seven distribution targets, crossed with
mechanic packs that force rulesets to adapt to the observed world.
`solo-ladder` assigns one policy one target; `duo-ladder` seats two policies in
the same world with different global targets and independent scores.
`commonwealth` presents the same canonical world and `wellness.max` objective
every episode: the submitted ruleset is the constitution, and its score is the
summed final-window wellness of agents surviving to the final tick. See
[`docs/SCENARIOS.md`](docs/SCENARIOS.md) for the distribution catalog,
selection rule, and regeneration workflow, and
[`docs/designs/2026-08-18-commonwealth-league.md`](docs/designs/2026-08-18-commonwealth-league.md)
for the Commonwealth contract.

Clone with `--recurse-submodules` (or run `git submodule update --init` in an
existing clone) so the DTL engine is present, then set up with
[`uv`](https://docs.astral.sh/uv/): `uv sync`, then
run the offline suite with `.venv/bin/python -m pytest`. For local container
development, `docker compose up` starts the one-seat config in `config.json` and
the bundled target-aware baseline. Protocol, language, and target references are
in `docs/PROTOCOL.md`, `docs/RULES.md`, and `docs/TARGETS.md`.

Use [`ruleset-studio/`](ruleset-studio/README.md) to build, validate, save, and
Play SugarLang rulesets in a local Blockly editor with live replay handoff and
optional agent chat.

Reproducibility assumes `PYTHONHASHSEED=0`; both Dockerfiles set it, and the
server re-executes itself with that value when necessary. A recorded results or
replay seed reproduces an episode on the pinned interpreter.

## Training

`tools/training_bridge.py` runs the same pinned DTL simulator, SugarLang validator,
target resolver, and scorer without a WebSocket server. It accepts `--variant`
with `certification` or a manifest variant ID. Each reset uses a deterministic
seed and one decision per seat. The bridge hides the seed and scenario pool from
player observations. Omit `--timesteps` for the variant's exact episode length;
set it for a shorter training curriculum. The ladder and Commonwealth variants
took 29–85 seconds locally, so use a bridge response deadline of at least 120
seconds.

`--mode choice` exposes seven validated, game-owned baseline rulesets as discrete
actions, a 66-value target and public-config encoding, and typed candidates.
This is a finite policy curriculum for Metta RL and native PufferLib. It does
not cover arbitrary SugarLang programs. `--mode text` accepts the full
`{"ruleset": ...}` submission and retains exact player-visible targets and
programs for Metta post-training. Both modes return scores from `run_episode`.

From a Metta checkout with the Coworld training stack, set `SUGARSCAPE_ROOT` to
this checkout and run:

```bash
uv run --group cortex ./tools/run.py train recipes.external.coworld_metta_rl \
  command="[\"$SUGARSCAPE_ROOT/.venv/bin/python\",\"$SUGARSCAPE_ROOT/tools/training_bridge.py\",\"--variant\",\"solo-ladder\",\"--mode\",\"choice\"]" \
  players=1 max_decisions=1 response_timeout_seconds=120 \
  run=sugarscape_rl total_timesteps=128
uv run ./tools/run.py train recipes.external.coworld \
  command="[\"$SUGARSCAPE_ROOT/.venv/bin/python\",\"$SUGARSCAPE_ROOT/tools/training_bridge.py\",\"--variant\",\"solo-ladder\",\"--mode\",\"choice\"]" \
  players=1 max_decisions=1 response_timeout_seconds=120 \
  run=sugarscape_puffer total_timesteps=128
uv run --package metta-posttrain metta-posttrain collect-teacher \
  --bridge "$SUGARSCAPE_ROOT/tools/training_bridge.py" \
  --bridge-command "$SUGARSCAPE_ROOT/.venv/bin/python" \
  --bridge-command "$SUGARSCAPE_ROOT/tools/training_bridge.py" \
  --bridge-command=--variant --bridge-command solo-ladder \
  --bridge-command=--mode --bridge-command text \
  --output /tmp/sugarscape-trajectories.jsonl \
  --source-revision "$(git -C "$SUGARSCAPE_ROOT" rev-parse HEAD)" \
  --episodes 16 --seed-prefix sugarscape --players 1 --game sugarscape \
  --action-schema-revision sugarlang-v1 --max-decisions 1
uv run --package metta-posttrain metta-posttrain export \
  --trajectory /tmp/sugarscape-trajectories.jsonl --output /tmp/sugarscape-dataset
```

Use a new output path for each collection. Seed-separated train and validation
splits require at least one complete episode in each split.

## Credits

This project is based on the **Digital Terraria Lab (DTL) Sugarscape**
implementation — [`nkremerh/sugarscape`](https://github.com/nkremerh/sugarscape),
maintained by Nate Kremer-Herman and contributors, released into the public
domain under the Unlicense. v3 runs that code as-is from the `src/sugarscape/`
submodule; `src/coworld/dtl.py` is the only place the wrapper touches its import
mechanics. The archived v1 is a native Nim port of the DTL
model, with the pinned upstream source preserved as its behavioral oracle at
[`archived/v1/reference/dtl-python/`](archived/v1/reference/dtl-python/)
(full contributor list in its `CREDITS` file). The DTL model itself builds on
*Growing Artificial Societies* (Epstein & Axtell, 1996).
