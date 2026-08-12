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
| Beat FX | ~10 keyframes (`chip-pop`, `gain-pop`, `curtain`, `roundbeat`, `endcard`, `stamp-pop`…), all `calc(Xs / var(--beat-speed,1))` | lead-change stinger and hold-on end card — speed-aware, in a beats layer kept SEPARATE from the standings layer so rebuilding one never restarts the other's animation. A die-off used to raise the same plate over the board whenever three settlers went at once; on the shipped config that is most timesteps, so it is a LINE now — the settler strip under the lead band (`settlerStrip`) — and only a lead change interrupts |

## 0 — The replay brief (each bullet traced to engine truth)

Recorded episode: 50×50, 200 timesteps, 250 settlers, two policy populations, sugar AND
spice. **Re-measured against `.build/replay.spice.json`, all 201 frames.** This section
has now been wrong twice for the same reason — it was written against one recording and
left standing when the shipped variant changed under it, under a heading promising every
bullet was traced to a recording. It described a 32×32 sugar-and-spice world, then that
world was replaced by the 50×50 sugar-only one, and spice has since been restored on the
oracle's own peaks. **If you change `config.json`, re-run these numbers or delete them.**

1. **Standing axis — total living wealth (sugar + spice) per population.**
   `coworld.nim buildResults` scores `int(totalWealth)` over each slot's living agents,
   and `docs/coworld-protocol.md` confirms it. **Running ≠ win** is not academic here:
   A ends with 54 settlers to B's 32 AND the higher score (19,033 v 14,779), but the two
   figures move independently through the episode. The scorebug goes on wealth; population
   rides as the secondary figure and as the settler strip.
2. **Dramatic beats**, ranked by what actually happened in the recording:
   - **Starvation deaths — the crush.** 164 of 250 settlers die, all starvation (diffed
     frame-to-frame; `stats.agentStarvationDeaths` matches the disappearances exactly on
     all 58 timesteps that carry one, and no other cause ever fires). They fall between t3
     and t177, half of them by t16, and up to 10 in a single timestep. That front-loaded
     shape is why the feed folds: the drama is the accumulation, not any single row.
   - **Lead changes — the race. Three**, at t9, t10 and t12, with A holding it from t12 to
     the buzzer and closing 4,254 ahead (28.8%). No frame is tied. This is new: the
     sugar-only recording this replaced had ZERO, so every lead-change path — the stinger,
     the transport's gold marks, the chart's spell bands, the end card's "won from behind"
     arc — was exercised only by the test suite. Restoring the second resource gave the
     broadcast the one beat it is built to catch.
   - **The migration.** Settlers converge on the resource. Sugar and spice sit on CROSSED
     diagonals (`environmentSugarPeaks` `[[15,35,4],[35,15,4]]`, `environmentSpicePeaks`
     `[[15,15,4],[35,35,4]]` — the oracle's own), so a settler needing both cannot camp on
     one summit. This is the iconic Sugarscape image and it is what the board must show.
   - **Emergent selection.** Survivors have better vision (3.85 v 3.29) and markedly lower
     metabolism on BOTH resources (sugar 1.81 v 2.85, spice 1.84 v 2.84) than the dead,
     measured on their t0 endowments. Nobody programmed that — it emerges.
   - **Inequality.** Gini climbs 0.132 at t0 → 0.287 at the buzzer. The founding result of
     the model. Note it lands just above the viewer's 0.28 "richest hold most" threshold,
     having sat below it for most of the episode — a reminder that those thresholds are
     the viewer's editorial line, not the engine's.
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

**And the two hues had to be matched for brightness.** `#F2FA00` sugar measures
L=0.872 against `#9B4722` spice at L=0.115 — a 4.7:1 luminance gap between the
two things the viewer is being asked to compare. At equal coverage the yellow
simply looked like more, so the eye read a sugar majority on a board that did not
have one. Sugar is a warm white `#f4ecdb` (L=0.800) and spice a lit amber
`#f0a63c` (L=0.478) now: a 1.5:1 gap, close enough that equal masses read as
equal masses. Hue says *which* resource; density says how much.

What it took to get there, since three attempts read badly and none of them is
obviously wrong until you look at it:

- **Scattered grains are noise.** One grain per unit, placed anywhere in its cell
  and small enough not to collide, dissolved the two sugar massifs and the two
  spice massifs into an even speckle — at that size the eye cannot integrate
  density from isolated dots.
- **A packed sub-grid is a halftone screen.** One grain per unit on a per-cell
  sub-grid is legible and countable, but it is a regular pitch inside a regular
  pitch, which is a printing artefact rather than a landscape. Filling it in
  raster order was worse: every cell laid its first grains along its top row, and
  because neighbouring cells hold similar amounts they did it together, striking
  continuous horizontal bands across the whole plate.
- **One particle size reads as television static.** Real sand has grades. The
  grains vary from 0.65× to 1.6× and the mass stops looking generated.

What works is many fine particles per unit scattered across the whole cell with
no inset, so neighbouring cells merge into one continuous field and the drifts
run across cell boundaries. It is drawn as a small sheet of pre-rendered tiles —
one per (sugar, spice) pair, three variants each so the repeat is invisible,
rebuilt only when the board size changes — because at cloud density a full board
is a quarter of a million fills per timestep, which is exactly the per-frame cost
that made an earlier build stutter.
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
