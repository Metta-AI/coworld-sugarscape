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

## 0r — Depth target, extracted from the reference (Agricogla)

Measured from `packages/cogweb/games/agricogla/src/client/animation/` so this build has
a concrete bar rather than a vibe.

| Dimension | Agricogla reference | Sugarscape target |
|---|---|---|
| Art batch | 18 rendered PNGs (5 tiles, 12 tokens, wordmark), inlined as data-URIs, team-recolored in code | ~18: 5 sugar-tier grain tiles ×2 variants, barren base, settler bead (1 base → 2 populations × 2 states via HSV recolor), death mote, end-card backdrop |
| Skeleton | one `<svg>` at `H=1180`, `W=round(H*16/9)`, `TOP_INSET = MARGIN + 74` derived from `BUG_H=58` | one 1920×1080 stage: canvas board + SVG HUD overlay in the same coordinate space, `TOP_INSET` derived from `BUG_H` |
| Scorebug | rank (mono) · identity dot · name (display, clipped) · score 30px · leader crown + `▲ +margin` | same, on the wealth axis, population as the secondary |
| Choreography | walk-in → work → fly-home arc → gain pop → spotlight, effect-on-arrival (`revealDelayMs`) | agents walk (interpolated) → arrive → harvest flash → starvation stagger → death mote rises |
| Timing levers | `animFactor = max(1/speed, 1/2)`; `turnDwellMs = max(BASE/speed, beat)`, `BASE_TURN_MS=2600`, `READ_PAUSE=600` | same two levers, ported: motion capped at 2× real time, frame dwell floored to the walk length |
| Ambient life | ~8 desynced loops (bob, roam, sway, smoke, glow, pulse), all `/ var(--speed)`, all killed by `prefers-reduced-motion` | terrain shimmer on regrowth, agent idle bob, slow light drift — desynced per agent, speed-aware, reduced-motion safe |
| Beat FX | ~10 keyframes (`chip-pop`, `gain-pop`, `curtain`, `roundbeat`, `endcard`, `stamp-pop`…), all `calc(Xs / var(--beat-speed,1))` | lead-change stinger, death callout, era curtain, hold-on end card — same speed-aware pattern |

## 0 — The replay brief (each bullet traced to engine truth)

Recorded episode: 32×32, 100 timesteps, 64 agents, two policy populations.

1. **Standing axis — total living wealth (sugar + spice) per population.**
   `coworld.nim buildResults` scores `int(totalWealth)` over each slot's living agents,
   and `docs/coworld-protocol.md` confirms it. **Running ≠ win:** population count is the
   visible race (16 v 16 at the end) but the SCORE is wealth (2334 v 2253). The scorebug
   goes on wealth; population rides as the secondary figure.
2. **Dramatic beats**, ranked by what actually happened in the recording:
   - **Starvation deaths — the crush.** 32 of 64 agents die, all starvation, all before
     t≈40 (diffed frame-to-frame; `stats.agentStarvationDeaths` confirms the cause). The
     dead die *far from the mountain* (mean distance 13.4 cells) while survivors sit on it
     (4.7). This is the single loudest beat.
   - **Lead changes — the race.** 5 of them: B takes the lead at t2 and holds to t62,
     A takes it, B retakes at t69, A takes it back at t71 and holds. Final margin 81 (3.5%).
   - **The migration.** Agents converge on the sugar mountain. This is the iconic
     Sugarscape image and it is what the board must show.
   - **Emergent selection.** Survivors have better vision (4.0 v 2.9) and lower metabolism
     (2.19 v 2.81) than the dead. Nobody programmed that — it emerges.
   - **Inequality.** Gini climbs 0.215 → 0.40, settling ~0.35; final wealth spread 1 → 287,
     top 5 agents hold 31%. The founding result of the model.
3. **Board — a single shared 32×32 lattice.** `environment.nim cellId = x * height + y`
   (column-major; the incumbent viewer decodes this correctly). Cells carry
   `[sugar, spice, pollution]`. In the shipping variant the terrain is **one central sugar
   mountain**, not the twin peaks of the literature: `environmentSugarPeaks` defaults to
   `[[35,15,4],[15,35,4]]`, both centred outside a 32-wide grid, so their gradients
   superpose into one massif. Render the snapshot, not the textbook.
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
| 5 | 32 agents starve; the lead changes 5 times | No event feed, no callouts, no end card, no winner | P1 |
| 6 | Spice, pollution, links, disease, depression, race, tribe are all inert in the shipping variant | 9 agent-colour modes, 2 cell modes and a links toggle, most of which render nothing | P2, misleads the viewer |
| 7 | The embed is 16:9 and can be 640×360 | `grid-template-columns: minmax(440px,1fr) 340px` + a square board + three 120px charts | P1, unreadable at the embed floor |
| 8 | `cellId = x*height + y` | `x = floor(cell/height), y = cell % height` | correct — not a bug |

The incumbent is a faithful *research instrument* and a failed *broadcast*. It is kept as
the payload reference; the viewer is designed from scratch (L51).

## 0c — Art direction lock

> **A 1996 Santa Fe Institute artificial-life plate, re-lit as a broadcast: an amber
> topographic sugar massif under a warm raking light, read from directly above, with two
> populations of small physical beads swarming it.**

- **Palette.** Warm near-black ground `#14100a` (never `#000`); one signature warm-dark ink
  line `#2a1f12` for every stroke and text outline; the sugar field ramps barren umber
  `#2b2114` → `#6b4a1c` → `#b8792a` → `#e8a838` → peak honey `#ffd97a`. Because the terrain
  owns the entire warm half of the wheel, the two competitors take the cool half:
  **Population A cyan `#3FC1D8`**, **Population B rose `#F0568A`**, each with a redundant
  shape token so the read never depends on hue alone.
- **Framing.** Full-bleed board at exact 16:9, a *subtle* corner vignette and a slight
  brightness lift over the massif so the mountain is the hero. Orthographic top-down —
  no rendered desk, no table, no furniture.
- **Type.** Display face for names, scores and titles; mono restricted to tabular numbers
  (timestep, wealth, counts); one uppercase letter-spaced eyebrow token. System fallbacks
  on every stack so a proxied embed never blanks.
- **The numeric HUD is dataviz.** Colour is held to the population and never repainted;
  numbers wear ink tokens, not the population hue; every score appears with its rank and
  its margin.

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
one is a **false bug**: total sugar genuinely plateaus after t8 (1034 → 738 → ~730 for the
rest of the episode). That plateau IS the carrying-capacity result the model is famous for,
and the per-cell churn underneath it is real and now visible. Do not "fix" it.
