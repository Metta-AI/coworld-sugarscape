# Replay viewer efficiency

**Status:** approved 2026-08-14; implementation in progress
**Date:** 2026-08-14
**Owners:** James Boggs; design drafted collaboratively by Codex and Claude Code

## Problem

The replay viewer is slow in two distinct ways:

1. Its speed labels are not wall-clock multipliers. A frame currently takes
   `620 * max(1 / speed, 1 / 3) + 150` milliseconds, so the displayed 4x mode
   is only 2.16x faster than 1x. A 1,000-tick replay takes about 5m57s at the
   maximum setting.
2. Loading expands a compact delta replay into every full world state before
   playback. In a shipped 60x60, 400-agent, 1,000-tick scenario, a 1.99 MB
   compressed / 14.92 MB raw replay retains 167.9 MB of JavaScript heap after
   forced garbage collection.

The viewer also redraws a fixed 2880x1620 canvas on a permanent 16 ms timer,
rebuilds nominally static terrain about 35 times per second, and repeatedly
rescans earlier full frames to reconstruct HUD series. Raising the nominal
speed does not remove any of those costs.

The measurements and source trace supporting these conclusions are in
[`docs/recon/replay-viewer-performance-2026-08-14.md`](../recon/replay-viewer-performance-2026-08-14.md).

## Goals

- Make `Nx` mean approximately `Nx` recorded-time progression per wall-clock
  second, including pauses between frames.
- Load and retain long v3 replays without memory proportional to
  `frame count * grid area`.
- Make playback cost proportional to visible work, not elapsed timer ticks or
  the entire replay history.
- Preserve the renderer-facing `sugarscape.frame.v1` frame shape so the visual
  renderer does not need to understand replay storage.
- Preserve exact seeking, reverse stepping, HUD values, event detection, and
  same-timestep replacement for imported full-frame v1 streams.
- Keep the static viewer dependency-free and self-contained.

### Performance budgets

These are acceptance budgets, not aspirational estimates:

| Case | Current | Required after the change |
|---|---:|---:|
| 60x60 / 400 initial agents / 1,000 ticks, retained replay store | 167.9 MB heap over empty viewer | less than 10 MB |
| 40x40 / 200 initial agents / 1,000 ticks, retained replay store | 74.4 MB heap over empty viewer | less than 6 MB |
| Paused, no active effect | fixed 62.5 Hz paint loop | no scheduled paint |
| Unchanged terrain | about 35.7 rebuilds/s | zero rebuilds |
| 1,000 ticks at 16x | no 16x mode | approximately 48 seconds plus scaled end hold |

The memory budgets apply after the source JSON document has been packed and
garbage-collected. Peak load memory may temporarily include both the parsed
document and packed store; retained memory may not keep the parsed document.

## Non-goals

- Changing replay format `sugarscape.replay.v3` or the renderer contract
  `sugarscape.frame.v1`.
- Moving replay parsing or painting to a Worker or `OffscreenCanvas` before
  profiling proves that remaining main-thread contention warrants the added
  transfer and lifecycle complexity.
- Adding a streaming JSON parser or another production dependency. Native
  decompression and JSON parsing are already fast enough; retained structure is
  the problem.
- Redesigning the visual treatment, HUD information architecture, or replay
  generation precision.
- Repairing live v3 spectating in this change. The current server stream is
  unreconstructable for a joining spectator; the required protocol decision is
  called out separately below.

## Design overview

The viewer will have three explicit layers:

```text
zlib JSON / full-frame v1 input
              |
              v
     FrameStore (packed deltas)
       - checkpoints every 32 frames
       - compact summary/event series
       - 3-frame materialization cache
              |
              | frameAt(index): sugarscape.frame.v1
              v
     playback clock + renderer
       - absolute timeline cursor
       - latest-due-frame selection
       - paint only while visible/dirty
```

`FrameStore` is the only component that understands storage. The existing
renderer continues receiving complete current and previous frame objects. The
playback clock decides which frame is due; it does not derive replay events.

## Decisions and rationale

### D1: Retain packed deltas, not the parsed JSON graph

Keeping raw delta-shaped JavaScript arrays and objects would remove duplicated
world snapshots but still retain tens of megabytes of object overhead. A single
load pass will validate and pack the v3 document into structure-of-arrays typed
storage, then release the parsed document.

The cell store uses:

- `Uint32Array frameOffsets`
- `Uint32Array cellIndices`
- one typed numeric plane each for sugar, spice, and pollution

Replay cells are JSON numbers; none of the three resource planes is
contractually integral. The packing pass selects the narrowest **lossless**
representation per plane: `Int16Array` or `Int32Array` only if every value is a
safe integer in range, `Float32Array` only if `Math.fround(value) === value` for
every value, and `Float64Array` otherwise. Checkpoints use the same selected
plane types. This preserves fractional growback and pollution without making
current shipped scenarios pay the widest representation unnecessarily.

Agent static records, dynamic upserts, births, and removals get separate offset
tables. Their current replay encoding is integral, but it is not `Int16`-bounded:
agent wealth defaults to `Int32Array`, with explicit range validation and a
lossless `Float64Array` fallback at the file boundary. Other agent fields use
the same narrowest-lossless rule.
Small, infrequent `runtimeStats`, `running`, and `measured` payloads may remain
plain objects and share references between sampling ticks.

The current load path uses `DecompressionStream`, `TextDecoder`, and
`JSON.parse`. Phase 2 should benchmark switching the decompressed response
directly through `Response.json()` to avoid the intermediate decoded string,
while preserving the existing plain-JSON fallback. A Worker would still
require copying or transferring the result and would not improve retained size.

### D2: Put random access behind `FrameStore`

The viewer adopts this narrow interface:

```js
store.count
store.frameAt(index)       // full sugarscape.frame.v1
store.summaryAt(index)     // compact precomputed display data
store.timestepAt(index)
store.appendFrame(frameV1) // compatibility input, not active v3 live
```

`frameAt(index)` reconstructs from the nearest checkpoint at or before the
requested index and applies at most 31 deltas. Checkpoints contain decoder
state, not materialized renderer objects:

- grid resource planes in the lossless types selected during packing;
- live agent dynamic state in its selected lossless packed numeric storage;
- the cumulative static roster needed to materialize living agents.

At 60x60, three all-`Float64` grid planes cost about 86 KB per checkpoint, or
about 2.8 MB for 32 checkpoints across 1,000 frames; the shipped integral
planes pack substantially smaller. Agent state adds bounded scenario-dependent
storage while remaining far below full-frame retention.

Sequential forward playback applies one delta to the current decoder state.
Arbitrary seeks copy the nearest checkpoint and replay the remainder. A
three-entry LRU retains only previous, current, and next materialized
`sugarscape.frame.v1` objects. A backward step is an ordinary indexed seek;
forward playback resumes incrementally from the resulting decoder state.

The initial eager materializer stays temporarily as a test oracle, then is
removed once every-frame equivalence tests cover both shipped benchmark
scenarios and focused edge fixtures.

### D3: Precompute summaries and semantic events during ingestion

The current HUD reconstructs history by scanning frames and living agents.
Worse, event detection runs when a frame is entered, so an honest high-speed
clock that skips display frames would miss lead changes and die-offs.

The packing pass therefore derives compact per-frame series once:

- population and per-seat population;
- tribe counts/shares;
- Gini coefficient from `runtimeStats.giniCoefficient`;
- per-seat sugar, spice, and total living wealth used by the lead plot;
- per-seat running scores and current measured values;
- death counts and causes, plus the lost agents' ids, positions, and seats used
  by death effects;
- lead-change and die-off events.

Series are incrementally updated from agent deltas rather than rescanning the
roster. Values that only arrive at histogram intervals are structurally shared
until the next sample. Chart paths are downsampled to at most the rendered
horizontal pixel count when a replay is longer than the chart is wide.

A same-timestep full-frame replacement invalidates more than its packed frame.
The compatibility adapter recomputes summaries and semantic events from the
replaced index through the end, because one changed wealth total can create or
remove later lead changes. This suffix is bounded by the retained tail window
in the common replacement case; replacing an older frame takes the explicit
slow rebuild path.

The settler detail may read the previous materialized frame from the LRU. The
trade footer and other current-tick labels read the current frame's statistics.
Neither requires keeping historical full frames.

### D4: Use an epoch-based playback clock

`requestAnimationFrame` alone does not make playback correct. The existing
timer deliberately avoided hidden-tab throttling, so the replacement must
separate timeline progression from painting.

On play or speed change, the clock records a monotonic epoch and cursor:

```text
due cursor = epoch cursor + elapsed wall time / frame dwell
```

Speed changes rebase the epoch without jumping. Each visible animation callback
selects the latest due frame; it does not serially paint intermediate frames.
The current 200 ms elapsed-time clamp is removed. Hidden tabs schedule no
painting, and visibility return computes the honest due cursor from the epoch
before painting once. Paused or held playback paints once and stops scheduling
until input, resize, data append, an intentional visual effect, or resume makes
the view dirty.

Semantic events and historical charts remain complete because D3 derives them
from all replay deltas, not displayed-frame callbacks. Transient animation for
skipped frames is suppressed rather than replayed late.

### D5: Define speed as wall-clock timeline speed

One recorded frame has a nominal 770 ms duration, including the current 620 ms
transition and 150 ms reading pause. At `N x`, total dwell is `770 / N` ms.

- Preserve 0.5x, 1x, 2x, and 4x; add 8x and 16x.
- Interpolate only when dwell is at least 150 ms. Faster rates snap to the
  latest frame due on the timeline.
- Scale the current 5.2-second end hold by the selected speed.
- Preserve reduced-motion behavior.
- Keep the first frame and a seek target synchronous so thumbnails and direct
  manipulation never wait for a future animation callback.
- Above the interpolation threshold, throttle `aria-live` announcements to a
  human-readable cadence and always announce the final state; do not enqueue a
  screen-reader utterance for every skipped frame.

This grammar makes a speed label testable and prevents fixed pauses from
dominating fast modes.

### D6: Invalidate terrain and adapt backing resolution

The current terrain is countable dots wholly contained by each cell, but stale
grain-drift state causes it to be rebuilt continuously. Terrain becomes a
cached layer invalidated only by resource-cell changes, board geometry, or
device-pixel-ratio changes.

The board and terrain backing stores also stop using a fixed 2880x1620 bitmap.
Their shared render scale is:

```text
min(1.5, stage CSS width * devicePixelRatio / 1920)
```

At the common 640x360 embed this removes a 20.25x backing-pixel oversupply and
reduces each full RGBA surface from about 18.7 MB to the density actually
visible. Backing stores resize only when geometry or DPR changes; the existing
geometry measurement path can cheaply detect that condition.

Initially, any cell delta may rebuild the terrain layer once for the selected
frame. If profiling still identifies terrain as material, split painting into
`paintResourceCell` and patch only the union of changed cell indices during
sequential or skipped advancement; random seeks and resizes use a full rebuild.

The unreachable grain drift/sheet/dissolve implementation is deleted after
tests establish that it has no active call path. This removes roughly 32 KB
from the generated 334 KB static bundle.

### D7: Preserve full-frame v1 replacement semantics at the boundary

The compatibility input `appendFrame(frameV1)` diffs full renderer frames into
the same packed internal representation. It retains a tail window of about 64
full frames so the existing same-timestep replacement behavior remains cheap.
Replacing an older frame is allowed but rebuilds packed state from the previous
checkpoint, including the summary and event suffix. If a stream begins at a
nonzero timestep, its first appended full frame becomes checkpoint 0 and the
existing joined-late presentation remains intact. This is explicitly a
compatibility path for v1 files and tests, not the active v3 socket protocol.

## Live v3 spectating: resolved scope

Today `ReplayWriter.capture_frame()` sends only compact delta frames to the
server's `frame_sink`, and `/global` fans those frames out. A newly connected
spectator receives a status greeting but no replay header, initial grid, roster,
or current snapshot. The active viewer socket path accepts only full
`sugarscape.frame.v1` frames. A joining spectator therefore cannot reconstruct
the v3 stream today; this design cannot regress working behavior that does not
exist.

Recommendation for this performance project: leave live v3 repair out of
scope, but keep `FrameStore` delta-native so the future adapter is small. The
future protocol should send a `replay_header` greeting containing the sanitized
header and reconstruction baseline, followed by the same delta frames already
emitted. It must also define reconnect behavior: either a current snapshot plus
subsequent deltas, or a bounded replay of deltas since the initial header.

James ratified option 1 on 2026-08-14:

1. **Selected:** optimize artifact loading/playback now and track live v3
   header/reconnect semantics as a separate protocol change.
2. Expand this project to define and implement the live protocol first, adding
   server and socket integration tests to every phase below.

## Delivery plan

The order is dependency-driven. In particular, high-speed frame skipping may
not ship before semantic events are independent of displayed frames.

### Phase 0: Lock behavior and measurement (implemented 2026-08-14)

- Add `FrameStore`-independent golden fixtures for full materialized frames,
  summaries, events, seeking, and same-timestep replacement.
- Turn the two shipped 1,000-tick scenarios into a reproducible headless Chrome
  performance harness recording raw/compressed bytes, post-GC retained heap,
  ready time, per-advance time, and paused paint count.
- Keep thresholds generous enough for CI host variance but strict enough to
  catch a return to eager snapshots or permanent painting.

Run the reproducible browser harness with:

```text
.venv/bin/python tools/benchmark_replay_viewer.py
```

Phase 0 records the eager-viewer baseline with `budgets_enforced: false`;
Phase 2 enables the retained-memory assertions after `FrameStore` replaces the
eager snapshots.

### Phase 1: Remove unnecessary pixels and paints (implemented 2026-08-14)

- Make 0.5x through 4x honest by using `770 / speed` total dwell and scaling the
  end hold. Iterate every frame index crossed by a timer callback so a jank
  interval cannot skip event handling. Keep 8x/16x disabled until Phase 3.
- Make board and terrain backing resolution adaptive to CSS size and DPR.
- Replace terrain drift-clock invalidation with data/geometry invalidation.
- Stop permanent painting while paused or hidden; render synchronously when a
  state change dirties the view.
- Delete the unreachable grain implementation and rebuild the self-contained
  bundle.

This phase is independently valuable and low risk. It does not change replay
navigation semantics, and it cuts the current maximum 1,000-tick duration from
about 5m57s to about 3m13s before the deeper storage and clock work lands.

The Phase 1 Chrome harness records zero paused board/terrain paints, a 321,300
pixel main backing store at its headless viewport (down from 4,665,600), and a
303 KB bundle (down from 334 KB). Retained replay heap is intentionally unchanged
until Phase 2.

### Phase 2: Introduce packed `FrameStore`

- Pack v3 arrays during load and drop the parsed document.
- Add checkpoints, the sequential decoder, three-frame materialization LRU,
  indexed seek, and full-frame compatibility adapter.
- Derive all compact summary and semantic-event series in the same ingestion
  pass.
- Migrate every direct `frames[index]`, `frames.length`, and historical scan to
  the store interface.
- Remove the eager production materializer after exhaustive oracle comparison.

This is the main memory win and the architectural prerequisite for reliable
high-speed playback.

### Phase 3: Make the clock honest

- Introduce the epoch cursor and visible-only animation scheduling.
- Add 8x and 16x and skip to the latest due frame when necessary, extending the
  honest dwell and scaled-hold grammar introduced in Phase 1.
- Rebase correctly on speed change, seek, pause/resume, and visibility return.
- Verify no semantic event is lost when display frames are skipped.

### Phase 4: Optimize only measured residuals

- Downsample long HUD chart paths to visible pixels.
- Replace whole-standings-SVG `innerHTML` updates with incremental DOM updates
  only if the post-series profile shows the remaining boundary cost matters.
- Patch changed terrain cells rather than rebuilding the layer if profiling
  still shows a meaningful cost.
- Re-profile before considering Worker/`OffscreenCanvas`; adopt either only
  with measured evidence and a clear ownership/transfer design.

Each phase should be separately reviewable. Phase 2 may be split mechanically
into store introduction, caller migration, and eager-path removal, but the
packed store must not coexist indefinitely with a retained parsed document or
full snapshot array.

## Validation

### Correctness

- For every index in representative v3 replays, deep-compare
  `FrameStore.frameAt(index)` with the current eager materializer's output.
- Compare every random-seek result with sequential reconstruction.
- Exercise forward, backward, first, last, and repeated seeks around every
  checkpoint boundary.
- Round-trip full-frame v1 input through `appendFrame`, including replacement
  inside and outside the retained tail window.
- Verify replacement recomputes every affected summary and semantic event from
  the replaced index forward, including lead changes created or removed later.
- Verify a first v1 frame at a nonzero timestep becomes the reconstruction
  baseline and retains the joined-late UI treatment.
- Compare every precomputed summary and event with a brute-force scan oracle.
- Verify speed changes, pause/resume, end hold, reduced motion, hidden-tab
  return, and skipped-frame event completeness with a controlled clock.
- Assert a hidden tab schedules zero paints and visibility return computes the
  epoch-derived due cursor before issuing exactly one catch-up paint.
- Assert high-speed playback does not flood the `aria-live` region and still
  announces the final state.
- Keep `.venv/bin/python -m pytest tests/test_replay.py
  tests/test_replay_viewer.py -q`, `node tools/test_viewer.mjs`, and
  `python3 tools/build_viewer.py --check` green.

### Performance

- Force garbage collection before retained-heap measurement and subtract the
  empty-viewer baseline.
- Assert the less-than-10 MB and less-than-6 MB retained-store budgets above.
- Assert that a paused viewer with no active effect issues no subsequent board
  or terrain paint.
- Assert unchanged terrain produces zero rebuilds and geometry change produces
  exactly one.
- Measure local ready time and per-sequential-advance latency as trend metrics;
  gate only after repeat runs establish non-flaky thresholds.
- Record browser version, viewport, scenario, and GPU mode alongside results.

## Alternatives considered

### Keep all full frames in typed arrays

This lowers object overhead but still scales with `frame count * grid area`.
Periodic checkpoints plus deltas remove the wrong dimension and support exact
seeks with bounded reconstruction.

### Parse and materialize in a Worker

This can improve responsiveness during load but does not reduce retained data.
Structured cloning may temporarily increase memory, and transfer ownership
complicates the renderer boundary. Reconsider only after the packed-store
profile.

### Use `OffscreenCanvas`

It moves paint work but does not remove redundant terrain rebuilds, oversized
surfaces, or permanent paused drawing. The browser canvas APIs and explicit
invalidation solve the measured problems more directly.

### Add a streaming JSON parser

The measured large replay is locally ready in about 245 ms; its 167.9 MB
retained expansion is the urgent cost. A dependency or custom parser is not
justified unless substantially larger real artifacts later show native JSON
parse peak memory or latency to be the limiting factor.

### Keep `setInterval` and lower its rate

A slower timer still wakes while paused and cannot make displayed speed honest.
The epoch clock preserves wall-clock progression without painting invisible or
unchanged states.

## Risks and mitigations

- **Renderer-contract drift:** isolate reconstruction behind `frameAt()` and
  deep-compare every output frame with the existing path before removal.
- **Numeric packing loss:** use D1's narrowest-lossless selection independently
  for every numeric plane, and validate ranges at the external file boundary;
  no field is narrowed merely because current shipped scenarios fit.
- **Seek latency spikes:** checkpoint every 32 frames and benchmark worst-case
  31-delta reconstruction, not just sequential playback.
- **Missed high-speed events:** derive semantic events during ingestion before
  enabling skipping.
- **Peak memory during load:** release references to the parsed document as
  soon as packing completes and measure both peak and post-GC retained heap.
- **Canvas blur or oversampling:** include DPR and geometry changes in backing
  resize tests; cap at the existing 1.5 render scale.
- **Half-migrated global state:** inventory and replace all direct `frames`
  access before deleting the eager array; do not support two long-lived sources
  of truth.
- **Compatibility tail complexity:** test replacements on both sides of the tail
  boundary and make the older replacement slow path explicit rather than
  silently rejecting it.

## Approval record

James approved this design on 2026-08-14 and selected artifact
loading/playback-only scope. Phase 0 establishes the correctness oracle and
performance harness before production behavior changes.
