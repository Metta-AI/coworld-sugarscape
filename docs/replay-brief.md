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
| Timing levers | `animFactor = max(1/speed, 1/2)`; `turnDwellMs = max(BASE/speed, beat)`, `BASE_TURN_MS=2600`, `READ_PAUSE=600` | same two levers, ported: motion capped at 2× real time, frame dwell floored to the walk length |
| Ambient life | ~8 desynced loops (bob, roam, sway, smoke, glow, pulse), all `/ var(--speed)`, all killed by `prefers-reduced-motion` | **none, deliberately** — the lattice is a scientific plate and idle motion on it is noise; the movement in this game is the swarm itself |
| Beat FX | ~10 keyframes (`chip-pop`, `gain-pop`, `curtain`, `roundbeat`, `endcard`, `stamp-pop`…), all `calc(Xs / var(--beat-speed,1))` | lead-change stinger, die-off callout, hold-on end card — speed-aware, in a beats layer kept SEPARATE from the standings layer so rebuilding one never restarts the other's animation |

## 0 — The replay brief (each bullet traced to engine truth)

Recorded episode: 32×32, 100 timesteps, 64 agents, two policy populations.

1. **Standing axis — total living wealth (sugar + spice) per population.**
   `coworld.nim buildResults` scores `int(totalWealth)` over each slot's living agents,
   and `docs/coworld-protocol.md` confirms it. **Running ≠ win:** population count is the
   visible race (16 v 16 at the end) but the SCORE is wealth (2334 v 2253). The scorebug
   goes on wealth; population rides as the secondary figure.
2. **Dramatic beats**, ranked by what actually happened in the recording:
   - **Starvation deaths — the crush.** 32 of 64 agents die, all starvation (diffed
     frame-to-frame; `stats.agentStarvationDeaths` confirms the cause). 28 of them go
     before t40; the last four straggle in at t61, t64, t79 and t82. The dead die *far
     from the sugar* — mean **13.07** cells to the nearest configured peak — while
     survivors sit on it at **3.90**. (Metric: Euclidean distance in lattice cells to the
     nearer of the two peaks in the recorded `environmentSugarPeaks`.) This is the single
     loudest beat.
   - **Lead changes — the race.** **4** of them: A leads at t0, B takes it at t2 and holds
     to t62, A takes it, B retakes at t69, A takes it back at t71 and holds. Final margin
     81 (3.5%). (An earlier draft said five and then listed four; four is correct.)
   - **The migration.** Agents converge on the sugar mountain. This is the iconic
     Sugarscape image and it is what the board must show.
   - **Emergent selection.** Survivors have better vision (4.0 v 2.9) and lower metabolism
     (2.19 v 2.81) than the dead. Nobody programmed that — it emerges.
   - **Inequality.** Gini climbs 0.215 → 0.40, settling ~0.35; final wealth spread 1 → 287,
     top 5 agents hold 31%. The founding result of the model.
3. **Board — a single shared 32×32 lattice.** `environment.nim cellId = x * height + y`
   (column-major; the incumbent viewer decodes this correctly). Cells carry
   `[sugar, spice, pollution]`.

   **How many mountains a world has is a property of the SEED, not the config** — an
   earlier draft of this brief got that wrong and a masthead string was built on it.
   `environmentSugarPeaks` defaults to `[[35,15,4],[15,35,4]]`, both out of range on a
   32-wide grid, and `configuration.nim:137-141` does **not** clamp or superpose them: it
   **replaces** each out-of-range coordinate with `rng.randomInteger(0, width-1)`. In the
   recorded episode they were re-seated to `[[15,17,4],[14,15,4]]` — 2.24 cells apart,
   which is why that world has one massif. Another seed can put them anywhere. Render the
   snapshot, and never assert the terrain's shape in copy.
4. **Readable entities — agents and sugar.** Per agent the frame carries id, cell, slot,
   age, sugar, spice, metabolism, movement, vision, sex, race, tribe, sick, depressed.
   In the shipping variant **spice, pollution, social links, disease, depression, trade,
   reproduction, races and tribes are all inert** (verified zero/absent across all 101
   frames). Rendering controls for them is what makes the incumbent read as a lab tool.
   The live signals are: position, wealth, metabolism, vision, age, and slot.
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
| 5 | 32 agents starve; the lead changes 4 times | No event feed, no callouts, no end card, no winner | P1 |
| 6 | Spice, pollution, links, disease, depression, race, tribe are all inert in the shipping variant | 9 agent-colour modes, 2 cell modes and a links toggle, most of which render nothing | P2, misleads the viewer |
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

### The plate stays light — a decision, with the measurement that argues against it

A parallel session measured the plate and filed `docs/palette-handoff.md` proposing that the
ground be **inverted to warm near-black**, keeping `gui.py`'s blend structure but moving the
zero end to `#1d1811` and lifting spice to `#cb3760`. Its measurement is correct and worth
recording, because it is the strongest argument against the lock above:

- **Full sugar `#F2FA00` against an empty cell `#FBF8F0` is 1.07:1.** That is not "shallow
  cells are low contrast" — it is the sugar axis carrying *no* luminance signal at all, end
  to end. The whole ramp is chroma.
- The spice axis is the opposite: `#9B4722` against the same empty cell is 6.0:1.

**The plate stays light anyway, and the reason is arithmetic, not taste.** No single
background satisfies both ramps. Sugar is very light and spice is very dark, so pushing the
empty cell down far enough for sugar to reach 3:1 (about L = 0.244, a mid warm brown) drops
spice to 1.78:1. Inverting all the way to `#1d1811` buys sugar its luminance and spends
spice's. There is no ground colour that gives both 3:1 while keeping the two hues, and the
two hues are what makes the picture Sugarscape.

Given that, the tie is broken by the two things that are not arithmetic. The owner rejected
an invented art direction once already, in those words — *"this doesn't look like what james
showed me the original game was like"* — and `.harness/screenshots/palette-proposal.png`
renders both plates side by side from the same frame of the real recording: on the light
plate the two sugar massifs, the two spice massifs and the carved trails of eaten cells all
separate cleanly; the inverted plate reads as a crimson heatmap and loses the eaten trails
into the ground.

What the handoff was right about, and what has been taken from it:

- **The board key now draws BOTH ramps.** It taught the yellow of sugar while most of the
  shipped board is the rust of spice — the dominant colour on the plate was the one thing
  the legend did not explain.
- **Every settler carries an ink ring.** A bare dot was separated from the terrain by hue
  alone, on the one channel the terrain already uses — a red settler on rust spice. The ring
  makes it structural, at any resource depth and under any colour-vision deficiency.
- `resourceName()` and the two-axis `cellColor` branch are live for the first time and were
  checked at both densities.

The open task on the board is left open rather than closed: inverting the plate is a
product decision the owner has already ruled on once, and it is theirs to reverse.

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
