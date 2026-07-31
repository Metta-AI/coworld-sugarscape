# Sugarscape replay brief

Working notes for the broadcast replay viewer. Phase 0a/0r/0/0c of `/ux.replay`.
Every claim below is traced to engine source or to a recorded full-scale episode
(`tools/record_replay.mjs`, seed 8675309, the manifest `default` variant).

## 0a — Platform, archetype, delivery

- **Platform A plumbing (the self-hosted third shape).** No Python `game/server.py`,
  no `@cogweb/*`. `src/sugarscape/coworld.nim` is a Nim + mummy server that serves its
  own viewer HTML at `/client/replay` and streams frames over a WebSocket. All the
  proxy/base-href/vendoring rules apply. It already ships `viewer.html`, so the job is
  **elevate by rebuild**, not polish.
- **Archetype 1 — spatial arena**, with a secondary economic read (wealth is the score,
  and the famous Sugarscape result is an emergent wealth distribution). Entities move
  continuously between frames, so interpolation is required, not optional.
- **Delivery: container-backed.** The manifest declares no `game.replay_viewer.bundle`;
  the viewer is `staticRead` into the Nim binary and served at `/client/replay`. The
  payload is a self-contained JSON artifact, so a static bundle is possible later — the
  viewer is written to read either source, so switching is a manifest change, not a
  rewrite. Container delivery is what ships today, so Phase 3/4 harden and verify
  against the k8s proxy, and data-URI assets are correct (the static-bundle CSP
  inversion for fonts/media does not apply here).

## 0r — Depth target, and where it misled this build

Measured from `packages/cogweb/games/agricogla/src/client/animation/` so this build has
a concrete bar rather than a vibe.

> **⚠️ The art-batch row was WRONG for this game, and following it cost a day.** The depth
> bar is derived from Agricogla, which had no prior visual identity — so "~35–45 rendered
> pieces, a themed dashboard is NOT done" is the right bar there. Sugarscape is a **port of
> an existing simulation whose renderer is vendored in this repo**. Generated terrain art
> displaced a rendering people recognise, buried the per-cell resource under texture, and
> read as fog. **For a port, fidelity to the original look IS the depth.** The art batch was
> generated, shipped, and then removed; the viewer now carries no images at all and the
> served document went from 738 KB to 115 KB. Every other row below transferred fine.

| Dimension | Agricogla reference | What Sugarscape actually needed |
|---|---|---|
| Art batch | 18 rendered PNGs (5 tiles, 12 tokens, wordmark), inlined as data-URIs, team-recolored in code | **none** — the board is ported from `reference/dtl-python/gui.py`; a drawn lattice, not an illustrated one |
| Skeleton | one `<svg>` at `H=1180`, `W=round(H*16/9)`, `TOP_INSET = MARGIN + 74` derived from `BUG_H=58` | one 1920×1080 stage: canvas board + SVG HUD overlay in the same coordinate space, `TOP_INSET` derived from `BUG_H` |
| Scorebug | rank (mono) · identity dot · name (display, clipped) · score 30px · leader crown + `▲ +margin` | same, on the wealth axis, population as the secondary |
| Choreography | walk-in → work → fly-home arc → gain pop → spotlight, effect-on-arrival (`revealDelayMs`) | settlers interpolate between timesteps (they jump several cells, so without it they teleport); a starving settler goes hollow before it dies; death leaves an expanding ring |
| Timing levers | `animFactor = max(1/speed, 1/2)`; `turnDwellMs = max(BASE/speed, beat)`, `BASE_TURN_MS=2600`, `READ_PAUSE=600` | same two levers, ported: motion capped at 3× real time (`ANIM_MAX`), frame dwell floored to the walk length |
| Ambient life | ~8 desynced loops (bob, roam, sway, smoke, glow, pulse), all `/ var(--speed)`, all killed by `prefers-reduced-motion` | **none, deliberately** — the lattice is a scientific plate and idle motion on it is noise; the movement in this game is the swarm itself |
| Beat FX | ~10 keyframes (`chip-pop`, `gain-pop`, `curtain`, `roundbeat`, `endcard`, `stamp-pop`…), all `calc(Xs / var(--beat-speed,1))` | lead-change stinger, die-off callout, hold-on end card — speed-aware, in a beats layer kept SEPARATE from the standings layer so rebuilding one never restarts the other's animation |

## 0 — The replay brief (each bullet traced to engine truth)

Recorded episode: 32×32, 100 timesteps, 64 agents, two policy populations, sugar AND
spice. **Re-measured against `.build/replay.json` after the shipped variant changed.**
An earlier revision of this section described the single-resource world the variant used
to run, and every figure in it was wrong once `config.json` gained spice and grid-scaled
peaks — under a heading promising each bullet was traced to a recording. The numbers below
were recomputed from all 101 frames of the current one.

1. **Standing axis — total living wealth (sugar + spice) per population.**
   `coworld.nim buildResults` scores `int(totalWealth)` over each slot's living agents,
   and `docs/coworld-protocol.md` confirms it. **Running ≠ win:** population count is the
   visible race (20 v 20 at the end) but the SCORE is wealth (5,994 v 4,894). The scorebug
   goes on wealth; population rides as the secondary figure.
2. **Dramatic beats**, ranked by what actually happened in the recording:
   - **Starvation deaths — the crush.** 24 of 64 agents die, all starvation (diffed
     frame-to-frame; `stats.agentStarvationDeaths` confirms the cause). They fall on 21
     separate timesteps between t6 and t75, 13 of them by t40, and never more than two in
     one timestep. That shape is why the feed folds: a raw row per beat is 21 rows of
     "1 settler starved", and the drama is the accumulation, not any single one.
   - **Lead changes — the race.** **Zero.** B leads from t0 and never gives it up, closing
     1,100 ahead (18.4%). No frame is tied. This matters for the design more than it looks:
     the beat the broadcast is built to catch does not occur in the reference recording, so
     every lead-change path — the stinger, the transport's gold marks, the chart's spell
     bands, the end card's "won from behind" arc — is exercised only by the test suite.
   - **The migration.** Agents converge on the resource. Sugar and spice sit on CROSSED
     diagonals (`environmentSugarPeaks` `[[22,10,4],[10,22,4]]`, `environmentSpicePeaks`
     `[[10,10,4],[22,22,4]]`), so a settler needing both cannot camp on one summit. This is
     the iconic Sugarscape image and it is what the board must show.
   - **Emergent selection.** Survivors have better vision (3.60 v 3.17) and markedly lower
     metabolism (sugar 2.15 v 3.08, spice 2.10 v 3.17) than the dead, measured on their t0
     endowments. Nobody programmed that — it emerges.
   - **Inequality.** Gini climbs 0.140 → 0.299 at its peak and settles at 0.267; final
     wealth spread 8 → 517, top five agents hold 21%. The founding result of the model.
     Note the shipped world lands BELOW the viewer's 0.28 "richest hold most" threshold at
     the buzzer, so the end card's spread sentence reads "spread fairly evenly" — correct,
     and a reminder that those thresholds are the viewer's editorial line, not the engine's.
3. **Board — a single shared 32×32 lattice.** `environment.nim cellId = x * height + y`
   (column-major; the incumbent viewer decodes this correctly). Cells carry
   `[sugar, spice, pollution]`. Both resources peak at 4; 868 of 1,024 cells carry spice at
   t0. Total sugar falls 2,297 → 1,860 and settles at 1,984; spice 2,298 → 1,850 → 2,021.
   That plateau IS the carrying-capacity result, and the per-cell churn under it is real —
   an audit once called the board "static" on the strength of the totals. Do not "fix" it.

   **Do not assert the terrain's shape in copy** — but the reason is no longer the one an
   earlier revision gave. That revision said the massif count was "a property of the SEED",
   because `configuration.nim:138-141` REPLACES an out-of-range peak coordinate with a
   random in-range one and the old defaults `[[35,15,4],[15,35,4]]` were both out of range
   on a 32-wide grid. The shipped `config.json` now pins all four peaks inside the grid, so
   that branch never fires and the terrain is fully determined by the config. The rule
   survives on its own merits: the viewer renders whatever lattice it is handed, and a
   variant may configure any number of peaks.
4. **Readable entities — agents and sugar.** Per agent the frame carries id, cell, slot,
   age, sugar, spice, metabolism, movement, vision, sex, race, tribe, sick, depressed.
   Spice is LIVE in the shipping variant (this changed; an earlier revision called it
   inert). Still inert, verified absent across all 101 frames: pollution, social links,
   disease, depression, trade, reproduction (24 deaths, **zero** births), races and tribes.
   Rendering controls for those is what makes the incumbent read as a lab tool. The live
   signals are: position, wealth, sugar, spice, metabolism, vision, age, and slot.
5. **Who is "you" — the two policy slots.** `slots[]` carries the submitted display names
   ("Population A"/"Population B"). Agents map to a slot by `decisionModel`. Every agent on
   screen belongs to a named competitor; there is no unowned population in this variant.

### Fidelity audit of the incumbent viewer (`src/sugarscape/viewer.html`)

| # | Engine truth | What the viewer does | Severity |
|---|---|---|---|
| 1 | Under the Observatory the page is served at `…/proxy/client/replay`; the sibling WS is `…/proxy/global` | `new WebSocket(…location.host + "/global")` — an absolute path that resolves off the proxy prefix | **P0, black screen hosted** |
| 2 | `coworld certify` requires a `/replay` WebSocket when no static bundle is declared (`runner.py replay_session_path`) | `coworld.nim` serves the spectator WS only at `/global`; `/replay` 404s | **P0, certification fails** |
| 3 | Score = total living wealth per slot | No score is shown anywhere; the "Populations" panel is a bare colour legend with no numbers | **P0, North Star fail** |
| 4 | The match is 100 scheduled timesteps | No clock, no progress toward the end | P1 |
| 5 | 24 agents starve across 21 timesteps; the lead never changes | No event feed, no callouts, no end card, no winner | P1 |
| 6 | Pollution, links, disease, depression, race and tribe are inert in the shipping variant (spice is not) | 9 agent-colour modes, 2 cell modes and a links toggle, most of which render nothing | P2, misleads the viewer |
| 7 | The embed is 16:9 and can be 640×360 | `grid-template-columns: minmax(440px,1fr) 340px` + a square board + three 120px charts | P1, unreadable at the embed floor |
| 8 | `cellId = x*height + y` | `x = floor(cell/height), y = cell % height` | correct — not a bug |

The incumbent is a faithful *research instrument* and a failed *broadcast*. It is kept as
the payload reference; the viewer is designed from scratch (L51).

## 0c — Art direction lock

> **The board is the original.** `reference/dtl-python/gui.py` is vendored in this repo
> and is the oracle for the LOOK, exactly as the Python model is the oracle for
> behaviour. The broadcast is a dark warm surround that seats that bright plate.

**This was the mistake worth recording.** The first lock was invented — "a 1996 Santa Fe
Institute artificial-life plate, re-lit as a broadcast: an amber topographic sugar massif
under warm raking light, with two populations of small physical beads swarming it." It
sounded right and it was researched from nothing. It produced a generated terrain batch, a
relief pass and contours that buried the per-cell resource under texture, read as fog, and
looked nothing like the model anyone recognises. The source renderer was in the repo the
whole time and was never opened. **For a port, the thing being ported is the reference —
for behaviour AND for presentation.**

What `gui.py` actually specifies, and what the viewer now does:

| Element | Original (`gui.py`) | Here |
|---|---|---|
| Field | `tkinter.Canvas(background="white")` | `#fbf8f0`, warmed a touch off pure white |
| Cell | `create_rectangle(..., outline="#c0c0c0")` | same, one rect per cell, same lattice colour |
| Cell fill | `findSugarAndSpiceColors("#F2FA00", "#9B4722")` — a two-axis interpolation from white through sugar-yellow and spice-brown | the same interpolation, ported exactly, so a spice-enabled variant renders faithfully |
| Agent | **no agent mark at all** — `lookupFillColor` recolours the whole cell rectangle, so a settler is a solid square that HIDES the sugar under it. (`create_oval` is the network overlay's per-cell shape, not the agent.) | **a deliberate deviation:** a filled dot, sized by wealth, hollow when within one timestep of starving. A dot keeps the resource visible under the swarm — the read this broadcast is built on — and matches Epstein & Axtell's own published plates |
| Agent colour | `palette[i]` per decision model — `#FA3232` red, `#3232FA` blue | the same order, each hue lifted slightly so one value reads on the white plate AND on the dark chrome |

The broadcast surround keeps its own identity, since the original has no broadcast layer to
copy: warm near-black ground, ink `#2a1f12`, paper `#f6ead2`, one sugar-gold accent
`#e8a838` taken from the world's own resource, mono restricted to tabular numbers, and a
redundant shape per seat so the read never depends on hue alone.

### The plate inverted, and resource became density — by request

The owner asked for two changes to the board: **change the white background**, and
**make sugar and spice densely packed particles rather than fully-shaded tiles.**
Both are now in, and together they settle a measurement that had been sitting
unresolved in this document.

A parallel session had filed `docs/palette-handoff.md` proposing the inversion,
with the measurement that argued for it:

- **Full sugar `#F2FA00` against an empty cell `#FBF8F0` is 1.07:1.** Not "low
  contrast" — the sugar axis carried *no* luminance signal at all, end to end.
- The spice axis was the opposite: `#9B4722` on the same cell is 6.0:1.
- No single background fixes both. Sugar is very light and spice very dark, so
  pushing the empty cell down far enough for sugar to reach 3:1 drops spice to
  1.78:1. That is why an earlier revision of this section concluded the plate had
  to stay light and the chroma-only ramp had to be accepted.

**The particle model dissolves that trade entirely**, which is the part neither
the handoff nor this document had seen. Quantity is no longer carried by a
colour at all: it is carried by HOW MANY GRAINS ARE THERE. One grain per unit
held, packed on a per-cell sub-grid. A cell with four sugar is four yellow
grains; one holding four of each is eight; an eaten cell is bare plate. That
survives greyscale, achromatopsia, a projector and a phone in sunlight — none of
which the ramp did — and it can be counted rather than estimated. The two hues
now only have to say *which* resource, not *how much*, so they are free to be
chosen for separation instead of for a ramp.

What it took to get there, since two attempts read badly and are worth recording:

- **Scattered grains are noise.** Placing each grain anywhere in its cell, small
  enough not to collide, dissolved the two sugar massifs and the two spice
  massifs into an even speckle — at that size the eye cannot integrate density
  from scattered dots. They have to PACK.
- **Raster order bands the board.** Filling the sub-grid left-to-right made every
  cell lay its first grains along its top row, and because neighbouring cells
  hold similar amounts they did it together: continuous horizontal stripes across
  the whole plate. Each resource now grows as a clump ordered by distance from
  its own corner — sugar from one, spice from the other — so a sugar-rich cell is
  a yellow clump, a spice-rich one a rust clump, and region colour follows region
  composition. That is what brings the crossed diagonals back.
- **The lattice had to go.** A drawn grid over a field of grains is a second grid
  at a second pitch, and the plate read as a halftone screen. The grains cluster
  inside their own cell with a gap at the edges, so the cell structure is drawn
  by the thing being measured rather than by scaffolding around it.

Knock-on changes the inversion forces, all applied: settlers take the bright
`seat.color` (the `board` variants were darkened for a white field and vanished
on this one) and carry an ink ring; the starving marker fills with the plate
rather than with paper, or a hollow settler becomes the brightest object on the
board; the death mote lifts to `C.loss`; the board key counts grains instead of
showing a colour ramp; the plate's edge is a lit warm rule, because a dark plate
on a dark surround has no luminance boundary of its own. `cellColor` and its
two-axis interpolation are deleted rather than left dormant.

## Phase 4 — where the gates stand

Green, and verified by looking rather than by status code:

- **`tools/test_all.sh`** — viewer staleness, the 7 byte-parity suites against the pinned
  Python oracle, and the coworld smoke test. That last one now also pins the transport's
  timestep units, the feed's ledger arithmetic, the density ramp and the larger-text
  control, the live reduced-motion listener, and focus movement on failure. The ledger
  assertion was mutation-checked: deleting the summary row fails it.
- **CI runs it.** `.github/workflows/ci.yml` — the viewer-staleness and byte-parity jobs on
  every push and pull request with no credentials, and the hosted-embed job behind the
  private `bitworld` package, which says loudly in its own step when it could not run.
- **`coworld certify`** — all ten steps, including the `/client/replay` + `/replay`
  liveness probe.
- **Looked at, through the proxy harness, at 1280×720 and the 640×360 embed floor**: early
  game, mid-game, the end card, and the larger-text ramp. Console clean; the whole app is
  one network request.

Craft debt that remains, ranked:

1. **`1.4.4 Resize Text` cannot be met the way the success criterion describes it.** The
   broadcast is set in SVG user units inside an embed whose aspect ratio the host fixes, so
   a larger default font size cannot reach it and there is no reflow to fall back on. Full
   page zoom does scale the whole thing, text included, with nothing lost; the larger-text
   control is the in-product mechanism on top of that. Stated, not claimed as passing.
2. **The board's resource ramp is chroma-only on the sugar axis** — see the decision above.
   A viewer with severe colour-vision deficiency reads the settlers, the lattice and every
   panel, but not the depth of the sugar under them.
3. **The wrap estimate is a character count, not a measurement.** `wrap()` assumes 0.52em
   average advance rather than measuring the glyphs, so a name of unusual width could still
   break a line early or late on the end card.
4. **The dense ramp is five fixed steps.** It is right for 640×360 and for the larger-text
   control at full size; it has not been tuned for the sizes in between, which simply take
   the full-size ramp.
