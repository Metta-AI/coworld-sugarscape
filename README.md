# Coworld Sugarscape

Coworld Sugarscape is a native Nim port of the Digital Terraria Lab (DTL)
Sugarscape model and a deployable Coworld game. The behavioral oracle is DTL
commit `a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8`, vendored under
`reference/dtl-python/`.

The production executables contain no Python. They preserve the pinned
CPython 3.12 model's asynchronous activation order, random-number consumption,
floating-point operation boundaries, Python numeric types, and byte-level JSON
and CSV serialization.

## Compatibility

The native model implements the complete headless, configuration-driven DTL
simulation:

- peak-generated and file-loaded sugar/spice environments, wraparound,
  cardinal/radial ranges, seasons, growback, pollution, and diffusion;
- movement, combat, collection, metabolism, aging, death, inheritance, and
  replacement;
- reproduction, tags, tribes, races, social networks, trade, lending, and
  debt;
- disease, immune systems, depression, and zombie-virus behavior;
- `Agent`, `Asimov`, `Bentham`, `Temperance`, and exact `Leader` decision
  models;
- aggregate and per-agent JSON and CSV output, including Python key order,
  whitespace, float spelling, arbitrary-size integers, and file boundaries;
- CPython 3.12-compatible seeded MT19937, `random()`, `randbelow()`, and
  `shuffle()`.

`Leader` compatibility deliberately retains the upstream exhaustive Cartesian
future search. It is exponential and therefore suitable only for the tiny
worlds for which the upstream implementation is practical.

The compatibility boundary excludes the desktop Tk GUI, screenshots,
profiling, diagnostic debug-console text, and the upstream parser's individual
configuration override flags. The native CLI accepts the canonical
configuration-file workflow used by headless DTL and Coworld. See
[`rules.md`](rules.md) for the exact contract.

## Toolchain and build

The repository pins Nim 2.2.6 and every Nim dependency in `nimby.lock`.
[Nimby](https://github.com/treeform/nimby) 0.1.26 or newer is required. Ensure
`~/.nimby/nim/bin` is on `PATH`, then provision the pinned compiler and
packages:

```bash
nimby use 2.2.6
nimby sync nimby.lock
mkdir -p .build .nimcache/release
nim c -d:release --opt:speed \
  --nimcache:.nimcache/release \
  --path:src \
  -o:.build/sugarscape \
  src/sugarscape.nim
```

The project `config.nims` disables fused multiply-add contraction. Do not
remove that setting: CPython rounds after each primitive floating-point
operation, and contraction changes late-horizon output bytes.

Run a model configuration:

```bash
.build/sugarscape --conf reference/dtl-python/examples/all_features.json
```

Use `--dump-config` to print the effective validated configuration, including
the concrete replayable seed selected when the input seed is `-1`.

Build the Coworld game and bundled greedy policy:

```bash
nim c -d:release --opt:speed \
  --nimcache:.nimcache/coworld \
  -o:.build/sugarscape_coworld \
  src/sugarscape_coworld.nim
nim c -d:release --opt:speed \
  --nimcache:.nimcache/greedy \
  -o:.build/sugarscape_greedy \
  players/greedy/greedy.nim
```

## Validation

Run the focused native suites:

```bash
tools/test_all.sh
```

Compare every vendored example with the Python oracle through its configured
termination. `--agent-log` checks both aggregate and per-agent output:

The oracle commands require CPython 3.12. Create an isolated interpreter with
[`uv`](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12 .venv
.venv/bin/python tools/differential_examples.py \
  .build/sugarscape --full --format json --agent-log
.venv/bin/python tools/differential_examples.py \
  .build/sugarscape --full --format csv --agent-log
```

The Python environment is only an oracle-test dependency. The native tests and
production images do not embed it.

Run the local Coworld protocol/replay test:

```bash
node tools/smoke_coworld.mjs .build/sugarscape_coworld
```

Rebuild the browser broadcast after editing anything under `viewer/`. It is
inlined into the generated `src/sugarscape/viewer.html`, which the binary embeds
at compile time, so that file is committed and the test suite fails on a stale
one:

```bash
python3 tools/build_viewer.py          # regenerate; --check only verifies
```

Regenerating the vendored assets is needed only when changing the art direction
or the typefaces. Both write into `src/sugarscape/` and are committed:

```bash
node tools/vendor_fonts.mjs            # subset woff2 faces
node tools/generate_art.mjs            # art batch; needs a Gemini API key
```

Record a full-scale episode to build or verify the viewer against, instead of
the small certification fixture:

```bash
node tools/record_replay.mjs .build/replay.json
.build/sugarscape_coworld --port:8080 --load-replay:.build/replay.json
# then open http://127.0.0.1:8080/client/replay
```

Build the production containers:

```bash
docker build -t coworld-sugarscape:local .
docker build -f players/greedy/Dockerfile \
  -t coworld-sugarscape-greedy:local .
```

`coworld_manifest.json` declares the current Bitworld runtime, default variant,
certification episode, schemas, routes, and both images.

The committed `config.json` tokens are local examples, not credentials. A
Coworld runner must inject fresh per-episode tokens; never reuse those example
values for a deployed episode.

## Coworld behavior

Each authenticated `/player` WebSocket controls a configured population of
decision-model labels. The game requests one legal movement decision at a time
in canonical shuffled activation order. An action is bound to the exact socket,
slot, request ID, and candidate set; malformed, spoofed, late, or illegal
actions are ignored and use the deterministic greedy fallback.

The `/global` WebSocket and browser spectator expose read-only
`sugarscape.frame.v1` state. The viewer includes resource/pollution modes,
policy and agent-attribute coloring, social links, inspection, labeled live
time series, a stable-domain wealth histogram, a normalized Lorenz curve, and
replay scrubbing. Late spectators receive up to 300 recent frames before live
updates. Results report each slot's final living population wealth (sugar plus
spice, truncated to an integer). Replay artifacts contain the effective
configuration and immutable statistics for all recorded frames without
consuming model RNG. The complete wire contract is in
[`docs/coworld-protocol.md`](docs/coworld-protocol.md).

## Performance

Benchmark the same configuration and timestep cap against the pinned oracle:

```bash
.venv/bin/python tools/benchmark.py \
  .build/sugarscape --example all_features --timesteps 100 --repeats 3
```

The runner reports the best of repeated wall-clock samples for both processes.
Performance numbers are machine-specific and should be recorded with the Nim,
Python, architecture, and source revision used.

## Repository layout

- `src/sugarscape/`: native model, compatibility runtime, and Coworld adapter.
- `players/greedy/`: bundled deterministic population policy.
- `tests/nim/`: focused native compatibility tests.
- `tests/fixtures/`: small oracle and edge-case configurations.
- `tools/`: differential, benchmark, state-comparison, and Coworld smoke tools.
- `reference/dtl-python/`: immutable upstream oracle and its 29 examples.
- `rules.md`: byte-level behavioral contract and fidelity gates.

## Provenance and license

The pinned upstream source and retrieval details are in
[`reference/dtl-python/UPSTREAM.md`](reference/dtl-python/UPSTREAM.md). DTL
Sugarscape is released under the Unlicense; this native port retains it.
