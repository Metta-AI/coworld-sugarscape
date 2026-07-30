# Handoff: the board now has spice, and the plate needs inverting

Written by a separate session that was asked "I can't tell what is sugar and what
is spice." Two findings, one of which is already fixed and one of which is left
for whoever owns `viewer/broadcast.js` — that file was being actively edited
while this was written, so nothing here has been applied to it.

## 1. Already done: the world actually has spice now (and two sugar mountains)

`config.json` and `coworld_manifest.json` (default variant) were changed, and
`.build/replay.json` was re-recorded against them. The same change is on `main`.

Three defects were behind the "where is the spice?" question:

- **Spice was silently zeroed.** `defaults.json` declares spice peaks with
  amplitude 4, which reads as enabled, but `environmentMaxSpice: 0` makes
  `configuration.nim:143-145` clamp both peaks to 0. Regrow rate, agent spice
  metabolism and starting spice were 0 too. Verified across all 101 frames of the
  old replay: **0 / 1024 cells** carried spice.
- **The two sugar mountains had collapsed into one.** `defaults.json` carries
  DTL's 50x50 coordinates `[[35,15,4],[15,35,4]]`, but the variant runs 32x32, so
  `configuration.nim:138` randomises any coordinate `> width`. They landed at
  `[[15,17,4],[14,15,4]]` — about two cells apart. That is why the board showed
  one amorphous blob instead of Sugarscape's iconic pair.
- The manifest described the variant as a "sugar-and-spice world", which it was
  not.

The variant now sets, mirroring DTL's own shipped `reference/dtl-python/config.json`
with peaks scaled 50 -> 32:

```json
"environmentMaxSugar": 4,
"environmentMaxSpice": 4,
"environmentSugarRegrowRate": 1,
"environmentSpiceRegrowRate": 1,
"environmentSugarPeaks": [[22, 10, 4], [10, 22, 4]],
"environmentSpicePeaks": [[10, 10, 4], [22, 22, 4]],
"agentSugarMetabolism": [1, 4],
"agentSpiceMetabolism": [1, 4],
"agentStartingSugar": [10, 40],
"agentStartingSpice": [10, 40]
```

Verified in the re-recorded replay: **868 / 1024 cells** carry spice (max 4);
agents finish holding 5398 spice against 5490 sugar; sugar concentrates in the
WS/EN quadrants (192/192 high cells) and spice in WN/ES (180/205) — the crossed
diagonals are back. No player change was needed: the engine already ranks
candidates with `welfareRewards(agent, sugarReward, spiceReward)` and
`coworld.nim` already scores `agent.sugar + agent.spice`.

### What this breaks in the viewer as it stands

`state.maxSpice` is now 4 instead of 0, so several code paths that were dormant
switch on for the first time and have never been seen with real data:

- `resourceName()` starts returning `"sugar + spice"`, which changes the
  masthead, the chart caption and the end card. That is correct now — but check
  the strings still fit at the compact width.
- `boardKey()` draws a sugar ramp only (`cellColor(step / 4 * state.maxSugar, 0)`).
  With spice on the board it now under-describes the picture and needs a second
  ramp. This is the thing the original complaint was actually about.
- The two-axis branch of `cellColor` is live for the first time.

## 2. Not done: the plate should invert. Spec below.

Do not just recolour the yellow. The measured problems with the gui.py plate on
this stage are:

- `#F2FA00` on `#FBF8F0` is **1.09:1**. Shallow cells — most of the board, most
  of the time — are invisible, so the resource gradient that is the whole point
  of the image cannot be read.
- A near-white plate inside the `#14100a` surround is a glare sandwich. The
  brightest thing on a broadcast should be the thing that matters, and here that
  is the settlers, not bare ground.

### Two approaches that were tried and rejected — don't repeat them

Both were rendered against the real replay and judged from the image, not
reasoned about:

1. **Two ramps summed additively** (empty -> gold for sugar, empty -> rose for
   spice, deltas added). Blows out to neon across almost the whole board, because
   ~85% of cells hold *both* resources. Unusable.
2. **Brightness = total resource, hue = which resource dominates.** No blowout,
   but muddy: interpolating gold to rose passes through brown, and it throws away
   the luminance separation that makes the original readable at all. The original
   works *because* sugar and spice sit far apart in luminance as well as hue.

### What works: keep gui.py's structure, invert the ground

Keep the original's blend math and hue identities. Change only the zero end,
lift spice so it reads on dark, and push spice off the seat red.

```js
const C_EMPTY = [29, 24, 17];   // warm near-black ground; NEVER pure black
const C_SUGAR = [246, 214, 78]; // gui.py #F2FA00, warmed off pure acid
const C_SPICE = [203, 55, 96];  // gui.py #9B4722, lifted to read on dark and
                                // pushed off seat red so settlers stay separable

function cellColor(sugar, spice) {
  const sf = state.maxSugar > 0 ? Math.min(1, sugar / state.maxSugar) : 0;
  const pf = state.maxSpice > 0 ? Math.min(1, spice / state.maxSpice) : 0;
  const blend = mix(C_SUGAR, C_SPICE, 0.5);
  return mix(mix(C_EMPTY, C_SPICE, pf), mix(C_SUGAR, blend, pf), sf);
}
```

Corners of the space: empty -> near-black, sugar-only -> gold, spice-only ->
crimson, both -> warm orange. `GRID_HEX` becomes `#332a1e` (one step up from the
ground) instead of `#c6c4bd`.

### Knock-on changes the inversion forces

These are not optional — the plate flip breaks each of them:

- **Settlers must switch from `seat.board` to `seat.color`.** The `board`
  variants (`#c22318`, `#2340c4`) were picked to sit on a *white* plate; on the
  dark plate they disappear.
- **Add a dark ring** (~1.6px at board scale, `#1a140e`) around each settler.
  Spice terrain is red and seat 0 is red; a ring makes the separation structural
  instead of depending on hue never colliding.
- **The starving marker inverts.** It currently fills near-white
  `rgba(251,248,240,.9)` to read as hollow against a white plate. On dark that
  becomes the brightest blob on the board — the opposite of the intended meaning.
  Fill with the ground colour and stroke with `seat.color`.
- **The death mote** is `#a8321a`, chosen "dark enough for the plate". Lift it to
  `C.loss` (`#e2703a`) or it vanishes.
- **`boardKey()` needs both ramps** — a sugar ramp and a spice ramp, since the
  board now carries both.
- Re-check the `C.ink` mat and drop shadow around the board. A dark plate on a
  dark surround may lose its edge; a warm hairline probably reads better than the
  current mat.

### Verifying

`.harness/screenshots/palette-proposal.png` in the main checkout is a
side-by-side of current vs proposed, rendered from the real re-recorded replay at
t40. Check the result at the 640x360 embed floor as well as full size — at that
size the lattice is already suppressed (`state.compact`), and the dark plate
changes how the settler ring reads against terrain.
