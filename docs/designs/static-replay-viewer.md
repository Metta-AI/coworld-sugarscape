# Static Replay Viewer

## Status

Implemented bridge for the existing Sugarscape release. It is intentionally
separate from any new simulation architecture.

## Problem

Sugarscape replay viewing previously started the version-matched game container,
loaded a replay containing complete presentation frames, and streamed those frames
to the browser at 25 frames per second. A full default episode contains 2,001
frames. The server starts streaming before a viewer connects and retains only
the latest 300 frames, so a late or reconnecting viewer can miss most of the
episode.

The original `sugarscape.replay.v1` artifact is also unnecessarily expensive.
Every frame repeats dimensions, player slots, object field names, all 1,024
cells, agent field names, and statistic field names. A measured 101-frame,
64-agent replay was 2.45 MB as JSON. A later full-size measurement was 62.89 MB.
Both compress substantially because much of that data is repeated.

## Goals

- Open hosted replays entirely in the browser, without a game pod or container.
- Start paused at frame zero only after the complete replay is available.
- Preserve every logical frame and support deterministic pause, seek, rewind,
  playback-speed changes, and end behavior.
- Keep cell reconstruction for seeking bounded and avoid repeated history
  scans during playback.
- Keep the replay format simple, versioned, and inspectable after decompression.
- Continue to view historical uncompressed `sugarscape.replay.v1` artifacts.
- Reuse the live spectator renderer rather than creating a second visual model.

## Non-goals

- Re-simulating Sugarscape mechanics in the browser. That is the preferable
  architecture for a new deterministic implementation: record the normalized
  configuration, seed, and external policy decisions, then derive presentation
  frames locally. This bridge avoids transplanting the legacy simulation into
  WASM and only compacts the presentation frames it already emits.
- Changing the standalone DTL-compatible simulation or its logs.
- Removing the legacy container replay endpoints immediately. They remain a
  local and historical compatibility path while hosted versions use the static
  bundle.

## Architecture

The Coworld manifest declares `build/static-replay-viewer` as its replay-viewer
bundle. `tools/build_replay_viewer.sh` clean-builds that directory from the
checked-in spectator HTML and a pinned AssemblyScript source module:

```text
build/static-replay-viewer/
  index.html
  timeline.wasm
```

Observatory serves the immutable bundle and passes the replay artifact URL as
`index.html?replay=<url>`. The viewer fetches the complete artifact, inflates it
when necessary, validates and indexes it, instantiates `timeline.wasm`, renders
frame zero, and remains paused. No WebSocket or game-owned server is involved.

The WASM module owns playback-clock state: current frame, playing/paused state,
speed, elapsed-time accumulation, seeking, and end clamping. JavaScript owns
browser I/O and Canvas rendering. This keeps the cross-boundary API numeric and
small; parsing JSON or manipulating DOM objects in WASM would require expensive
copies and a larger runtime.

## Replay format

New episodes write a deterministic zlib-compressed UTF-8 JSON document with
format `sugarscape.replay.v2`. Decompressing the artifact yields:

```json
{
  "format": "sugarscape.replay.v2",
  "config": {},
  "width": 32,
  "height": 32,
  "slots": [],
  "agentFields": [],
  "statFields": [],
  "keyframeInterval": 100,
  "frames": []
}
```

Each frame is an array:

```text
[timestep, keyframe, cells, agents, links, stats]
```

- `keyframe` is `1` for a complete cell snapshot and `0` for a delta.
- A complete `cells` value is the existing row-major array of
  `[sugar, spice, pollution]` triples.
- A delta `cells` value contains only changed cells as
  `[cellIndex, sugar, spice, pollution]`.
- `agents` contains arrays whose columns are named once by `agentFields`.
- `stats` contains arrays whose columns are named once by `statFields`.
- `links` keeps its existing sparse object representation.

Frame zero and every 100th stored frame are keyframes. Arbitrary seeking starts
at the closest preceding keyframe and applies at most 99 cell deltas. Sequential
playback applies only the next delta. Agent and statistic objects are expanded
only for the frame being rendered, keeping the retained timeline compact.

The static viewer accepts both compressed v2 and historical plain JSON v1.
The legacy native replay server also expands v2 for local `coworld replay`
compatibility.

## Performance choices

- Deterministic zlib uses the browser's built-in `DecompressionStream`, avoiding
  a bundled decompressor. Compression Streams are broadly available and can run
  in workers if parsing later becomes a measured main-thread bottleneck.
- Metadata and object keys are stored once, while periodic keyframes bound seek
  work. This follows the established full-snapshot plus incremental-snapshot
  replay pattern without introducing a schema compiler or general serialization
  dependency.
- Static playback is driven by `requestAnimationFrame`. The WASM clock may skip
  presentation frames when rendering falls behind instead of accumulating lag.
- Time-series values and prefix bounds are indexed once during load. Rendering a
  frame does not rescan every prior frame.
- Only the current decoded cell snapshot and presentation frame are retained in
  expanded form. All logical frames remain available in the compact timeline.

## Failure behavior

The static viewer displays a visible error for a failed fetch, unsupported
compression, malformed JSON, unknown format, invalid frame, or failed WASM
load. It never silently falls back to a replay pod.

## Validation

- Native round-trip tests cover v2 compression, keyframes/deltas, deterministic
  bytes, and v1 compatibility.
- The Coworld smoke checks the produced artifact and the legacy load path.
- Static-bundle tests verify clean builds, the WASM exports, paused startup,
  complete retention, seeking, rewinding, and speed control.
- A measured default 2,001-frame, 64-seat replay was 11.39 MB compressed and
  31.49 MB inflated, compared with 62.89 MB for expanded v1 JSON and 11.84 MB
  after equivalent compression. On local Chrome, the viewer retained all 2,001
  frames, started paused at frame zero, and rendered tested random seeks in
  1.6-3.5 ms. At 8x playback it advanced 121 frames in 300 ms and remained
  responsive. These are development-machine measurements, not performance
  guarantees.
