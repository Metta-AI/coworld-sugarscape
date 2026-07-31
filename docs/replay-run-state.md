# ux.replay run state — Sugarscape

Working state for this build. Read this first after a context compact.

## What this is

A `/ux.replay` rebuild of the Sugarscape coworld replay viewer, on branch
`ux-replay-broadcast` in the worktree `~/sugarscape-replay` (off `origin/main`).
The task: full run-through of the skill, then **93+ on five independent rubrics
graded by five separate auditor agents**. Not there yet.

## Scores

| Rubric | R1 | R2 | Target |
|---|---|---|---|
| 1 · Visual design & art direction | 83 | 88 | 93 |
| 2 · Broadcast legibility / 15-second test | 71 | 84 | 93 |
| 3 · Engine + original-game fidelity | 79 | 77 | 93 |
| 4 · Accessibility & measured contrast | 54 | 78 | 93 |
| 5 · Hosted delivery, robustness, code quality | 61 | 67 | 93 |

Round 3 has not been run. All R2 findings that were real are fixed and committed.

## The single most important lesson of this run

**This coworld is a PORT, and the upstream renderer is vendored in the repo at
`reference/dtl-python/gui.py`.** It is the oracle for the LOOK exactly as the
Python model is the oracle for behaviour. It went unread for most of this run; an
art direction was invented instead ("an amber topographic massif under warm
raking light"), which produced a generated terrain batch that buried the per-cell
resource under texture and read as fog. The owner rejected it: *"the resource is
not obvious, now there is a fog over the map, this doesn't look like what james
showed me the original game was like."*

The board is now a direct port of `gui.py`: white field, `#c0c0c0` lattice, cells
ramping white → `#F2FA00` with sugar (and → `#9B4722` with spice) via the same
two-axis interpolation, agents as plain filled circles coloured red-then-blue by
decision model. Served document went 738 KB → ~138 KB; there is no image
pipeline at all. Details and the corrected art-direction lock: `docs/replay-brief.md` §0c.

## Two sessions are working this branch — read this before touching the plate

The owner has two sessions open on this worktree at once. Both are editing
`viewer/broadcast.js`, in the same place, and their work composes rather than
conflicts. If you are one of them, this section is the handshake.

- **"Fix sugar/spice flicker"** owns `grainCloud`, `grainStream`, the tile/strip
  sheet's keying, and the plate crossfade (`SETTLE_MS`, `terrainBlend`,
  `showTerrain`, the two `terrain` buffers).
- **"Add motion to the grains"** owns the stir loop (`GRAIN_PHASES`, `stirAt`,
  `stirTerrain`, the baked phase strips) and the surround (`drawGround`, the
  horizon and dust colours).

**The invariant that binds the two: a grain's HOME never moves between
timesteps.** The stir orbits a grain around its home and the home comes from
`grainCloud`, which is keyed by (variant, resource) and never by the amount in
the cell. Anything that reseeds a home per timestep — including a well-meant
"vary the scatter with the amount" — puts the flicker straight back.

Rebuild the whole path after either of you edits, or the replay the owner is
watching keeps showing the other one's last build: `build_viewer.py`, then the
Nim binary, then restart 18400 AND the preview on 18402 (cycle below).

## Verification state — all green

- `tools/test_all.sh` — viewer staleness check, 7 Nim byte-parity suites, and the
  coworld smoke test (protocol, socket derivation under the proxy prefix,
  playback engine, overlay rendering at 1/2/3/5/16 populations, replay-server
  lifetime, late-joiner backlog). Passes.
- `coworld certify` — all 10 steps, incl. `Replay liveness: verified /client/replay and /replay`.
- Proxy harness (`assets/proxy_harness.py`) at 1280×720 and the 640×360 embed
  floor: console clean, one network request for the whole app.
- `build_viewer.py` fails the build if the document would fetch anything
  external. Verified by injecting a CDN script.
- The flicker fix, measured in the running viewer against the old seeding on the
  same recorded frames (t40 → t41, 222 of 1,024 cells change amount):

  | | old | new |
  |---|---|---|
  | cell pixels changed by a +1 regrowth | 79% | 29% — the new grains themselves |
  | by a +2 regrowth | 83% | 50% |
  | by a harvest, 3,3 → 0,0 | 95% | 93%, and now drained over 380ms |
  | whole plate | 19.0% | 13.6% |

  The dissolve was sampled live mid-playback: `0 → 0.025 → 0.088 → … → 0.987 → 1`
  over ~12 drawn frames per beat, holding at 1 between them, and reading 1 flat
  after a scrub. Costs: 8.1ms of one-time sheet build, 0.57ms per plate
  composite, +0.03ms on a drawn frame against a 16ms tick.

## How to run it

```bash
cd ~/sugarscape-replay
python3 tools/build_viewer.py            # regenerate src/sugarscape/viewer.html
nim c -d:release --opt:speed --nimcache:.nimcache/release --path:src \
  -o:.build/sugarscape_coworld src/sugarscape_coworld.nim
sh tools/test_all.sh
```

**The preview is harness-managed on port 18402 and the owner watches it.** After
any rebuild it serves the OLD binary until restarted, so the cycle is:
`preview_stop` → `pkill -f "port:18402"` → `preview_start`. Never `pkill -f
"port:1840"` — that pattern also kills the proxy-harness game server on 18400 and
silently takes the preview down.

Harness game server + proxy mirror, for audits and screenshots:

```bash
.build/sugarscape_coworld --host:127.0.0.1 --port:18400 --load-replay:.build/replay.json &
GAME_BASE=http://127.0.0.1:18400 PROXY_NAME=sugarscape PROXY_PORT=18890 \
  python3 ~/metta/agent-plugins/ux/skills/ux.replay/assets/proxy_harness.py &
# page:  http://127.0.0.1:18890/v2/coworlds/sugarscape/proxy/client/replay
# embed: http://127.0.0.1:18890/embed?path=client/replay
```

## Blockers found and fixed (do not regress these)

Each is pinned by a test unless noted.

1. **Absolute `/global` socket** — resolved off the Observatory proxy prefix and
   black-screened the embed. Derived from the page's own path now.
2. **No `/replay` WS route** — `coworld certify`'s liveness probe had nothing to
   connect to. Both names serve the stream.
3. **Replay server exited ~4s after boot** — published its frames and closed, so
   any spectator arriving later got nothing. It serves until stopped and keeps
   the whole backlog.
4. **End card showed the PENULTIMATE timestep's scores** on every playthrough
   (2,312/2,231 vs the true 2,334/2,253) — `atEnd` rounded the cursor while
   rendering floored it, and the beats cache omitted the frame index.
5. **A 1.2s delivery gap declared the match over.** Live episodes have ~6.4s
   inter-frame gaps on the shipped config, so `/client/global` was unusable.
   Completion is now rules-based: the stream must reach `maxTimestep`.
6. **A truncated stream crowned the wrong population** — cutting at frame 50 gave
   a confident verdict for the population that actually loses by 81. Now reads
   CUT SHORT with no result.
7. **Crash on a 5+ population match** — the board key indexed a 4-entry palette
   raw; the manifest permits 16. Seats cycle; populations past the fourth were
   also being dropped from every total.
8. **Whole broadcast sealed behind `role="img"`** — no standing, clock, beats or
   verdict reachable by assistive technology.
9. **Corrupt replay bytes bound the port and reported healthy before parsing** —
   a ready-then-crashloop window under Kubernetes. Parse precedes the bind.
   *(Not pinned by a test.)*

## Known open items, ranked

Carried from the R2 audits; these are what round 3 should attack.

1. **No CI.** `test_all.sh` is correct and green and nothing runs it. No `.github/`.
2. **`1.4.4 Resize Text` cannot pass** in a fixed-aspect embed — the stage locks
   to the viewport so browser zoom yields identical physical text size. Inherent
   to the medium; needs a stated decision rather than a fix.
3. **Most overlay type is 6–11 CSS px at the 640×360 floor.** `T()` × 1.28
   compensates only partly; the population name is still hardcoded `25`.
4. **The feed is a partial ledger presented as a complete one** — summing its
   rows gives fewer deaths than the total shown in the emergence panel.
5. **`reducedMotion` is read once**, with no `change` listener.
6. **Firefox range thumb is 20×20** against the 24×24 minimum (WebKit is 24).
7. **Seat colour used as text** in the chart pole labels and the stinger headline
   measures 4.42:1 on its own ink halo — under AA for the size it renders at.
8. **`fail()` moves no focus** when it hides the control group.
9. **Scrub `valuenow`/`valuemax` are frame indices while `valuetext` reports
   timesteps** — wrong range for AT that falls back.
10. **The 300-frame live backlog cap** silently truncates a late joiner's episode
    with nothing in the protocol to say so. No test pins it.
11. **~15 inline `rgba()` literals** below a theme block whose header says there
    are none.

## Rubric prompts

The five prompts are long and specific. Re-derive them from the pattern: open a
named screenshot battery with the Read tool, check the prior audit's findings
one by one as FIXED / PARTIALLY FIXED / NOT FIXED, grade the rubric's own
dimensions, and return a score with a ranked defect list carrying file and line.
Run them **synchronously on explicit absolute paths**, short and imperative, and
tell them not to spawn sub-agents — a zero-tool-use return is a misfire, not a
verdict.

Battery capture: proxy-harness embed at 1280×720 and 640×360, covering early
die-off, mid-game, the end card at both sizes, and the error state.
