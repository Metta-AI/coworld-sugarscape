# Native research variants

The research collection runs reviewed study implementations alongside the existing DTL worlds.
It currently exposes nine engines through 56 named research variants.
A research controller submits one parameter object, then the native model runs to its declared horizon.
The simulation's agents retain their original behavior.

| Study | Registered cases | Native runtime | Scientific boundary |
| --- | --- | --- | --- |
| McCulloch 2022 | Three references and one calibration challenge | Study Python implementation, Python 3.11.14 | Preserve initialization collisions and inactive occupants. Calibration scoring is a Coworld adaptation. |
| Carrella 2021 | One reference | Study Python reconstruction, Python 3.11.14 | Matches the retained reconstruction; Python randomness differs from author NetLogo. No estimator-fitting claim. |
| Dogan 2026 | Slow, balanced and fast baseline references | Author Mesa model, Python 3.12.4 | Unpublished working paper. Preserve the original levy semantics; include off-grid owners in accounting. |
| Izquierdo 2009 | Five- and six-transition return witnesses | Study formal model, Python 3.11.14 | Controlled constructive paths, not unbiased stationary samples. |
| Brearcliffe 2020 | Sixteen ordered strategy pairs under each of two learning settings | Original NetLogo 6.1.1 model and Java recorder | Released-code and manuscript learning parameters remain separate variants. Aggregate recording only. |
| Oremland 2014 | Two tax-clock phases crossed with clipped/unclipped payments | Study NetLogo 5.3.1 reconstruction and original batch recorder | Reconstructed method; 200-entry uniform 25% policy, 50 transitions, endpoint measurements only. |
| Thaler 2019 | Four implementations crossed with baseline/rebirth | Original Haskell kernels, GHC 8.4.3 | 1,000 returned observations. Fixed author seed 42. Concurrent schedules differ; shared hosted timings are not historical scaling evidence. |
| Quera 2025 | One forward reference | Author Julia 1.11.3 model and qualified dependency lock | 50 native stored states, 49 transitions; preserve native survival and occupancy. No training/gradient claim. |
| Lima 2024 | One container-scenario reference | Original two NetLogo 6.0.4 worlds, JaCaMo and MySQL 5.7 | Both 1,000-step models, native routing and identity accounting. Colocated native processes; no original host-GUI or spontaneous AgentSpeak re-entry claim. |

Thaler records returned observable-agent counts, not an independent reconstruction of live internal state.
Its logical frame indices 1–1,000 correspond to native times 0–999.
The native kernels retain fixed seed 42; the episode seed is not substituted into them.

Lima preserves original model, AgentSpeak, API and router source bytes.
Its native models keep separate clocks and unseeded random streams; the episode seed does not replace them.
The native services share one game container instead of the paper's multi-container deployment.
API and SQL bind to private loopback; the game maps their original hostnames locally.
The wrapper disables Flask's development reloader and relocates MySQL data, socket, PID and export directories.
The original PHP dashboards remain preserved source; Coworld uses its own replay viewer.
Neither this deployment nor its CPU quota establishes historical performance equivalence.
The reference retains both complete native logs, a quiescent SQL snapshot and exported AgentSpeak files.
Its population metric counts agents loaded in native models; queued identities are recorded separately.
No shared spatial timeline, unreported sugar state or Gini is reconstructed.


Each replay records the source commit and file hashes, resolved parameters, seed, engine and interpreter.
Julia frames retain all six native arrays, including dead agent slots and occupancy flags.
Julia's `vision_probability` determines both vision probabilities as `p` and `1-p`.
Its dependency lock comes from the qualified forward study, not an author-supplied historical environment.
NetLogo episodes additionally identify runtime jars, recorder classes, native seed mapping, executed model and raw output hashes.
Seeds and authentication tokens are withheld from player observations.
No native source or dependency is downloaded at episode startup.

Reference variants accept `{"type":"action","parameters":{}}` and score zero.
They are experiments, with no competitive ordering implied by that score.
`calibrate-mcculloch` accepts maximum metabolism 1–4 and vision 1–16.
Its score is `1 / (1 + abs(final_population - 30))` after 100 transitions.
This objective and parameter-selection interface are explicitly Coworld adaptations.

## Run a prospective comparison

Install the game environment, then the qualified native workers:

```bash
uv sync
.venv/bin/python tools/setup_research.py
.venv/bin/python tools/setup_netlogo_research.py --javac /path/to/jdk11/bin/javac
export COWORLD_JAVA=/path/to/jdk11/bin/java
PYTHONHASHSEED=0 .venv/bin/python tools/research_experiments.py \
  --variant paper-mcculloch-1-1 --variant paper-mcculloch-4-7 \
  --seeds 1729 1730 1731 --out /path/to/new-evidence-directory
```

For host execution of Quera, install Julia 1.11.3, then instantiate the pinned forward project:

```bash
export COWORLD_JULIA=/path/to/julia-1.11.3/bin/julia
export COWORLD_JULIA_DEPOT=/path/to/research-julia-depot
JULIA_DEPOT_PATH="$COWORLD_JULIA_DEPOT" JULIA_NUM_PRECOMPILE_TASKS=1 JULIA_PKG_PRECOMPILE_AUTO=0 \
  "$COWORLD_JULIA" --startup-file=no --project=src/coworld/research_sources/quera_2025 \
  tools/setup_quera_research.jl src/coworld/research_sources/quera_2025
```

The packaged game performs this setup at build time and executes offline.

For the isolated Lima runtime and its native architecture qualification:

```bash
docker build --platform linux/amd64 --target lima -t sugarscape-lima-runtime .
# Use a new evidence directory for every run.
docker run --rm --network none --cpus 2 --memory 4g \
  -v /absolute/new-evidence:/evidence sugarscape-lima-runtime \
  python /opt/lima/lima_runner.py /evidence/native
```

The packaged public-protocol qualification runs:

```bash
docker run --rm --network none -v "$PWD/tests:/qualification:ro" GAME_IMAGE \
  python /qualification/verify_lima_system.py /tmp/new-lima-proof
```

The research runner accepts `--timeout-seconds 3300` for this complete native architecture.
The native models still execute their full 1,000-step horizons; this option only bounds waiting.


The runner uses separate real game and baseline-player processes over the public WebSocket protocol.
It retains requests, configs, game/player logs, results, replay and a summary with replay hashes.
Existing output directories and repeated variant/seed selections are rejected.
An explicit `--timesteps` is a smoke-duration override and remains marked in results and replay.
Oremland's native evaluator requires exactly 50 transitions.
A single episode is not the full replication ensemble or training campaign.

For the packaged path, use `coworld build`, then:

```bash
coworld run-episode dist/coworld_manifest.json \
  --variant paper-mcculloch-4-7 --output-dir /path/to/new-container-evidence
```

The game image contains qualified Python workers, both NetLogo runtimes, Haskell executables, the Julia forward environment and Lima's native process stack.
The bundled baseline recognizes the observed research protocol; other players must implement `sugarscape-research/1`.
The Ruleset Studio remains a SugarLang authoring surface and lists only compatible variants.
The live viewer reports execution status and recorded aggregate observations.
Native snapshots are published after bounded execution, not as spatial live animation.
The static replay viewer displays native cells and agents when recorded.
Brearcliffe displays aggregates; Oremland displays its native endpoint. Neither receives invented spatial animation or Gini.

## Leagues and rapid variants

Reuse the platform's variant catalog and league scheduler.
James Boggs's merged work already supplies scenario pools, qualifiers, Ruleset Studio and hosted configuration resolution.
The merged experiment runners in `tools/compare_rulesets.py` and `tools/reproduce_blueprints.py` cover DTL ruleset studies.
Use `tools/research_experiments.py` for the native paper-model collection.

Keep reference studies in an experiment collection rather than ranking their zero scores.
For a competitive parameter-selection task, create a one-seat score league selecting `calibrate-mcculloch`.
The current platform supports either Eval (`round_trigger: "new_policy"`) or continuous grading:

```json
{
  "enabled": true,
  "ranking": {"algorithm": "score", "standing_aggregation": "latest"},
  "continuous": {
    "enabled": true,
    "variant_id": "calibrate-mcculloch",
    "seats_per_episode": 1,
    "regrade_interval_minutes": null,
    "max_policies_per_round": 32
  }
}
```

This is the `settings.ladder` fragment, not a complete league-creation request.
A Softmax teammate sets the ranking and ladder document with elevated privileges.
The owner supplies the league/division identity and can rotate an existing variant pool.
Use repeated prospective seeds when evaluating policy quality; a single grade has sampling uncertainty.
Do not mix reference-zero and calibration scores into one leaderboard.
No game-owned commissioner or Conductor integration is required.
See the platform's [league contract](https://github.com/Metta-AI/metta/blob/aaa330489a54e39408e840f33d90b32b006533d2/packages/coworld/src/coworld/docs/PLATFORM_LADDER_LEAGUE.md).

Relevant merged work: [scenario pool](https://app.graphite.dev/github/pr/Metta-AI/coworld-sugarscape/16),
[Ruleset Studio](https://app.graphite.dev/github/pr/Metta-AI/coworld-sugarscape/18),
[experiment runners](https://app.graphite.dev/github/pr/Metta-AI/coworld-sugarscape/39),
[Eval ladders](https://app.graphite.dev/github/pr/Metta-AI/metta/27935).

## Richmond GPU companion

`coworld_manifest.gpu.json` defines `sugarscape-research-gpu`, with one `paper-richmond-full` reference variant.
The CPU collection remains one world with nine native adapters.
A GPU request applies to the entire game runnable, so the separate companion avoids reserving GPUs for CPU variants.
Both use the same research protocol, replay viewer and experiment runner.

Richmond runs the unchanged released benchmark v1 at `290702073492677f2fc9164419e9d5900d119e02`,
with FLAME GPU 2.0.0-rc at `19136c18629af0a52ac4355ff705596b22bedac1`.
Its original fixed seeds 0–2 execute all 84 conditions: 48 scaling, 18 occupation and 18 resolution cases.
Scaling and occupation retain 100 steps each; resolution retains three steps and nine recorded bins.
The endpoint contains all 6,600 population records, 162 resolution rows and original aggregate CSVs.
It does not invent a shared grid, hidden cell state or Gini.

The released initialization, native counters, agent ordering and transfer behavior remain unchanged.
Earlier scientific controls distinguish those released behaviors from corrected-model interpretations.
No historical V100 timing, corrected-model result, or independently seeded episode claim is made.
Non-timing rows are compared against the retained V100 archive diagnostically; a discrepancy is retained and investigated.
Reference score is zero.

Build and run the complete public game/player/spectator workflow on one compatible NVIDIA GPU:

```bash
docker build --platform linux/amd64 -f Dockerfile.research-gpu -t sugarscape-research-gpu .
docker run --rm --network none --gpus device=0 \
  -v /absolute/new-evidence:/evidence sugarscape-research-gpu \
  python /qualification/verify_richmond_system.py /evidence
```

The packaged runtime uses CUDA 11.8 and compiles for Hopper (`sm_90`).
Its real device probe requires exactly one allocated compatible GPU before the original binary starts.
Use the qualified GPU image with `coworld build --compose compose.research-gpu.yaml --template coworld_manifest.gpu.json`.
The fast certification fixture exercises the ordinary DTL container contract; it does not qualify the GPU paper method.
The separate full native system workflow above supplies that proof.

Hosted game GPU support is a separate platform change. The current deployed platform rejects game GPU requests.
Do not infer hosted Kubernetes readiness from Docker or provider GPU qualification.
The ten-paper replication evidence remains in [Metta-AI/sugarscape](https://app.graphite.dev/github/pr/Metta-AI/sugarscape/1).

Scientific evidence distinguishes source equivalence, public protocol execution,
container execution, hosted certification and full campaign completion.
A passed stage does not imply the others passed.
