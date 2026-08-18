# Ruleset Studio Play — compile and run into the replay viewer

**Status:** implemented (2026-08-18), phase 2 of the
[Ruleset Studio](2026-08-18-ruleset-studio.md)
**Owner:** James Boggs

## Outcome

Ruleset Studio now has an IDE-style **▶ Play** action and adjacent settings
cog. Play submits the current Blockly compilation, runs a real Sugarscape
episode locally without Docker or a policy subprocess, gives the existing
replay viewer the main area while the world runs, and then lets that live view
settle naturally into replay controls. The parent-owned **◀ Editor** control
returns to the unchanged canvas; the final-score chip reopens the canonical v3
artifact.

## User contract

- Play is available only after the current editor generation has completed
  authoritative server validation, is valid, and has no local structural lint.
  `Command/Ctrl+Enter` uses the identical gate.
- The button vocabulary is Play → Compiling… → Stop. Stop is cooperative and
  takes effect at the next frame-observer boundary.
- The cog selects an explicitly classified fixed or pooled variant. Pooled
  variants offer ranked preview or exploration; exploration selects a scenario
  and may override timesteps. Seeds remain canonical decimal strings at every
  browser/API/artifact boundary.
- Settings and the phase-1 context selector are one state. Fixed and
  exploration choices synchronize immediately. A ranked preview synchronizes
  to the seed-derived scenario returned by POST.
- Starting a run creates one iframe at `/runs/{id}/client/replay`. Polling a
  terminal result never replaces it. Explicit reopen uses
  `/runs/{id}/client/replay?replay=/runs/{id}/replay.bin`.
- The Studio verdict always renders from API `results`; the embedded viewer
  applies its own centralized terminal-score rule. An unavailable/pruned run is
  recoverable and never changes the editor buffer.

## Configuration semantics

`src/coworld/studio.py` owns the public catalog and composition:

- `local-default`, `solo-wealth`, and `commonwealth` are fixed variants.
- `solo-ladder` and `duo-ladder` are pooled variants.
- `duel-4seat` is intentionally absent from the Studio catalog for now.
- Ranked preview resolves the same seed-to-scenario choice as the engine.
  Exploration narrows the pool to one scenario and changes only an explicit
  timesteps override; `measurement_window` is never scaled.
- Platform `tokens` are stripped before local resolution so they cannot replace
  configured seats. Arity comes from resolved `seats`; singleton targets are
  expanded only by `resolve_seat_targets`.
- Seat 0 uses the Blockly-compiled working ruleset. Other seats use the bundled
  target-aware baseline through `choose_ruleset(target.as_dict())`.

The API keeps phase-1 raw request bodies unchanged for validation and save.
Only Play routes use JSON envelopes:

| Route | Method | Purpose |
|---|---|---|
| `/api/scenarios` | GET | Public variants, scenarios, and context ids |
| `/api/run` | POST | Compile, reserve, and start one run |
| `/api/run/{id}` | GET | Progress, results, and transport warning |
| `/api/run/{id}` | DELETE | Request cancellation |
| `/api/displayed-run` | PUT | Pin/release the run visible in the browser |

## Run and artifact lifecycle

The process-wide single-run reservation is a correctness invariant because the
engine uses global RNG state. A run moves through `running → cancelling →
cancelled`, or from `running` to `done`/`error`. The worker never releases its
own reservation; a subsequent POST reaps a terminal reservation once engine
work is complete, even if that worker is still draining artifact cleanup.
Registry locks never cover validation, simulation, artifact I/O, or publication.

`frame_sink` exceptions are a tested `run_episode` abort contract.
`RunCancelled` uses that seam and publishes neither a final frame nor partial
artifacts. Every terminal outcome invokes the listener close callback so an
already-connected spectator cannot become a zombie.

Successful runs publish a same-filesystem temporary directory with one atomic
rename:

```
build/studio/runs/<run-id>/
  replay.bin
  results.json
  studio.json
```

Artifacts are immutable. Artifact pruning and the in-memory registry each
retain a 20-run terminal tail and spare the active and parent-displayed ids. A
racing viewer therefore sees either the complete directory or a recoverable
404, never partial JSON/replay bytes.

## Live materialization and transport

`ReplayWriter.header_sink` supplies a score-free bootstrap header exactly once,
before any frame. It is built through the same path used by `finish`; final-only
`scores` and `seat_details` are excluded. `V1FrameMaterializer` then applies
every v3 delta but serializes only tick 0, each
`max(1, timesteps // 240)` sample, and the final frame. A one-frame lookbehind
holds the possible terminal sample until `run_episode` returns; final scores and
seat details are then injected and `final:true` is emitted.

The asyncio/WebSocket seam is confined to `src/coworld/server.py` as
`StudioRunStageServer`, separate from `SugarscapeServer`. The asyncio loop owns
all ordering. The synchronous worker publisher validates serialized frames and
uses `loop.call_soon_threadsafe` without blocking.

Routes on the run-stage origin are allowlisted:

- `GET /runs/{id}/client/replay` — the built viewer bundle;
- `WS /runs/{id}/replay` — serialized `sugarscape.frame.v1` objects only;
- `GET /runs/{id}/replay.bin` — the immutable v3 artifact.

The catch-up buffer and each spectator queue are byte-accounted over serialized
frames. The catch-up/queue ceiling is 24 MiB and the per-frame guard is 8 MiB.
Only intermediate frames may be evicted or coalesced; tick 0 and final are
guaranteed. If a guaranteed frame is oversized, live delivery is disabled and
reported as a transport warning while the engine and artifacts continue. Join
snapshot plus subscription is atomic in one event-loop turn. A terminal socket
lingers for at least two seconds so the viewer's live-to-replay timer can fire.
The registry admits a pending run before its first frame; terminal and
artifact-only runs reject live subscriptions immediately. Closing a run drops
its catch-up buffer and spectator references, retaining only one lightweight
closed-run tombstone for late-subscriber rejection.

WebSocket `Origin` must exactly match the canonical run-stage origin; missing or
foreign origins are rejected. The iframe is trusted and unsandboxed, so its
socket carries that origin. The parent/API origin uses exact CORS, including
GET/POST/PUT/DELETE preflight.

## Launcher and shutdown

`tools/ruleset_studio.py` re-executes with `PYTHONHASHSEED=0` before Coworld
imports. It chooses three distinct loopback ports and starts, in order:

1. the run-stage asyncio loop thread;
2. the merged stdlib API listener loaded in-process with `importlib`;
3. the ux.surface Node link-server child serving `ruleset-studio/src`.

The page receives exact `?api=` and `?run=` origins. The launcher preserves
`--metta-root`, dynamic preferred ports, bridge discovery/runbook, and
`--no-open`; it adds `--run-port`, `--runs-dir`, `--shutdown-timeout`, and
`--link-server`. Link-server resolution is CLI argument, then
`COWORLD_STUDIO_LINK_SERVER`, then the ux.surface path below `--metta-root`.

SIGINT/SIGTERM stops acceptance, requests cancellation, and performs the
bounded worker join before listeners stop. A timed-out join never returns the
service to accepting state; the launcher reports the timeout and abandons the
daemon worker so interpreter shutdown remains bounded. Normal link-child exit
stops acceptance but lets an active run finish and atomically publish.

## Integration corrections from the merged phase-1 Studio

These corrections supersede the pre-merge proposal while preserving its Play
semantics:

1. The working ruleset is `compileWorkspace(...).value` from the merged Blockly
   canvas. There is no JSON editor, `RulesetDocument`, or editor adapter.
2. Existing raw validation/save APIs and the agent patch/undo pipeline remain
   authoritative; Play is an extension, not a parallel Studio chassis.
3. The link server serves `ruleset-studio/src` directly. Runtime origins arrive
   in the page query; there is no generated app or runtime-config bundle.
4. Studio strips platform tokens, takes arity from resolved seats, and delegates
   singleton target broadcast to the engine resolver.
5. Commonwealth is an exposed fixed variant; duel-4seat remains deferred.
6. Incremental v1 conversion supports both distribution and scalar targets and
   injects authoritative final seat details.
7. Settings and the existing Context selector share one selection path.
8. The merged launcher retains Metta bridge discovery and dynamic ports while
   keeping both Python listeners, registry, and worker in one process.
9. The viewer terminal selector covers distribution, Commonwealth, all seats,
   the end card, panels, verdict, and ARIA narration; historical cursors retain
   running/counterfactual scores and legacy v1 keeps wealth behavior.

## Evidence

The full Python suite, Blockly VM suite, viewer VM suite, viewer bundle check,
and CDP browser handoff are release gates. The browser test drives the real
Blockly Play control through live tick 0, progress, final frame, replay reset
and playback, API/verdict equality, Editor return, canonical reopen, Stop,
expired-run recovery, reduced motion, keyboard ordering, and three screenshots.

Fresh quick evidence on 2026-08-18 (`wealth-skewed.twin-peaks`, 100 ticks):

| Metric | Measured |
|---|---:|
| Total pipeline | 1.874 s |
| Engine with observers | 1.870 s |
| Live frames | 101 |
| Serialized live bytes | 7,408,291 B |
| Largest live frame | 73,794 B |
| Compressed v3 replay | 324,074 B |
| Raw v3 replay | 1,714,045 B |
| Artifact publish | 1.116 ms |

Both byte limits passed. These wall times are evidence, not CI assertions.
`tools/benchmark_ruleset_studio.py --ranked` retains the full-fidelity path,
but **ranked benchmark deferred; run before relying on ranked-mode resource
budgets**.

Screenshots are written to:

- `build/studio/ruleset-studio-editor.png`
- `build/studio/ruleset-studio-running.png`
- `build/studio/ruleset-studio-settled.png`

## Remaining scope

This is a local single-user tool. Run history UI, hosted/multi-user operation,
duel-4seat selection, and ranked resource certification remain out of scope.
