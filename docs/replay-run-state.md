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

## The world is sugar AND spice, on the oracle's own peaks (owner call, 2026-08-05)

*"Where's the spice?"* — James, on the team screen. Settled: there is supposed to
be both. This section previously argued the opposite; read the reversal before
re-litigating it.

**What the earlier reasoning got right.** Turning spice on does tile the plate.
Sugar and spice on crossed diagonals leave **1.2% of cells bare** against 27.6%
for sugar alone — on the 50x50 grid and on any other. That measurement stands.

**What it got wrong.** It read "no bare ground" as "no mountains" and switched the
second resource off to get bare ground back. The massifs were never missing —
they are HEIGHT, not presence. Dump frame 0 and the field is a textbook
Sugarscape landscape: cells ramping 1→4 around each of four peaks, with each
resource's own bare ground sitting exactly where the other one's mountain is.
Nothing was wrong with the world. What was wrong was the **board**, and it was
measurable: sampling the rendered plate cell by cell against the frame it was
drawn from, one unit of sugar to the next moved mean luminance by 4–9 values
(**1.06:1 to 1.13:1**, where a non-text graphic needs 3:1), while the scatter
WITHIN a single level was 7–13. The encoding was quieter than its own noise —
gap/σ of 0.32 to 0.92 — so a 1-cell and a 4-cell were not distinguishable and
four mountains printed as an even speckle. Grain density saturates: past the
first unit each new grain lands on sand that is already lit.

**So the fix is in the renderer, not the config.** `paintHeightWash` puts the sand
on a deterministic wash — one source pixel per cell, blended off the plate toward
each resource's hue in proportion to what the cell holds, upscaled smoothed so
the field interpolates between cell centres instead of terracing into squares. It
is gui.py's two-axis ramp restored as a floor UNDER the sand, so the grains keep
texture and the harvest animation and stop having to carry depth alone. Measured
after: adjacent levels 1.19–1.26:1 at gap/σ 1.0–3.9, bare→full 2.20:1 for sugar.
`WASH_GAIN` is set at 0.16 by the settlers rather than by the terrain — a seat
colour is ~115 inside a C.ink ring, and the brightest joint cell has to stay
clearly under it.

`config.json` now omits every SUGAR key — the oracle's command-line defaults
already equal what `reference/dtl-python/config.json` ships, so restating them
could only drift — and states the five SPICE keys, which those defaults would
otherwise zero. The reference is documented to run `python sugarscape.py --conf
config.json`, and that file has maxSpice 4, regrow 1, metabolism [1,4], starting
[10,40], peaks (15,15) and (35,35). Two keys stay at the CLI default on purpose:
`timesteps` 200 (episode length is a Coworld call) and `agentMaxAge` [-1,-1]. This
is a variant of the reference world, not a restatement of it, and the manifest
description says exactly that.

**It is also the better match.** The sugar-only recording had ZERO lead changes —
the one beat this broadcast exists to catch never happened in its own reference
data, so every path to it was exercised only by the test suite. With spice:
three, at t9, t10 and t12. Two metabolisms also make the die-off real (164 of 250,
half of them by t16) and put 69 of those deaths on spice alone, so the second
resource is load-bearing rather than decorative.

If you ever need TIGHTER mountains, the lever is peak POSITION —
`radialDispersion` scales with `max(px, W-px)`, so peaks nearer the centre make
tighter ones (32x32 at 14/18 instead of 10/22 measures 37.8% bare with both
resources present). The generator is not the lever: `sugarRadiusScale` is
hardcoded upstream and the byte-parity suites pin it.

The replay is 10 MB (201 frames x 2,500 cells). Under the 300-frame live backlog
cap, but worth knowing before adding frames.

## The lead plot diverges, and its band is stacked (owner call, 2026-08-05)

*"The lead should be blue on one side and red on the other, not both on the same
side."* — James. This plot has now been changed in both directions, so the
reasoning on each side is worth keeping.

**It was diverging, then it wasn't.** Commit 47924ab moved it to plot the
ABSOLUTE lead always upward, on the argument that a viewer applying the
near-universal "up is winning" would see a descending band contradict the
scoreboard. Real, but it costs more than it buys: with both spells drawn upward,
SIDE carries nothing and the whole question of who leads rests on telling two
hues apart. Diverging gives it a second, redundant channel, which is what a
colour-blind viewer or a compressed stream has left when hue fails. The old
objection is answered by NAMING THE POLES — each half carries its population's
dot and name — so "up" decodes as "A" rather than as "good". Do not undo that
half of it: without the pole labels the original objection comes straight back.

**The scale is symmetric and that is not free.** A peaks at +4,254 and B at only
201, so B's spells are genuinely thin. That is the episode being lopsided, not
the axis lying about it; scaling each half to its own maximum would draw a 201
lead at the same height as a 4,254 one. The crossings stay legible because the
line changes side AND colour at the same point, with the gold dashed rules on top.

**The band is stacked by resource**, spice against the line and sugar outside it
(owner call, flipped from sugar-first). Height is still the true lead, but the
seam says what the lead is MADE of, which is a different fact: on the shipped
recording A's lead is 99% sugar at t25 and 54% by t200, and on 9.5% of timesteps
the two resources favour different populations. The denser tone is always the
INNER band — that is a property of the stack, not of a resource — so if the two
are ever swapped again, `along("spice")` and the key's label list are the two
places that move together. When the resources disagree the outer band folds back
across the line; that is the fact rather than a fault, since ink on a side is
that side's advantage whichever band it belongs to.

**Cut at the midline with a clipPath**, not by segmenting at the crossings: a
spell that changes hands does so BETWEEN two plotted points, and the clip finds
that intersection exactly and for free. Each band and the lead stroke are drawn
twice, once into each half.

Pinned in `tools/test_viewer.mjs`: one band per resource per side, the upper half
only ever seat 0's colour and the lower only seat 1's, both poles named, the two
shades keyed, the caption inside the plot, and the inner band tracing the SPICE
lead — that last one read off the geometry, because renaming assertions when the
two were swapped would otherwise have proved nothing. Every one was
mutation-tested against the regression it guards.

## The die-off is a line now, not a banner (owner call, 2026-07-30)

*"Instead of DIE OFF being this flashing banner every tick that covers the middle
of the game, why not just make it a population line chart by the lead-in-sugar
chart that updates tick by tick."*

Done, in `viewer/broadcast.js`:

- `onFrameEntered` queues a beat for a **lead change only**. The `count >= 3`
  death branch is gone, and `stinger()` no longer has a die-off variant. On the
  shipped config a die-off clears three settlers most timesteps, so the plate was
  up more often than it was down, over the one surface the broadcast is about.
- `settlerStrip()` is the replacement: one line per population, on the SAME time
  axis as the lead band directly above it, so a collapse and the lead it cost sit
  on the same vertical. Scaled 0 → the largest headcount any one population has
  held (not `startingPopulation`: reproduction climbs past it and a late joiner
  never saw it).
- The race panel carries both plots. Sparse pays for it with 78 units off the
  emergence panel, which still clears the 235 its two stacked readouts need.
  **Dense cannot pay** — at 194 units emergence is exactly its own content — so at
  the embed floor the strip is carved out of the lead plot and the panel keeps its
  height. The gap between the plots is one caption tall at either ramp, and the
  strip drops its "0" at the floor where two 34-unit gutter figures filled the
  76-unit plot they were scaling.
- `headCounts()` sets each population's live figure beside its head dot, in that
  seat's lifted `text` colour: two populations dying at the same rate draw two
  lines on top of each other, so the shape alone cannot say which is which. The
  figures sit AFTER the head, in the stretch of axis the episode has not reached,
  and flip in front of it at the end; heads at nearly the same value are pushed
  apart from the top down. Dropped entirely when the stack cannot span the plot
  — the sixteen-population case the manifest permits.
- Pinned by `tools/test_viewer.mjs`: deaths queue nothing, a lead change still
  raises LEAD CHANGE, the strip is labelled, it carries one point per population
  per timestep delivered, each head carries its own figure, the figure flips at
  the end of the axis, and sixteen of them are dropped rather than piled up.
  `DIE-OFF` may not appear in the document.

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

**`?stir=off` tells the two motions apart, and you will need it.** They are easy
to confuse for each other and the numbers say why. Held on ONE paused timestep,
with nothing in the model changing at all:

| per 67ms stir step, paused | stir on | `?stir=off` |
|---|---|---|
| plate pixels that move | 46.7% | 0.15% (the starving markers, not the plate) |
| that move by >60 of 215 levels of plate-to-grain contrast | 17.4% | 0% |

That is consistent with the intended ~⅓px drift rather than with grains
teleporting — a 1px grain at that contrast shifts an edge pixel by ~70 when it
moves a third of a pixel — but it means the drift runs at near-full contrast
across roughly half the grain pixels, fifteen times a second, on a board whose
owner's complaint was that the resource flickers. **Nobody can answer "does it
still flicker?" while both motions are running**, which is what the switch is
for. Judge the stir with `?stir=off` in the other tab.

**The grain size and the grain count are ONE setting with two halves.** Coverage
is the quantity a cell holds and coverage goes with the SQUARE of the grade, so
`particle` in `buildGrainSheet` and `PARTICLES_PER_UNIT` must move together or a
unit of sugar quietly changes what it is worth on the plate. The owner asked for
much finer sand on 2026-07-30: 0.026 of a cell, down from 0.064, paid for with
36 → 220 grains per unit. One-time sheet build 129ms, 11.9 MB of strips, first
composite after a rebuild ~48ms of texture upload and 0.72ms warm.

**And the cells bleed.** The tile carries a 3px margin and a grain that orbits
past the edge is drawn into it, over the neighbour, instead of wrapping back
inside — the torus kept density flat but nothing ever crossed a boundary, so the
lattice could still be read off the plate. The honest cost of the spill: the
overhanging sand belongs to the cell it came FROM, so a harvest takes it with it.

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
