# Recon: replay viewer performance

## Mission

Find why the v3 replay viewer advances so slowly even when its displayed speed
is increased, and identify concrete time- and space-efficiency improvements
without changing behavior in this pass. The active path is the static,
self-contained viewer in `replay-viewer/`; the archived viewers are outside the
current implementation boundary (`AGENTS.md:1-18`).

## Directory map

- `replay-viewer/src/broadcast.js` — source playback clock, v3 delta decoder,
  canvas renderer, SVG HUD, controls, and replay loading.
- `replay-viewer/src/broadcast.html` and `broadcast.css` — the fixed 16:9 canvas,
  SVG, controls, and presentation shell (`replay-viewer/src/broadcast.html:16-48`).
- `replay-viewer/index.html` — generated single-file bundle; source edits belong
  in `replay-viewer/src/`, and `tools/build_viewer.py` assembles the committed
  output (`tools/build_viewer.py:30-38`, `tools/build_viewer.py:121-137`).
- `src/coworld/replay.py` — compact replay producer: one initial state followed
  by cell and agent deltas (`src/coworld/replay.py:21-33`,
  `src/coworld/replay.py:75-116`).
- `tests/test_replay.py`, `tests/test_replay_viewer.py`, and
  `tools/test_viewer.mjs` — replay reconstruction, bundle-contract, and headless
  viewer-model coverage (`tests/test_replay.py:14-95`,
  `tests/test_replay_viewer.py:11-71`).

## Findings

### Q1: Why does increasing the nominal replay speed barely help?

The control is doing exactly what its code asks, but the label overstates the
result. A frame lasts:

```text
620 ms * max(1 / selected_speed, 1 / 3) + 150 ms
```

The speed menu offers 0.5x, 1x, 2x, and 4x, while animation is capped at 3x and
the 150 ms reading pause is never scaled (`replay-viewer/src/broadcast.js:236-255`).
Consequently:

| Label | Actual dwell per recorded timestep | Effective rate vs. 1x |
|---|---:|---:|
| 1x | 770.0 ms | 1.00x |
| 2x | 460.0 ms | 1.67x |
| 4x | 356.7 ms | 2.16x |

A 1,000-timestep ladder replay therefore takes about 12m50s at 1x and 5m57s at
the maximum setting, before the final hold. The shipped ladder scenario used in
the large benchmark really is 1,000 timesteps (`build/scenario-pool/capacity.dense-regrow-2.json:8-11`).

This is the primary explanation for the reported symptom. It is a playback
policy problem, not evidence that the renderer is unable to advance four times
as fast. A useful fast mode should make timeline speed honest: scale the whole
dwell, remove the fixed reading pause at high speed, and skip intermediate
recorded frames when more than one becomes due between display paints. Keep the
current full interpolation as the cinematic 0.5x/1x behavior, not as a mandatory
cost at every speed.

### Q2: What runtime work is wasteful?

#### 1. Static terrain is rebuilt about 35 times per second

The old sand renderer left a 28 ms drift clock in the active loop
(`replay-viewer/src/broadcast.js:1035-1062`). `tick()` rebuilds terrain whenever
that clock changes or an obsolete dissolve remains in flight
(`replay-viewer/src/broadcast.js:4794-4808`). The current `buildTerrain`, however,
ignores its `from`, `clock`, and `dissolved` arguments: it clears the terrain
canvas and redraws the static countable dots from the current frame
(`replay-viewer/src/broadcast.js:1581-1630`).

This is pure waste. Terrain now needs rebuilding only when the terrain frame,
board size, or scale changes. On the measured 60x60 midpoint, one rebuild took
about 1.68 ms; scheduled at 35.7 Hz, that is about 60 ms of main-thread work per
wall-clock second before board animation or HUD work.

The same migration left a sizeable dead implementation behind. Functions such
as `buildGrainDrift`, `buildGrainSheet`, `grainSolid`, `grainSipTile`,
`grainUnits`, `grainShare`, and `paintHeightWash` have definitions but no call
sites. The abandoned grain section is roughly 32 KB of source inside a generated
334 KB bundle. The self-contained bundle requirement means every unused byte is
still shipped (`tests/test_replay_viewer.py:36-58`).

#### 2. The entire board redraws on a fixed timer, including while paused

Boot installs `setInterval(tick, 16)` permanently
(`replay-viewer/src/broadcast.js:5321-5339`). Every non-empty tick redraws the
canvas board and animated ground, even if playback is paused and nothing has
changed (`replay-viewer/src/broadcast.js:4725-4748`,
`replay-viewer/src/broadcast.js:4809-4821`). The board is a 2880x1620 backing
canvas (`replay-viewer/src/broadcast.html:19-22`).

The measured 60x60 midpoint board draw took about 0.51 ms in headless Chrome's
software path, or about 32 ms of JavaScript canvas work per second at 62.5 timer
ticks. Paused playback should render once, then wake only for an input, resize,
active effect, or resume. During playback, use `requestAnimationFrame` and derive
the cursor from monotonic elapsed time; a hidden tab can catch the timeline up on
visibility return without painting frames nobody can see. This matches current
browser guidance to use `requestAnimationFrame` for canvas animation and to
pre-render repeated work offscreen ([MDN canvas optimization](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial/Optimizing_canvas)).

#### 3. The culture HUD repeatedly rescans the whole replay

The HUD is sensibly signature-cached to timestep boundaries, but each boundary
replaces the whole standings SVG via `innerHTML`
(`replay-viewer/src/broadcast.js:4212-4245`,
`replay-viewer/src/broadcast.js:4291-4304`). The culture chart first scans every
frame to rediscover the set of tribes, then for every tribe rescans every frame
up to the cursor and recounts every agent (`replay-viewer/src/broadcast.js:3852-3907`).
The inequality chart independently walks all prior frames to rebuild its points
(`replay-viewer/src/broadcast.js:3670-3709`).

At the measured 60x60 midpoint, a forced HUD boundary rebuild took about 9.75 ms.
Precompute compact `giniSeries` and `tribeShareSeries` once while applying deltas;
then HUD work is proportional to chart points, not chart points times living
agents. Downsample paths to at most the rendered horizontal pixel count for long
future recordings.

### Q3: Where is the space blow-up?

The producer is already compact. It records one initial grid and roster, then
only changed cells, changed/new/dead agents, runtime statistics, and periodic
histograms (`src/coworld/replay.py:67-73`, `src/coworld/replay.py:75-116`). It
serializes compact JSON and zlib level 9 (`src/coworld/replay.py:118-150`), and
the public contract documents the same delta model (`docs/PROTOCOL.md:79-89`).

The browser immediately reverses that saving. `v3ToReplay()` applies each delta
and calls `materialise()` for all timesteps. Every call creates a fresh object
for every living agent and deep-copies every cell into nested arrays
(`replay-viewer/src/broadcast.js:5134-5173`,
`replay-viewer/src/broadcast.js:5185-5205`). `adoptReplay()` then validates and
records all of those full snapshots before playback starts
(`replay-viewer/src/broadcast.js:5268-5318`).

Measured in Chrome 151 after forced garbage collection:

| Scenario | Replay compressed/raw | Materialized frames | Live JS heap over empty viewer | Ready time, local fetch |
|---|---:|---:|---:|---:|
| 40x40, 200 initial agents, 1,000 ticks | 1.11 MB / 8.02 MB | 1,001 | 74.4 MB | 139 ms |
| 60x60, 400 initial agents, 1,000 ticks | 1.99 MB / 14.92 MB | 1,001 | 167.9 MB | 245 ms |

The large scenario dimensions are source data, not synthetic assumptions
(`build/scenario-pool/capacity.dense-regrow-2.json:8-11`,
`build/scenario-pool/capacity.dense-regrow-2.json:76-78`). The heap expansion is
about 84 times the compressed artifact. This is memory bloat rather than a leak:
the snapshots remain reachable by design. Chrome's own guidance distinguishes
that pattern from progressive leakage and recommends forced-GC heap comparison,
which is the method used here ([Chrome memory guidance](https://developer.chrome.com/docs/devtools/memory-problems)).

The durable fix is to remain delta-native in the viewer:

1. Retain the compact replay frames.
2. Precompute only small per-timestep summaries needed by charts and events.
3. Materialize the current and previous visual frames on demand.
4. Add periodic compact checkpoints (for example every 32 timesteps) so an
   arbitrary scrub replays at most one checkpoint interval of deltas.
5. Cache the last reconstructed neighborhood for sequential playback.

Packing all current full snapshots into typed arrays would reduce the multiplier,
but still scales as `timesteps * grid area`; checkpoints remove that wrong
dimension. Moving the existing eager conversion to a Worker or `OffscreenCanvas`
would hide some main-thread latency but would not solve retained memory.
`OffscreenCanvas` is established and worker-capable, but it should be a later
option only if profiling still shows rendering contention after the redundant
work is removed ([MDN OffscreenCanvas](https://developer.mozilla.org/en-US/docs/Web/API/OffscreenCanvas)).

### Q4: What should be changed first?

Recommended order, smallest high-value changes first:

1. **Make speed honest.** Add real fast rates and permit frame skipping; do not
   force the full 620 ms walk plus 150 ms pause at 4x.
2. **Stop static terrain churn.** Rebuild only on terrain/geometry changes and
   remove the unreachable grain implementation. This is local and low risk.
3. **Render on demand.** Replace the permanent timer with `requestAnimationFrame`
   while motion is active, and stop scheduling while paused or held.
4. **Precompute chart series.** Eliminate repeated full-replay agent scans at
   each HUD boundary.
5. **Keep replay deltas compact in memory.** Add checkpoints plus current/previous
   materialization. This is the largest win and the only one that fixes scaling,
   but it changes more viewer state and should land after the smaller fixes.

No new production dependency is justified. The browser APIs and existing data
contract are sufficient.

## Measurement method

The two shipped scenario JSON files were run through `run_episode(config,
[None], emit_timing_logs=False)`. Replay raw/compressed sizes came from the
artifact and zlib payload. The generated artifact was loaded from localhost in
Google Chrome 151.0.7922.138 at a 1280x720 emulated viewport. CDP
`Runtime.getHeapUsage` was sampled after `HeapProfiler.collectGarbage`, once for
the empty viewer and once after all 1,001 frames were adopted. Function timings
are 20-30 invocation averages through the real viewer functions with GPU
acceleration disabled, so they isolate JavaScript/canvas command cost rather
than claim hosted-device frame rates. Chrome recommends profiling clean sessions
and inspecting CPU/FPS rather than guessing from source
([Chrome runtime performance guide](https://developer.chrome.com/docs/devtools/performance)).

Baseline validation remained green:

```text
.venv/bin/python -m pytest tests/test_replay.py tests/test_replay_viewer.py -q
7 passed in 0.15s

node tools/test_viewer.mjs
Viewer model passed

python3 tools/build_viewer.py --check
replay-viewer/index.html is up to date (334 KB)
```

## Cross-references and surprises

- The source comments still describe moving sand and dissolves, but the active
  terrain code has already switched to static dots. That stale internal design
  narrative directly conceals the wasted repaint path
  (`replay-viewer/src/broadcast.js:1035-1055`,
  `replay-viewer/src/broadcast.js:1503-1519`).
- `tools/build_viewer.py`'s module docstring still says it writes to
  `src/sugarscape/viewer.html`, while the actual `OUTPUT` is
  `replay-viewer/index.html` (`tools/build_viewer.py:2-17`,
  `tools/build_viewer.py:30-38`). This did not affect performance, but it is
  documentation drift worth correcting when implementation begins.
- The focused tests validate replay correctness and the bundle contract, but no
  test currently places an upper bound on heap amplification, load time, or work
  performed while paused (`tests/test_replay_viewer.py:11-108`).

## Unresolved

- This pass did not profile a replay inside the Observatory iframe on a user's
  actual device. The local measurements prove the algorithmic waste and the
  speed cap, but hosted CPU/GPU scheduling may change their relative weights.
- The exact replay James experienced was not identified. A trace from that
  replay would determine whether its worst visible pauses are terrain, HUD,
  garbage collection, or all three.

## Files read (full or significant section)

- `AGENTS.md`, `README.md`, `docs/what-is-a-coworld.md`, `docs/PROTOCOL.md`
- `src/coworld/replay.py`
- `replay-viewer/src/broadcast.js`, `broadcast.html`, `broadcast.css`
- `tools/build_viewer.py`, `tools/serve_replay_viewer.py`, `tools/test_viewer.mjs`
- `tests/test_replay.py`, `tests/test_replay_viewer.py`, `tests/test_episode.py`,
  `tests/conftest.py`
- `build/scenario-pool/capacity.compact-regrow-1.json`,
  `build/scenario-pool/capacity.dense-regrow-2.json`
