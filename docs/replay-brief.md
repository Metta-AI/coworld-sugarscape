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

## Phase 4 — where the gates stand

Correctness and delivery are green: `coworld certify` passes end to end (including the
replay-liveness probe of `/client/replay` + `/replay`), the native suite and the coworld
smoke test pass, the document loads through the proxy harness with a clean console, all
three failure modes fail visibly, and the control chrome measures 15.7:1 text contrast
with 24px minimum targets at the 640×360 floor.

**The adversarial aesthetic gate has NOT cleared the >90 bar** — 64/100, then 70/100 after
the first fix round, then the crater/title/axis fixes above (not yet re-scored). Both
audits confirmed 9 of 10 AI-default tells PASS on measured evidence, so the failure is not
"it looks AI-default"; it is specific craft debt. Known open items, ranked:

1. **The 640×360 floor is a linear downscale, not a responsive design.** The rail keeps the
   same three panels and four feed rows at half scale, so roughly a dozen small labels fall
   below legibility (chart axis ends, `t0`/`t100`, "lead, in sugar", the settler sublines,
   "unequal", "36 alive of 64", the feed timestamps). Needs the rail to shed or promote
   content at the floor rather than scale linearly. The scorebug and board already survive.
2. **The event feed goes stale.** At t47 the newest row is `t16–38`, because the coalescer
   merges a long quiet stretch and nothing newer has happened. It should surface the current
   state (or the standing beat) rather than leaving a panel titled "what just happened"
   showing something nine timesteps old, and lead changes should not scroll off behind
   routine starvation.
3. **The tertiary ink token `#6f6250` measures 3.21:1** on the panel — under AA for body
   text. Fine for the large numerals it mostly carries, wrong for the small captions.
4. **The race chart is ~70% empty** — the whole leading half is blank when one population
   holds the lead throughout, and everything right of the cursor is unused.
5. **`CARRYING CAPACITY 55` is a bare number** and reads as contradicting the `36 alive of
   64` caption beneath it; it needs a unit or an explicit "the world supports N" framing.
6. **The end-card backdrop is a side-elevation painted peak** inside a frame whose board is
   an orthographic top-down render — two incompatible depictions of the same mountain.
7. **Contours are present but faint**, and vanish entirely at the embed floor, so the
   "topographic plate" half of the lock is only partly delivered.

The audit also raised "the board looks static — the resource never visibly changes." That
one is a **false bug**: total sugar genuinely plateaus after t8 (1034 → 738, then 711–765 for the
rest of the episode, closing at 763). That plateau IS the carrying-capacity result the model is famous for,
and the per-cell churn underneath it is real and now visible. Do not "fix" it.
