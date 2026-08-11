# What is a Coworld?

Reference document for coding agents working on the Sugarscape coworld
(researched during v2 design; still the platform-contract reference for v3).
Read this before touching platform-facing code (manifest, server routes,
results, replays, release tooling).

> **Provenance & freshness.** Researched 2026-08-06 against metta commit
> `37d4143e81` and coworld CLI `coworld-v0.1.35` (PyPI pin seen in CI:
> `coworld==0.1.35`). The platform moves fast. **Metta is the source of
> truth, not this document**: before relying on any version-sensitive claim,
> run `git -C ~/coding/metta pull` and re-verify against
> `packages/coworld/src/coworld/types.py` and
> `packages/coworld/src/coworld/docs/`. Citations into metta use file paths
> and section/function names (line numbers rot); citations into
> `archived/v1/` use line numbers (frozen).

## Definition

A **coworld** is a containerized, self-describing multiplayer game that the
Softmax platform can run competitively. Concretely it is:

1. A **game Docker image** — a long-running server that reads a JSON config,
   serves WebSocket endpoints for players and spectators, runs one episode,
   and writes JSON results plus an opaque replay artifact.
2. At least one **bundled player Docker image** — a baseline policy that
   connects to the game the same way user-submitted policies do.
3. A **`coworld_manifest.json`** describing both, plus config/results JSON
   Schemas, protocol docs, shipped variants, and a certification fixture.
4. Optionally a **static replay-viewer bundle** (self-contained web page,
   usually WASM) that renders replay bytes with no game container.

The platform (Observatory) hosts uploads, runs episodes on Kubernetes,
maintains leagues/ladders with ratings, and serves replays. User policies are
submitted as Docker images and scheduled against each other inside your game.

The `coworld` Python package at `~/coding/metta/packages/coworld/` owns the
manifest schema, local runner, certifier, and role types — everything below
that is platform contract lives there.

---

## Tier 1 — Platform contract (MUST)

### 1.1 Manifest

Source of truth: `packages/coworld/src/coworld/types.py` (Pydantic models;
`coworld_manifest_schema.json` is generated from it — never hand-edit the
JSON). Validation beyond the schema: `manifest_validation.py`. Versioned via
`apiVersion: "coworld.softmax.com/v1"` (absent ⇒ read as v0; v1 = v0 + the
discriminator). Unknown top-level keys are **rejected** (`extra="forbid"`).

Top-level fields:

| Field | Required | Notes |
|---|---|---|
| `game` | yes | see below |
| `player` | yes, ≥1 entry | bundled baseline player(s) |
| `variants` | yes, ≥1 | `{id?, name, description?, game_config}` — shipped configs leagues pick from |
| `certification` | yes | `{game_config, players}` — tiny local smoke fixture |
| `tags` | no | **if present, ≥3 entries** |
| `reporter`, `commissioner`, `grader`, `diagnoser`, `optimizer` | no | supporting roles, default `[]` |
| `players_per_user` | no | ≥1 |
| `episode_timeout_minutes` | no | 1–100, default 20 |

`game` (all required unless noted): `name`, `version` (PEP 440 — templates
omit it; `coworld build --version X` stamps it into the hydrated manifest),
`description`, `owner`, `config_schema`, `results_schema`, `runnable`
(`type:"game"`, `image`, `run[]`, `env{}` — no secrets, `source_url?`,
`resources?`), `protocols` (`player`, `global`, optional `engine_runtime` ∈
`mettagrid|cogweb|bitworld|nimgrid`), `docs` (`readme` required, `pages[]`
optional). Optional: `promo`, `replay_viewer: {bundle: <dir>}`.

Docs/protocol values are `{type:"text", value}` (inline markdown) or
`{type:"uri", value}` (https URL). Role entries (`player[]` etc.) add `id`,
`name`, `description` on top of the runnable fields.

Hard rules enforced outside the schema (`manifest_validation.py`):

- `config_schema` **must require a `tokens` string-array** with integer
  `minItems`/`maxItems` (one auth token per seat, injected by the runner).
- `config_schema` must use `players: [{name}]` (legacy `player_names` /
  `slots[].name` are rejected).
- `variants[].game_config` and `certification.game_config` must be
  **token-free** (the runner injects tokens).
- `certification.players` length must equal
  `certification.game_config.players` length.
- `results_schema` **must include `scores`**: one number per player slot —
  this is the cross-game ranking scalar.

### 1.2 Game container runtime

Authoritative doc: `packages/coworld/src/coworld/docs/roles/GAME.md`. The
game is a long-running server on `COGAME_HOST:COGAME_PORT` (default
`0.0.0.0:8080`) that must:

- Read config from `COGAME_CONFIG_URI` (file:// or http(s)://) at startup.
- Serve `GET /healthz` → 200 once ready (the runner gates on this before
  starting players).
- Serve `WS /player?slot=<n>&token=<t>` — **reject bad tokens at the WS
  handshake** (the runner asserts this), plus `GET /client/player?slot&token`
  (browser client for humans).
- Serve `WS /global` + `GET /client/global` (spectator).
- Start the episode when all seats connect or after
  `player_connect_timeout_seconds` (default 180, read from game_config).
- Write results JSON to `COGAME_RESULTS_URI`; write replay bytes to
  `COGAME_SAVE_REPLAY_URI`.
- On a terminal player fault, write `{message: 1–2000 chars,
  failed_policy_index: int≥0}` to `COGAME_PLAYER_FAILURE_URI`.
- Replay mode (`COGAME_LOAD_REPLAY_URI` + `GET /client/replay` + `WS
  /replay`) is **only required when `game.replay_viewer.bundle` is absent**.

**Message payloads are game-owned.** The platform fixes only the route
family and token semantics; each coworld defines its own player protocol in
`manifest.game.protocols.player`.

### 1.3 Player container runtime

Authoritative doc: `packages/coworld/src/coworld/docs/roles/PLAYER.md`.
Short-lived container, one per seat. It must read
**`COWORLD_PLAYER_WS_URL`** (a fully formed ws URL with slot and token
already encoded), connect, speak the game's protocol, act only for its own
slot, and exit cleanly. Hosted pods also get the legacy alias
`COGAMES_ENGINE_WS_URL`. Optional: upload one ≤200 MB zip to
`COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` (never blocks teardown).

### 1.4 Results

`packages/coworld/src/coworld/docs/artifacts/RESULTS.md`. The runner
validates the results JSON against `results_schema` after the game exits.
`scores` (one number per slot) drives commissioners and leaderboards. Also
expose **episode-level scalars** (not only per-seat arrays): platform
qualification gates evaluate boolean predicates over keys matching
`score.*` / `result.*` on each episode.

### 1.5 Certification gate

`coworld certify` runs 10 automated steps locally with **no backend, no
credentials** (transcript:
`packages/coworld/src/coworld/transcripts/coworld-executable.transcript.md`):
matriculate (schema) → source-resolves → images-reachable →
fixture-conforms → smoke-episode → results-conform → replay-present →
replay-loadable (static bundle declared OR `/replay` emits a frame) →
players-run (every declared player launches) → supporting-roles. The
certification fixture should therefore be deliberately tiny and fast (short
episode, few seats, no external dependencies — cf. cue-n-woo's
`stub_bedrock: true`).

### 1.6 Replay artifact and viewers

`packages/coworld/src/coworld/docs/artifacts/REPLAY.md` and
`docs/STATIC_REPLAY_VIEWERS.md`. The replay artifact is a **game-owned
opaque byte payload** — the platform stores it as `replay.replay` and hands
its URL to the viewer. Default viewer UX: autoplay, loop to tick 0.

Three delivery modes (backend `resolve_coworld_replay_session`):

1. **`static_bundle` — the current recommended path.** Manifest declares
   `game.replay_viewer: {bundle: <dir>}`. The Observatory serves the
   uploaded, content-addressed bundle and opens
   `index.html?replay=<url-encoded replay URL>`; the viewer fetches the
   bytes and renders with **no game container**. Constraints (server
   enforced): `index.html` at bundle root, regular files only, ≤4096 files,
   ≤256 MiB compressed / 512 MiB uncompressed, relative URLs only, fail
   visibly. Optional inputs: `#assets=<signed base>`, `?chrome=off`
   (thumbnail mode), `postMessage({type:"coworld-replay", bytes})`,
   `league.html` as an optional second entrypoint for the league "walled
   pit" shell. CSP allows `'wasm-unsafe-eval'` and blob workers — WASM is
   expected.
2. `static` — CloudFront-signed shared shell configured via the
   `COGAME_REPLAY_VIEWER_CONFIG` env var (vanilla-wow only; special case).
3. `runtime` — legacy fallback: boot the version-matched game image with
   `COGAME_LOAD_REPLAY_URI` behind an HTTP/WS proxy. Known jank (base-href
   rewriting breaks page-relative assets). Avoid for new work.

**Build hook contract:** if the manifest declares a source bundle dir, the
repo must ship an executable `tools/build_replay_viewer.sh`; `coworld build`
invokes it with the resolved output dir as `$1` and refuses to hydrate the
manifest unless the dir and `index.html` exist. `coworld upload-coworld`
does **not** run the hook — it uploads what `build` produced. When a static
bundle is declared, certify drops the `/client/replay` + `/replay`
requirement.

### 1.7 Release lifecycle

`packages/coworld/src/coworld/docs/AUTHORING.md` ("ladder of proof") and
`LIFECYCLE.md`. The three-command flow (the old `resolve-and-upload` is
**removed**):

```
coworld build --version <v> --project . --compose compose.yaml \
    --template coworld_manifest.json --output build/coworld-package/coworld_manifest.json
coworld certify <hydrated-manifest>
coworld upload-coworld <hydrated-manifest> [--wait-hosted-smoke]
```

- `coworld build` builds images from `compose.yaml` (service names = role
  names), substitutes `{{GAME_IMAGE}}`-style placeholders with pinned
  `name:coworld-<12hex>` tags, stamps `game.version`, pins `source_url` to
  the commit SHA, and runs the replay-viewer hook.
- Auth via `softmax login` / `softmax set-token`. First authenticated upload
  of a `game.name` **claims name ownership**.
- Highest uploaded version becomes **canonical** (after base-player
  self-play smoke episodes pass, when smoke testing is enabled). Leagues
  follow the canonical version automatically — uploading a new version is
  how fixes reach a league.
- User policies ship separately: `coworld upload-policy <image> --name X
  --run ... [--secret-env K=V]` then `coworld submit <policy> --league ...`.

### 1.8 Hosted episode execution (what runs your containers)

`packages/coworld/src/coworld/docs/LIFECYCLE.md`. Each hosted episode is a
Kubernetes parent Job: an init container writes the concrete game config +
per-seat tokens into a shared workdir; the game container starts; a worker
waits for `/healthz`, creates a ClusterIP Service, then launches **one child
pod per seat** with `COWORLD_PLAYER_WS_URL` injected. Deadlines: 20-minute
k8s Job active deadline (also `episode_timeout_minutes`, default 20);
player connect window default 180 s. Results/replay/logs upload as separate
artifacts; an event processor finalizes the episode row and updates
leaderboards.

---

## Tier 2 — De facto conventions (SHOULD)

From surveying the live coworld repos. **`coworld-ctf`
(~/coding/coworlds/coworld-ctf) is the canonical template**: newest, Nim,
points at the current monorepo schema URL, full static WASM replay bundle,
~70 tests, working CI upload workflow. Secondary references: coworld-crewrift
(multi-role manifest, definitive replay-bundle doc at
`docs/static-replay-viewer.md`), column-coworld (smallest end-to-end
example + full CLI transcript in its README), ProxyWar (wrap-an-existing-game
adapter), coworld-vanilla-wow (all six roles; sprawling special case — don't
copy).

Recurring repo layout:

```
coworld_manifest.json            # template with {{GAME_IMAGE}} placeholders
compose.yaml                     # service names = role names, platform: linux/amd64
Dockerfile                       # canonical build recipe for the game image
Dockerfile.replay-viewer         # if the bundle needs a toolchain (e.g. emsdk)
config.json                      # local dev default config
src/                             # engine
players/<name>/                  # each with its own Dockerfile + README
replay-viewer/                   # viewer sources; output dir is gitignored
tools/build_replay_viewer.sh     # the build hook
tests/                           # module-mirrored, one aggregator entrypoint
docs/PROTOCOL.md, docs/RULES.md
.github/workflows/upload-coworld.yml   # dry-run by default
AGENTS.md (+ thin CLAUDE.md pointer)
```

Conventions that repeat across all of them:

- **Two protocol families.** Nim/bitworld games (ctf, crewrift) speak
  **Sprite v1** — a binary WS protocol (message-type byte, little-endian
  fields, Snappy-compressed RGBA sprites; spec copy at
  `archived/v1/bitworld/docs/sprite_v1.md`) — and document only their
  deltas. Python/TS games (column, cue-n-woo, ProxyWar, paintarena) speak
  plain JSON with a `type` field. Both are contract-legal (§1.2).
- **Replays store config + recorded inputs, not frames.** The static viewer
  cross-compiles the same deterministic game core to WASM (ctf: Nim →
  wasm32 via Emscripten, running in a dedicated Worker) and **resimulates**.
  A `GameVersion` constant gates replay compatibility; bumping it means
  re-recording all replay fixtures in the same change.
- Wire types are frozen (ctf: flatty "field order is sacred"); generated
  files are tool-owned; docs catalogs update in the same commit as the code
  they describe.
- Deps are lock-pinned. Nim repos use **nimby** (`nimby.lock`,
  `nimby --global sync`), not nimble resolution — the Dockerfile is the
  canonical build recipe (ctf: `nimby use 2.2.4`, then
  `nim c -d:release -d:useMalloc --opt:speed --stackTrace:on`).
- Tests run from repo root; use `-d:release` for sim-heavy tests (debug is
  10–50× slower).
- CI upload workflows default to dry-run and refuse to publish a non-HEAD
  SHA.

## Leagues and ladders (short — platform-side machinery)

Model is **League → Division → Round** (no "seasons" in v2). A coworld
becomes a league via a **league seed** (`coworld league create <coworld>
<key> <name>`); the platform materializes it once the coworld is canonical,
and nothing schedules until ladder settings are enabled. Rounds are planned
by either the platform ladder (Temporal workflows; seating strategies like
`round_robin`, `swiss_neighbor`, `team_n` with optional `elo_softmax`
matchmaking) or a game-shipped commissioner container (`WS /round`
protocol). Default rating: Elo, k=32, all-pairs comparison within a round on
`results.scores`. Submissions pass a platform-owned **qualification gate**
(self-play episodes evaluated against a boolean predicate over
`score.*`/`result.*` scalars) before placement. Cadence:
`round_interval_minutes` on league settings. Depth: `docs/specs/0069-*` and
`packages/coworld/src/coworld/docs/roles/COMMISSIONER.md` in metta.

---

## Traps (learned the hard way — check these before shipping)

1. `config_schema` without a required `tokens` string-array (with integer
   `minItems`/`maxItems`) fails upload validation. Tokens are runner-injected
   auth, not a player-count declaration.
2. Any token material in `variants[].game_config` or
   `certification.game_config` is rejected.
3. `results_schema` needs `scores` **and** episode-level scalars —
   qualification gates can't evaluate per-seat arrays.
4. `resolve-and-upload` no longer exists; the flow is two-step
   `build` → `upload-coworld`.
5. `coworld upload-coworld` does not run the replay-viewer hook. Stale
   bundle = whatever `coworld build` last produced.
6. Bad token must be rejected **at the WS handshake**, not after accept —
   the runner probes this.
7. Certification runs with no backend/credentials — the fixture must be
   self-contained and fast (stub external deps).
8. Bundled players in `manifest.player[]` are mirrored to **public ECR** —
   treat their images as fully public. Submitted user policies are not.
9. LLM players on the hosted platform must call the Bedrock **sidecar**
   (`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`) with `InvokeModel`, not `Converse`,
   or they 403 and silently fall back (see `packages/coworld/AGENTS.md`).
10. **Publication is a separately authorized production mutation.** Never
    run `upload-coworld`, `upload-policy`, or `submit` without an explicit
    request — merging/release-readiness does not imply publish authority.
11. Work in an isolated venv when installing the `coworld` CLI locally
    (column-coworld README pattern:
    `uv pip install "coworld[auth,test] @ file:///Users/jamesboggs/coding/metta/packages/coworld"`)
    — never into metta's venv, never globally.
12. Manifest schema changes in metta are append-only and CI-gated
    (`coworld manifest-schema check --against origin/main`) — design new
    manifest needs within the existing schema.

---

## Tier 3 — What v1 was (context only; do not revive)

`archived/v1/` is a complete, working coworld — frozen because it was
vibe-coded, not because it failed certification. Read it as evidence, not as
a template. Anatomy:

- **A deterministic Nim port of the DTL Python Sugarscape** whose dominant
  constraint was **byte-level CPython parity**: `py_random.nim` (MT19937
  compatibility), `py_json.nim` (CPython `json.dumps` byte formatting), and
  `config.nims:1-4` disabling FMA contraction (`-ffp-contract=off`) so float
  rounding matches CPython per-operation. A vendored Python reference +
  differential tests kept it honest.
- **Platform edge was contract-correct** (matches §1.2 today): mummy
  HTTP+WS server, `/healthz`, `/player?slot&token` with 403 on bad token
  and reconnect support, `/global` with a 300-frame catch-up buffer,
  `COGAME_*` URIs, results with per-slot `scores` (final population
  sugar+spice), replay written on exit (`src/sugarscape/coworld.nim:659-682`).
- **Player protocol** (`archived/v1/docs/coworld-protocol.md`): JSON over
  WS. Game pushes an `observation` per agent per timestep — agent state
  plus ranked movement `candidates` — and the player replies
  `{"type":"action","requestId":N,"cell":C}`. Only movement is delegated;
  metabolism/combat/trade/reproduction/RNG stay in the sim. Timeout
  (default 100 ms) falls back to `candidates[0]` and counts a fallback.
- **The identifiable jank:**
  - The decision edge is synchronous and sequential: one observation in
    flight at a time, per agent, with a `sleep(1)` busy-wait
    (`coworld.nim:467-488`). Worst case ~6.4 s/timestep with 64 seats
    timing out.
  - Replays are streamed **presentation frames** (full cell grid per
    keyframe, `sugarscape.replay.v2` zlib JSON, ~11 MB compressed per
    default episode), not config+inputs. The "WASM viewer" is a 507-byte
    AssemblyScript playback *clock*; all rendering lives in a monolithic
    52 KB `viewer.html` shared between live spectating and replay.
  - `simulation.nim` is a 3995-line monolith; nimble metadata can't
    actually build the project (nimby-only, private `bitworld` dep).
- **v1's own signpost** (`archived/v1/docs/designs/static-replay-viewer.md`,
  Non-goals): re-simulating in the browser — "record the normalized
  configuration, seed, and external policy decisions, then derive
  presentation frames locally" — is named as *the preferable architecture
  for a new deterministic implementation*. That is exactly the ctf/crewrift
  static-bundle pattern (§Tier 2).

## Experimental: the Arena runtime (spec 0076) — a second, WASM-based contract

> **Provenance & status (separate from this doc's main stamp).** Researched
> 2026-08-06. Spec: `~/coding/metta/docs/specs/0076-arena-single-pod-experiment.md`
> (Status "In Review", author James Boggs, Revision 5). The metta-side code is
> **unmerged** — it lives on `origin/jb/arena-task-{1,3,4,5,6,7,8}-*` (PRs
> 19035/19062/19066/19074/19087/19088/19094, all closed pending landing; full
> stack tip = `origin/jb/arena-task-8-tooling`); Task 0 spikes merged as
> #19024. Those branches will be rebased — cite by path + function name and
> **re-check whether the stack has landed on main before relying on paths**.
> The coworld-ctf side (Task 2) IS merged: commit `e1a84a0` in
> `~/coding/coworlds/coworld-ctf` — the durable reference implementation.
> James intends to dogfood Arena with Sugarscape v2.

The Arena replaces the container-per-episode topology for episode execution:
game and players compile to **WASM components** (`softmax:game@0.1.0`,
`softmax:player@0.1.0`) that run inside one warm arena-runner pod. No
per-episode pods, no image pulls, no WebSockets — the host mediates all
messages in-process. Headline target: `dispatched → running` from p50 28.4 s
(Docker) to ≤1 s. Player "images" become single `.wasm` files uploaded to S3
by content hash.

### The WIT contracts (verbatim; vendored copy at `coworld-ctf/arena/wit/`)

`softmax:game@0.1.0` — host-driven lifecycle; host owns time, transport,
artifacts:

```wit
record seat-message { seat: u32, payload: list<u8> }
record step-output  { messages: list<seat-message>, done: bool }

interface output {
  results: func(body: list<u8>);        // exactly once, from finish()
  replay-append: func(chunk: list<u8>); // buffered; host persists after finish()
}
interface log { line: func(level: string, msg: string); }

world game {
  import output; import log;
  export init:   func(config: string, seats: u32, seed: u64) -> result<_, string>;
  export step:   func(actions: list<seat-message>) -> result<step-output, string>;
  export finish: func() -> result<_, string>;
}
```

`softmax:player@0.1.0` — the inverted WebSocket loop:

```wit
world player {
  import log;  // line: func(level, msg)
  export start:      func(slot: u32, config: option<string>) -> result<_, string>;
  export on-message: func(message: list<u8>) -> result<list<list<u8>>, string>;
}
```

Payloads are **game-defined opaque bytes** (CTF reuses Sprite v1 unchanged) —
the protocol survives; only the transport moves. Deliberately absent from
v0.1.0: `llm` and `secrets` imports — **LLM players cannot exist under Arena
v0.1.0** (a later copy-paste from `softmax:reporter` when needed).
Componentize-py guests also emit a type-only `softmax:game/types@0.1.0`
import that hosts must satisfy with an empty instance.

### Host semantics that shape game design (from the branch executor/pump)

- **Pump loop:** `game.step(buffered_actions)` → host fans `step_output.
  messages` out per seat (concurrent across seats, ordered within a seat) →
  collects `on-message` replies as the next step's `actions` → repeats until
  `done` or wall clock → `game.finish()`. Step granularity is **game-defined**
  — a "step" need not be a full timestep.
- **Fault model — inverted vs. the WS world:** a seat that traps, exceeds its
  response deadline, or violates byte budgets gets a typed `SeatFault` and is
  **permanently dropped** — no further deliveries, no further actions; the
  game must tolerate absent seats. Any guest `err` result **poisons the
  instance** (Nim goto-exceptions are unrecoverable; host discards it).
- **Terminal fan-out:** on the `done` step, messages are still delivered but
  all replies/faults are discarded — final observations are fire-and-forget.
- **Deadlines are host config, not game config:** per-seat response default
  180 s (`ARENA_RUNNER_PLAYER_RESPONSE_SECONDS`), episode wall clock from the
  job payload (`episode_timeout_seconds` ≤ 3600). Pacing: `replicate` (host
  sleeps to `tick_rate`) or `unpaced` (as fast as guests answer).
- **Limits (host constants):** 512 MiB game / 128 MiB player memory caps,
  epoch-based interruption (no fuel), 256 MiB results + 256 MiB replay caps,
  32 MiB per message. Bare WASI: no stdio, no preopens, no env, and **no
  `wasi:random`** in a well-formed guest — determinism is structural.
- **Platform integration:** experiment-scoped. No manifest changes — the
  coworld manifest stays as-is; component S3 keys ride an optional `arena`
  block on the episode job payload (`execution_backend=arena`, submitted via
  `POST /jobs/batch` by dev scripts). Results/replay/logs land at the same
  canonical artifact keys, so downstream (Episode row, leaderboards, replay
  viewing) is unchanged.

### The Nim component recipe (merged, in coworld-ctf `arena/`)

The proven pattern from `e1a84a0`, directly reusable here:

- **Transport-free runtime module** (`arena/game_runtime.nim`): init/step/
  finish over the existing sim core, reusing the exact same
  observation-builder and input-parser procs the WS server calls — that
  sharing is the parity mechanism. Baseline player refactored so the WS loop
  and `on-message` drive one shared policy code path.
- **Thin ABI shim** (`arena/game_component.nim`): checked-in `wit-bindgen c`
  bindings (drift-checked against regeneration at build time), `NimMain()`
  called from a C `__attribute__((constructor))` (reactor has no main),
  pre-filled error out-params (`--exceptions:goto` unwinds without assigning
  them), guest allocations via `alloc` freed by generated `cabi_post_*` shims
  — hence **`-d:useMalloc` is mandatory**.
- **Build** (`arena/build.sh`, versions hard-asserted): Nim 2.2.6 → wasm32
  via wasi-sdk 33 (clang 22.1.0), flags `--os:linux --cpu:wasm32
  --threads:off --mm:arc --exceptions:goto -d:useMalloc -d:noSignalHandler
  --noMain` + `-mexec-model=reactor`; `wit-bindgen` 0.60.0; `wasm-tools
  component new` 1.255.0 with the wasmtime 46.0.1 preview1 reactor adapter;
  `wasi-vfs` 0.6.3 only if the guest needs packed data files.
- **Validation**: native-vs-wasm `gameHash` parity on shared seeds, results
  JSON equality, and re-simulating the emitted replay through the canonical
  engine. Test host: `jco transpile` + Node (no wasmtime needed locally).
- **Sizes**: CTF game component ~3.1 MB code (+7.5 MB packed assets), player
  ~350 KB. A Sugarscape player would be tiny.
- **Seed gotcha**: WIT passes `u64`; Nim `int` is 32-bit on wasm32, so CTF
  folds the seed to 31 bits identically on both builds. A v2 RNG with
  explicit fixed-width state (`uint64`) avoids the fold entirely.

### What a Sugarscape v2 implementation on Arena looks like (mapping, no verdicts)

One deterministic core, multiple thin shells — Arena, the WS container, and
the browser replay resimulator all want the same thing:

```
src/sugarscape/        pure sim core: no I/O, no clock, no OS entropy,
                       seed-driven RNG, obs-encode/action-decode as pure fns
arena/                 softmax:game + softmax:player shells (dogfood target)
server/  (later)       mummy WS shell — still required for real league hosting
replay-viewer/ (later) same core resimulating in the browser (static bundle)
```

Mapping decisions embedded in this (each is a fork, not a given):

1. **Activation model.** Because step granularity is game-defined, DTL-style
   sequential activation survives: `step()` can emit exactly one agent's
   observation and consume one action per call — the host round-trips it
   in-process at µs cost instead of v1's 100 ms-timeout WS edge. Alternative:
   simultaneous decisions batched per timestep (all agents observe pre-step
   state; game resolves conflicts deterministically) — cheaper pump traffic,
   different rules than DTL.
2. **Fallback semantics.** v1 fell back to `candidates[0]` per decision and
   kept the seat alive; Arena permanently drops a faulted seat. The game must
   define what a dropped seat's agent does forever after (e.g. permanent
   greedy/default policy) — a rules decision v1 never had to make.
3. **Seat count.** Default v1 variant = 64 seats (one agent each) → 65
   component instances/stores/threads per episode vs the 17 the experiment
   was sized for. Memory caps are host constants (128 MiB/player). Scaling
   question to raise with the Arena work, not resolve here; population-policy
   variants (few seats controlling many agents) sidestep it.
4. **Message encoding** is free to be JSON (v1-style, LLM/tooling friendly)
   or compact binary — payloads are opaque to Arena, and Sugarscape
   observations are tiny either way. Whatever is chosen should be encoded by
   pure core functions so all shells share it.
5. **Dogfood harness.** ctf-style `jco transpile` + Node parity tests need
   only merged tooling (works today, durable in this repo); running the real
   `arena_runner` worker end-to-end requires the unmerged metta branch (or
   devbox once deployed). Start with the former, graduate to the latter.
6. **Replay/viewer synergy.** Replay = config + seed + decision log via
   `replay-append` (tiny). The browser static bundle can resimulate with the
   same core — either a separate emscripten build (ctf's production choice)
   or potentially `jco transpile` of the *same* `softmax:game` component
   (ctf uses jco only in tests; unproven for production viewers — an option,
   not a plan).

What Arena does **not** replace: the league path. Certification, upload, and
hosted play still run the container/WS contract (§1.2) — Arena is an
experiment measuring what the pod-per-episode ladder costs. A v2 that wants
both league hosting and Arena dogfooding ships both shells over one core.

## Decisions taken for v2

> **v3 note (2026-08-11).** v2 was archived unimplemented, and v3 **reversed
> D1**: with per-tick player control removed, v3 is a direct clone of the DTL
> Python implementation (vendored in `src/sugarscape/`). See
> `docs/designs/sugarscape-v3-design-2026-08-11.html` §1 for the reversal
> rationale. D1 is preserved below as the v2-era record.

**D1 — v2 is our own implementation of Sugarscape, not DTL.** (2026-08-07)
v2 is written from scratch. It is not a port of the DTL Python model
(`nkremerh/sugarscape`), does not target behavioral parity with it, and is not
bound by the CPython determinism contract that dominated v1 (MT19937 parity,
`json.dumps` byte formatting, `-ffp-contract=off`). DTL and `archived/v1/`
remain **reference and evidence** — for which Sugarscape mechanics exist and
how they interact — but neither is a template or an oracle, and differential
testing against `archived/v1/reference/dtl-python/` is not a correctness
criterion. A mechanism-level walkthrough of DTL is at
`docs/dtl-implementation.html`; read its §11 quirk list as the set of
behaviours v2 is explicitly free to discard.

Rationale: DTL is a batch social-science simulator with no notion of an
external agent controller, so player control can only be bolted on. v1 could
delegate **movement only** — the sim ranked candidate cells and the seat picked
one from that list — via a synchronous per-agent WebSocket round trip inside
the sequential activation loop (`archived/v1/docs/coworld-protocol.md`;
`src/sugarscape/coworld.nim:467-488`), with `candidates[0]` substituted on a
100 ms timeout. Every other mechanic (collection, combat, trade, reproduction,
lending, disease, metabolism, aging, all RNG) stayed inside the sim, and there
were no gates through which a player could influence them. Owning the model
lets player agency and its gates be designed in rather than retrofitted.

**This resolves fork 4 below** (determinism spec) in favour of v2 defining its
own deterministic spec, optimized for Nim performance and native↔wasm parity.
Forks 1, 2, 3, 5 and 6 remain open, and D1 widens 5 and 6: activation model and
fallback semantics are now free model-design choices, not constraints inherited
from DTL.

## Open design forks for v2 (decide deliberately with James — no verdicts here)

> **All six forks were closed on 2026-08-07** — see `docs/v2-design.md`
> (§10 maps each fork to its resolution; the design doc is now the
> authority on v2 model decisions). The list below is preserved as the
> context that framed them.

1. **Message encoding (was "player protocol"):** Arena makes payload bytes
   transport-independent — the same encoding rides the WS shell and the
   Arena shell. Choices: game-specific JSON (v1 lineage; natural for
   turn-based candidate selection, friendly to LLM/scripted players),
   Sprite v1/bitworld binary (ctf/crewrift lineage, shared renderer for
   free), or a compact custom binary. Encode/decode must live in the pure
   core either way.
2. **`engine_runtime` declaration** (manifest metadata; Arena doesn't read
   it): `bitworld` (v1's value) vs. `nimgrid` vs. omit — follows from fork 1
   and what runtime v2 actually builds on.
3. **Replay architecture:** config+seed+decision-log with a resimulating
   static bundle (the modern pattern, v1's own recommendation, and exactly
   what Arena's `replay-append` naturally produces) vs. compact frame log.
   Viewer build: separate emscripten target (ctf production) vs. jco
   transpile of the Arena component (unproven option). Determinism of the
   core is a prerequisite regardless.
4. **Determinism spec:** keep DTL/CPython behavioral parity (v1's heaviest
   constraint — enables differential testing against the Python reference,
   but dictates RNG, float mode, and activation-order details) vs. define
   v2's own deterministic spec optimized for Nim performance and
   native↔wasm parity (fixed-width `uint64` RNG state — Nim `int` is 32-bit
   on wasm32; float discipline or integer-only state so native and WASM
   builds hash identically).
5. **Activation model (was "decision-edge concurrency"):** Arena dissolves
   v1's latency problem — in-process round-trips make even per-agent
   sequential activation cheap, so this is now a *rules* choice: DTL
   sequential activation (one agent decides at a time, sees post-move
   state; via one `step()` per activation) vs. simultaneous per-timestep
   decisions with deterministic conflict resolution. The WS shell still
   needs a concurrency answer for whichever model is chosen.
6. **Fault/fallback semantics (new, forced by Arena):** v1 substituted
   `candidates[0]` per missed decision and kept the seat alive; Arena
   permanently drops a faulted seat. Define what a dropped/absent seat's
   agent does for the rest of the episode (permanent default policy, agent
   death, …) — and whether the WS shell mirrors the same rule for
   consistency across runtimes.

## Authoritative sources (open these for depth)

| Topic | Path (under `~/coding/metta` unless noted) |
|---|---|
| Manifest models (source of truth) | `packages/coworld/src/coworld/types.py` |
| Coworld package guidance | `packages/coworld/AGENTS.md` |
| Authoring end-to-end | `packages/coworld/src/coworld/docs/AUTHORING.md` |
| Game / player role contracts | `packages/coworld/src/coworld/docs/roles/GAME.md`, `PLAYER.md` |
| Local vs hosted lifecycle | `packages/coworld/src/coworld/docs/LIFECYCLE.md` |
| Results / replay artifacts | `packages/coworld/src/coworld/docs/artifacts/RESULTS.md`, `REPLAY.md` |
| Static replay viewers | `packages/coworld/src/coworld/docs/STATIC_REPLAY_VIEWERS.md` + spec `docs/specs/0068-*` |
| Certification checklist | `packages/coworld/src/coworld/transcripts/coworld-executable.transcript.md` |
| Task recipes (upload, submit, CI) | `packages/coworld/COOKBOOK.md` |
| Ladder orchestration | `docs/specs/0069-league-ladder-orchestration.md` |
| Canonical template repo | `~/coding/coworlds/coworld-ctf` (esp. its `AGENTS.md`) |
| Replay bundle contract (clearest prose) | `~/coding/coworlds/coworld-crewrift/docs/static-replay-viewer.md` |
| Minimal end-to-end example | `~/coding/coworlds/column-coworld` |
| v1 protocol / design docs | `archived/v1/docs/coworld-protocol.md`, `archived/v1/docs/designs/static-replay-viewer.md` |
| Arena experiment spec (authoritative plan) | `docs/specs/0076-arena-single-pod-experiment.md` |
| Arena metta code (UNMERGED — verify first) | branches `origin/jb/arena-task-*`, tip `jb/arena-task-8-tooling` (`arena_runner/{worker,executor,pump,spec}.py`, WIT under `packages/coworld/src/coworld/wit/softmax-{game,player}/`) |
| Arena Nim component reference (merged) | `~/coding/coworlds/coworld-ctf/arena/` (commit `e1a84a0`: `game_runtime.nim`, `*_component.nim`, `build.sh`, `README.md`) |
