"use strict";

/* Sugarscape broadcast viewer.
 *
 * The whole broadcast lives in ONE 1920x1080 stage: a canvas board and an SVG
 * overlay share that coordinate space and scale together, so the short 16/9
 * hosted embed can never clip the scorebug off the top or starve the board of
 * height. Everything a viewer must READ is in the overlay; the floating HTML
 * carries only zero-data controls.
 *
 * The replay payload is `sugarscape.replay.v1`: a frame per recorded timestep
 * carrying the full sugar/spice/pollution lattice, every living agent, the
 * policy slots and the canonical aggregate statistics. Frames arrive either
 * over the spectator WebSocket (the container-backed path this ships on) or by
 * fetching an artifact named in `?replay=` (which is all a static bundle would
 * need). Nothing here mutates simulation state.
 */

// ---------------------------------------------------------------------------
// Theme — the Phase-0c art-direction lock, as tokens. Every colour the viewer
// paints comes from this block or from the gui.py port's own named constants
// (SUGAR_HEX / SPICE_HEX / PLATE_HEX / GRID_HEX); nothing below writes a colour
// literal inline.
// ---------------------------------------------------------------------------

const C = {
  ground: "#14100a",
  ink: "#2a1f12",          // the brand line; NEVER pure black
  paper: "#f6ead2",        // warm off-white; NEVER pure white
  muted: "#a8977c",
  dim: "#9c8b70",   // lifted twice: #6f6250 was 3.3:1, #8a7a62 passed by only 0.07
  border: "#4a3620",
  panel: "rgba(20,15,8,.86)",
  gold: "#e8a838",         // sugar — the world's own accent
  loss: "#e2703a",
  // Translucent surfaces, kept here rather than inline so the whole art
  // direction is still one block. Alpha is the point of each of these: they sit
  // over the board or over another panel and must let it through.
  card: "rgba(31,24,14,.985)",     // the end card's plate
  cardScrim: "rgba(10,7,4,.965)",  // full-stage dim behind the end card
  rowBack: "rgba(20,15,8,.72)",    // a result row inside the card
  wash: "rgba(246,234,210,.07)",   // the Lorenz square's fill
  hairline: "rgba(246,234,210,.34)",
  hairlineSoft: "rgba(246,234,210,.16)",
  // The equality diagonal is the whole POINT of a Lorenz chart - without it the
  // gold curve is an unreferenced squiggle - and it measured 1.84:1. C.muted is
  // 6.7:1 on the panel; a non-text graphic needs 3.
  guide: "#a8977c",               // the equality diagonal
  axis: "rgba(246,234,210,.42)",   // the chart's baseline, the strongest rule
  trackBed: "rgba(246,234,210,.14)",
  bugScrimTop: "rgba(12,9,5,.92)",
  bugScrimEnd: "rgba(12,9,5,0)",
  // Board-side values. The mat's shadow is warm rather than pure black, the
  // The plate is dark now, so its edge cannot be carried by luminance against a
  // dark surround: the mat is a lit warm rule rather than a shadow.
  mat: "rgba(20,12,4,.5)",
  edge: "#5c452a",
  // The surround, which is a place rather than a slab. See drawGround for why
  // there is a horizon behind the plate, why the corners fall away from it, and
  // why the far sand blowing over both is held this close to invisible.
  horizon: "rgba(126,86,36,.17)",
  horizonFar: "rgba(126,86,36,.06)",
  horizonOut: "rgba(126,86,36,0)",
  hollowIn: "rgba(8,5,2,0)",
  hollow: "rgba(8,5,2,.5)",
  dust: "rgba(246,234,210,.05)",     // far sand, lit by nothing
  dustWarm: "rgba(240,166,60,.05)",  // the same spice, a long way downwind
  // Not colours: the two ends of the alpha ramp that feathers a grain tile into
  // its neighbours. Here rather than inline so the block really is every literal.
  maskIn: "rgba(0,0,0,1)",
  maskOut: "rgba(0,0,0,0)",
};

// The original assigns palette colours to decision models in order
// (reference/dtl-python/gui.py: palette[0] red, palette[1] blue), so the two
// populations are red and blue exactly as in the model everyone recognises.
// Each hue is lifted slightly from the source so the same colour is legible
// BOTH as a dot on the white plate and as a chip on the dark broadcast panels,
// and each carries a redundant shape so the read never depends on hue alone.
//
// `text` is the second value, for the places a seat colour carries INK rather
// than filling a shape — the chart's pole label, the strip's head figures and
// the lead readout, which sit on the lead band itself where the chip hues
// measure 3.3-3.6:1. The chips themselves are used only as fills, where they
// are not text at all.
// (An earlier note here claimed the C.ink halo behind every label was the
// binding background. It is not: at three stage units the halo is a sub-pixel
// rim, and the surface underneath is the panel — darker than the ink, so the
// chips already cleared AA there. The lift is for the band.)
const SEATS = [
  // #f5504a on ink 4.69:1 -> #ff6b60 5.80:1
  { color: "#f5504a", text: "#ff6b60" },   // gui.py palette[0] #FA3232
  // #5a7cff on ink 4.40:1 (FAILS AA) -> #6b8bff 5.19:1
  { color: "#5a7cff", text: "#6b8bff" },   // gui.py palette[1] #3232FA
  { color: "#6bd47f", text: "#6bd47f" },   // palette[2] #32FA32, 8.7:1
  { color: "#52d6e8", text: "#52d6e8" },   // palette[3] #32FAFA, 9.3:1
];

const F = { display: "Space Grotesk", mono: "IBM Plex Mono" };

// ---------------------------------------------------------------------------
// Geometry — one 16:9 stage; the board top-inset derives from the scorebug
// height so the two can never overlap by construction.
// ---------------------------------------------------------------------------

const W = 1920;
const H = 1080;
const RENDER_SCALE = 1.5;          // canvas supersampling; see setTransform below
const MARGIN = 30;
const BUG_H = 92;
// The clear space under the scorebug band. 22 was generous for a band whose type
// has since come down by a quarter.
const BAND_GAP = 12;
const KEY_H = 34;
/* The transport gets its OWN LANE, and the lane is measured in PIXELS.
 *
 * The floating pill is laid out in CSS percentages of the stage; the board is
 * laid out here in stage units; the two were never reconciled, so the pill sat
 * ON the board — two lattice rows at 1280, and THREE at 640, where its pixel
 * floors bite while the board scales down. The compact variant occluded more of
 * the primary read surface than the full-size one.
 *
 * What the pill actually needs is a physical 34 CSS px: a 24px minimum target
 * plus padding and border. As a CONSTANT 104 units that was right at the 640
 * floor and wrong everywhere above it — at 1280 it reserved 104 units for a pill
 * that needed 51, and the board paid the difference in every row of its lattice.
 * Derived from the live width it costs exactly what it needs at any size.
 */
const TRANSPORT_PX = 34;
const RAIL_GUTTER = 26;

/* The board is as big as the chrome will let it be, and the chrome is now honest
 * about what it costs.
 *
 * Every number this is made of used to be a constant tuned at one width, so the
 * board was fixed at 798 of 1080 units — 74% of the height and 42% of the width —
 * while the rail beside it took 54% of the width to hold three panels of short
 * text. Once the type became pixel-anchored the chrome around the board was
 * provably oversized at every width above the floor: the scorebug reserved a
 * fixed 92 units for two lines that had shrunk by a quarter, the key reserved its
 * own 34-unit row for one line of legend, and the transport reserved twice what
 * it needed. Reclaiming those puts ~30% more area under the lattice, which is the
 * thing the broadcast is actually about.
 *
 * Recomputed on every resize rather than at load, because all three of those
 * depend on the width the stage is being shown at. BOARD and RAIL are mutated in
 * place: everything downstream reads their fields at draw time. */
const BOARD = { x: MARGIN, y: 0, w: 0, h: 0 };
const RAIL = { x: 0, y: 0, w: 0, h: 0 };
let transportH = 104;
let keyH = KEY_H;

function layoutStage() {
  const perPixel = unitsPerPixel();
  transportH = Math.max(44, Math.round(TRANSPORT_PX * perPixel));
  // The key is ONE LINE of legend and had a fixed 34-unit row for it, which is
  // the caption step plus 16 units of nothing at any width above the floor.
  keyH = Math.max(20, Math.round(T(18) * 1.12));
  const top = BUG_H + BAND_GAP + keyH;
  BOARD.y = top;
  BOARD.w = H - top - MARGIN - transportH;
  BOARD.h = BOARD.w;
  RAIL.x = BOARD.x + BOARD.w + RAIL_GUTTER;
  RAIL.y = BUG_H + BAND_GAP;
  RAIL.w = W - RAIL.x - MARGIN;
  RAIL.h = H - RAIL.y - MARGIN - transportH;
  // The transport is laid out in CSS and must span the board it belongs to. That
  // was a hardcoded 41.6% (798/1920); the board moves now, so the width goes over
  // as a custom property rather than being restated in the stylesheet.
  document.documentElement.style.setProperty(
    "--board-width", `${(BOARD.w / W * 100).toFixed(2)}%`);
}

// ---------------------------------------------------------------------------
// Tempo — two independent levers (the Agricogla model).
//   animFactor  caps motion so it never plays faster than ANIM_MAX x real time.
//   frameDwellMs floors the auto-advance so speed collapses DEAD TIME between
//   timesteps, never the walk itself.
// ---------------------------------------------------------------------------

// The board's motion IS the product, so reduced motion does not disable it -
// it stops the replay auto-advancing, snaps between timesteps instead of
// interpolating, and drops the death rings. The viewer can still step and scrub.
//
// Read LIVE, not once at load. The preference is changed while pages are open -
// by a system accessibility toggle, by a browser setting, by an OS switching
// theme on a schedule - and a viewer that sampled it at boot kept animating for
// the rest of the session for someone who had just asked it to stop.
const motionQuery = typeof matchMedia === "function"
  ? matchMedia("(prefers-reduced-motion: reduce)")
  : null;
let reducedMotion = Boolean(motionQuery && motionQuery.matches);
if (motionQuery) {
  const onMotionChange = (event) => {
    reducedMotion = event.matches;
    // ONE direction only. Turning the preference on stops the replay at once,
    // which is the whole point. Turning it off used to force-START playback -
    // over an explicit pause, for anyone whose OS flips the setting on a
    // schedule. Resuming is the viewer's decision, not the media query's.
    if (reducedMotion && frames.length > 0) setPlaying(false);
  };
  // Safari before 14 has no addEventListener on a MediaQueryList.
  if (typeof motionQuery.addEventListener === "function") {
    motionQuery.addEventListener("change", onMotionChange);
  } else if (typeof motionQuery.addListener === "function") {
    motionQuery.addListener(onMotionChange);
  }
}

const ANIM_MAX = 3;
const BASE_FRAME_MS = 620;
const READ_PAUSE = 150;
const MOTE_MS = 1500;
const SPEEDS = [0.5, 1, 2, 4];

// With ANIM_MAX at 2 both levers saturated there, so pressing 4x changed the
// label and nothing else. At 3 the dwell floor keeps shortening past 2x while
// motion still never plays faster than 3x real time.
function animFactor(speed) {
  return Math.max(1 / Math.max(speed, 0.05), 1 / ANIM_MAX);
}

/** How long to hold each timestep. The walk between two timesteps is the beat
 *  and must always play in full, so the dwell is the capped walk plus a pause
 *  to read it. Because animation is capped at ANIM_MAX, raising the speed past
 *  that point shortens the walk no further and only the pause remains constant
 *  - which is what stops a fast replay from becoming unreadable. */
function frameDwellMs(speed) {
  return BASE_FRAME_MS * animFactor(speed) + READ_PAUSE;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const board = document.getElementById("board");
const context = board.getContext("2d");
const hud = document.getElementById("hud");
const notice = document.getElementById("notice");
const controls = {
  container: document.getElementById("controls"),
  play: document.getElementById("play"),
  glyph: document.getElementById("play-glyph"),
  back: document.getElementById("step-back"),
  forward: document.getElementById("step-forward"),
  scrub: document.getElementById("scrub"),
  speed: document.getElementById("speed"),
  text: document.getElementById("text-size"),
};

const frames = [];
const frameIndexByTimestep = new Map();
const events = [];               // derived beats, in frame order
const wealthSeries = [];         // [{ timestep, scores: number[], population: number[] }]
const motes = [];                // transient death effects

const state = {
  streamId: null,
  cursor: 0,                     // fractional index into frames
  playing: true,
  speed: 1,
  live: false,                   // true while a live episode is still producing frames
  finished: false,
  maxTimestep: 0,
  maxSugar: 1,
  maxSpice: 0,
  maxWealth: 1,
  startingPopulation: 0,
  lastDrawnIndex: -1,
  holdUntil: 0,
  truncated: false,
  // Whether the very first timestep was seen. A spectator joining past the
  // server's live backlog cap has not, so "N of M survived" would be a fiction.
  sawStart: false,
  // The overlay scales with the stage, so at the 640x360 embed everything in the
  // rail shrinks by two thirds and a dozen small labels fall under 7px. Below
  // this width the rail sheds detail and sizes up instead of scaling down.
  compact: false,
  // The viewer's own "larger text" switch, which forces the compact ramp at any
  // size. See LARGE_TEXT below.
  largeText: false,
};

/* Density.
 *
 * The whole broadcast is drawn in a 1920-unit stage that is letterboxed into the
 * embed, so a stage unit is 1/3 of a CSS pixel at the 640x360 floor. A label set
 * at 18 units renders at SIX pixels there. Scaling every size by a constant did
 * not fix it: 18 x 1.28 is still 7.7px, and pushing the constant high enough to
 * clear 11px blew the panels apart because the BIG type grew by the same factor.
 *
 * So compact does not scale — it SWITCHES RAMPS. Five steps, with everything
 * below the caption step collapsing INTO it. The panels pay for that in content,
 * not in overflow: compact drops the Lorenz curve, the chart's axis annotations,
 * the crown, a feed row, and the scorebug's secondary line, and shortens
 * population names to their last word.
 *
 * THE RAMP IS IN CSS PIXELS, NOT STAGE UNITS, and that is the whole point of this
 * rewrite. It used to be five constants in stage units — 34, 40, 52, 66, 92 —
 * picked so the smallest landed at 11.3 CSS px at the 640 floor. But a stage unit
 * is 1/3 of a pixel at 640 and 1/1.64 of one at the 1174 switch-over, so those
 * same constants printed the caption at 11.3px at the floor and at 20.8px just
 * under the threshold, and the hero at 30.7px and 56px. The ramp was doing its
 * job at exactly one width and shouting everywhere else — which is what a stage
 * at 800 looked like: type built for a phone, rendered half again as large.
 *
 * Anchored to pixels it is the same physical size at every width in the band, and
 * it meets the sparse ramp exactly at DENSE_BELOW by construction rather than by
 * a constant that has to be re-tuned whenever the threshold moves.
 *
 *   caption 11.3px · label 13.3px · body 17.3px · figure 22px · hero 30.7px
 */
const COMPACT_PX = [
  [18, 11.3],       // caption
  [22, 13.3],       // label
  [30, 17.3],       // body
  [44, 22.0],       // figure
  [Infinity, 30.7], // hero
];

/** Stage units per CSS pixel at the width the stage is actually being shown at. */
function unitsPerPixel() {
  return W / Math.max(1, state.stageWidth || W);
}

/* The two reasons type gets bigger are NOT the same reason, and conflating them
 * broke the accessibility control.
 *
 * A SMALL STAGE needs a physical floor: whatever the width, nothing may print
 * below ~11 CSS px. That is a floor, so it does nothing once the stage is wide
 * enough to clear it on its own.
 *
 * A VIEWER ASKING FOR LARGER TEXT needs a multiplier: half again the design's own
 * size, at any width, including a 1600px stage that is nowhere near the floor.
 * Written as a floor it would have been a no-op at exactly the sizes where
 * someone reaching for it is most likely to be sitting — the control would have
 * silently done nothing on a desktop. */
const LARGE_TEXT_SCALE = 1.5;

/** Map a type size onto the current density's ramp. */
function T(size) {
  let mapped = size;
  if (state.compact) {
    const perPixel = unitsPerPixel();
    // Never BELOW the sparse size: compact exists to make small stages legible,
    // and a step that came out smaller than the size it replaced would be a
    // regression dressed as a ramp.
    for (const [limit, pixels] of COMPACT_PX) {
      if (size <= limit) { mapped = Math.max(size, pixels * perPixel); break; }
    }
  }
  return state.largeText ? mapped * LARGE_TEXT_SCALE : mapped;
}

/** Geometry that must stay proportional to the stage — a swatch, a dot radius, a
 *  rule's width. These do NOT take the type ramp: floored to a caption step a
 *  6-unit dot becomes a blob that eats the label beside it. Tracks the same
 *  pixel anchor as the type, so marks and labels shrink together. */
function G(size) {
  const mapped = state.compact ? size * Math.max(1, 1.34 * unitsPerPixel() / 3) : size;
  return state.largeText ? mapped * LARGE_TEXT_SCALE : mapped;
}

/** The advance to leave after a run of text set at `size`. The overlay lays its
 *  legend out by hand, so this has to track the REAL type size — a fixed
 *  per-character advance overlapped every label the moment the ramp changed. */
function advance(content, size) {
  return content.length * size * 0.56;
}

function dense() {
  return state.compact || state.largeText;
}

/* Where the two ramps meet.
 *
 * This was a bare `width < 900`, and it was a CLIFF rather than a floor: one
 * pixel above it the sparse ramp applied raw, so a 901-unit stage printed the
 * smallest label at 7.0 CSS px - worse than the 640 floor the compact ramp was
 * built to cure, and squarely in the 900-1300 band most article embeds live in.
 *
 * The threshold is not a taste call, it is arithmetic. The smallest size the
 * sparse ramp carries is MIN_SPARSE units on a 1920-unit stage, so it clears
 * MIN_TYPE_PX only once the stage is MIN_SPARSE / MIN_TYPE_PX * 1920 wide.
 * Below that width the compact ramp takes over, which is always LARGER, never
 * smaller. Both sides of the switch are legible; only the content differs.
 */
const MIN_TYPE_PX = 11;
const MIN_SPARSE = 18;
const DENSE_BELOW = Math.ceil((MIN_TYPE_PX / MIN_SPARSE) * W);   // 1174

function measureDensity() {
  const width = document.getElementById("stage").getBoundingClientRect().width;
  const compact = width > 0 && width < DENSE_BELOW;
  // The width itself is now a live input, not just the side that chose the ramp:
  // the compact steps are pixel-anchored, so every T() and G() reads it.
  const moved = width > 0 && width !== state.stageWidth;
  if (width > 0) state.stageWidth = width;
  if (moved) layoutStage();
  if (compact === state.compact) {
    if (moved) {
      standingsSignature = "";
      beatsSignature = "";
      terrainShown = null;
    }
    return;
  }
  state.compact = compact;
  syncLargeText();
  standingsSignature = "";
  beatsSignature = "";
}

/** Reflect the switch honestly, INCLUDING when it can do nothing.
 *
 *  Below DENSE_BELOW the compact ramp is already in force and is already the
 *  largest this viewer has, so pressing the button changed not one pixel — while
 *  it still reported `aria-pressed="true"` and announced "Larger text, on". A
 *  control that announces a state change it cannot deliver is worse than no
 *  control. It says so instead, and the name leads with the visible glyphs so
 *  speech input can reach it (SC 2.5.3); the state comes from aria-pressed
 *  alone, rather than being announced twice. */
function syncLargeText() {
  const inert = state.compact;
  controls.text.disabled = inert;
  controls.text.setAttribute("aria-pressed", state.largeText ? "true" : "false");
  controls.text.setAttribute(
    "aria-label",
    inert
      ? "AA, larger text — already at the largest size this embed can show"
      : "AA, larger text",
  );
  controls.text.setAttribute(
    "title",
    inert
      ? "This embed is already showing the largest type this viewer has."
      : "Larger text — sets the broadcast in a bigger type ramp and drops the"
        + " finer annotations to make room",
  );
}

/* Larger text.
 *
 * WCAG 1.4.4 asks that text scale to 200% without loss. Full-page zoom does
 * scale this broadcast — the stage is letterboxed into the viewport, so zooming
 * the host page magnifies the whole thing, text included, with nothing lost. But
 * TEXT-ONLY resizing (a larger default font size) cannot reach type expressed in
 * SVG user units, and the embed's aspect ratio is fixed by the host, so there is
 * no reflow to fall back on. This switch is the in-product mechanism instead: it
 * forces the compact ramp at any size, which is a ~1.5x type increase, and it is
 * remembered for the session. The trade is stated on the button's own title. */
const LARGE_TEXT = "sugarscape.broadcast.largeText";

function setLargeText(on) {
  state.largeText = on;
  syncLargeText();
  try {
    if (on) sessionStorage.setItem(LARGE_TEXT, "1");
    else sessionStorage.removeItem(LARGE_TEXT);
  } catch (error) {
    // A sandboxed iframe can deny storage entirely; the toggle still works, it
    // just does not persist. Never let that throw and take the overlay with it.
  }
  standingsSignature = "";
  beatsSignature = "";
}


// ---------------------------------------------------------------------------
// Frame ingestion + derived model
// ---------------------------------------------------------------------------

const FRAME_FORMAT = "sugarscape.frame.v1";
let rejectedFormat = false;
let rejectedShape = false;

/** The server stamps a format on every frame. Checking only that `cells` is an
 *  array let a future shape through to throw on every tick behind a fully
 *  populated HUD - confidently wrong, which is worse than a black box. */
function isRenderableFrame(frame) {
  if (!frame || typeof frame !== "object") return false;
  if (typeof frame.format === "string" && frame.format !== FRAME_FORMAT) {
    if (!rejectedFormat) {
      rejectedFormat = true;
      fail(`This episode is recorded as ${frame.format}, which this viewer cannot read.`);
    }
    return false;
  }
  const shaped = Array.isArray(frame.cells) && Array.isArray(frame.agents)
    && Array.isArray(frame.slots) && Array.isArray(frame.cells[0])
    && Number.isFinite(frame.width) && Number.isFinite(frame.height)
    && Number.isFinite(frame.timestep);
  // Say WHICH way it was unusable. Letting these fall through to the silence
  // timer told an operator debugging a slot-config bug that nothing was being
  // sent, when five frames a second were arriving and being discarded.
  if (!shaped) {
    if (!rejectedShape) {
      rejectedShape = true;
      fail("This episode is sending frames this viewer cannot read.");
    }
    return false;
  }
  if (frame.slots.length === 0) {
    if (!rejectedShape) {
      rejectedShape = true;
      fail("This episode declares no policy populations, so there is no standing to show.");
    }
    return false;
  }
  return true;
}

/** A seat's colours. The manifest permits up to 16 populations while the
 *  palette lists four, so this cycles rather than returning undefined: indexing
 *  SEATS raw threw on the fifth population and blanked the whole overlay, and
 *  silently dropped those populations' wealth from every total. */
function seatOf(index) {
  return SEATS[((index % SEATS.length) + SEATS.length) % SEATS.length];
}

function slotOf(agent) {
  return agent.slot >= 0 ? agent.slot : -1;
}

/** Per-population standing. The score axis is total living wealth, matching
 *  `buildResults` in coworld.nim (which truncates the float sum to an integer);
 *  population count is the visible race but NOT the score. */
function standings(frame) {
  const rows = frame.slots.map((slot, index) => ({
    index,
    name: slot.name || `Population ${index + 1}`,
    wealth: 0,
    sugar: 0,
    spice: 0,
    population: 0,
  }));
  for (const agent of frame.agents) {
    const row = rows[slotOf(agent)];
    if (!row) continue;
    // Kept apart as well as summed. The score is the sum and only the sum, but
    // the lead plot stacks the two, and WHICH resource a lead is made of is a
    // different fact from how big it is: a population can be ahead overall while
    // behind on one of them. On the shipped recording that happens on 9.5% of
    // timesteps, and for the first 25 it is nearly the whole story.
    row.sugar += agent.sugar;
    row.spice += agent.spice;
    row.wealth += agent.sugar + agent.spice;
    row.population += 1;
  }
  for (const row of rows) row.score = Math.trunc(row.wealth);
  return rows;
}

/** True when the head of the episode was never delivered. The game server keeps
 *  a bounded backlog for live spectators, so joining a long episode late yields
 *  a stream that opens partway through — every total derived from "since the
 *  start" is then a window, and the broadcast has to say which. */
function joinedLate() {
  return !state.sawStart && frames.length > 0 && frames[0].timestep > 0;
}

function ranked(frame) {
  return standings(frame)
    .slice()
    .sort((first, second) => second.score - first.score || first.index - second.index);
}

/** The engine ships a per-frame count for each death cause. Saying "starved"
 *  for every disappearance is right for the shipping variant and wrong the
 *  moment aging, combat or disease is enabled - so read the cause rather than
 *  assume it. */
function deathCause(frame) {
  const stats = frame.stats ?? {};
  const causes = [
    ["starved", Number(stats.agentStarvationDeaths ?? 0)],
    ["died of age", Number(stats.agentAgingDeaths ?? 0)],
    ["killed in combat", Number(stats.agentCombatDeaths ?? 0)],
    ["lost to disease", Number(stats.agentDiseaseDeaths ?? 0)],
  ].sort((first, second) => second[1] - first[1]);
  return causes[0][1] > 0 ? causes[0][0] : "lost";
}

/** Derive this frame's beats by diffing against the previous one — a replay has
 *  no event stream, so deaths and lead changes are read out of the state. */
function deriveEvents(index) {
  if (index === 0) return;
  const previous = frames[index - 1];
  const frame = frames[index];
  const living = new Set(frame.agents.map((agent) => agent.id));
  const lost = previous.agents.filter((agent) => !living.has(agent.id));

  if (lost.length > 0) {
    const bySlot = new Map();
    for (const agent of lost) bySlot.set(slotOf(agent), (bySlot.get(slotOf(agent)) ?? 0) + 1);
    events.push({
      index,
      timestep: frame.timestep,
      kind: "death",
      count: lost.length,
      cause: deathCause(frame),
      bySlot: [...bySlot.entries()],
      agents: lost,
    });
  }

  /* A lead change is measured against the last frame that HAD a leader.
   *
   * Comparing adjacent frames and suppressing whenever either was tied dropped
   * the change entirely when the lead passed THROUGH a tie: A ahead, level, B
   * ahead emitted nothing, because ranked()'s slot-index tiebreak keeps A first
   * through the tie and the frame where B pulls ahead is compared against a tied
   * one and suppressed. The chart's count, the transport's gold marks and the
   * end card's "won from behind" arc all under-reported. Scanning back to the
   * last unambiguous leader costs a short walk over wealthSeries, which is
   * already computed, and gets the transit right. */
  const after = ranked(frame);
  const leader = leaderOf(wealthSeries[index]?.scores);
  if (leader < 0) return;
  let previousLeader = -1;
  for (let step = index - 1; step >= 0; step -= 1) {
    const candidate = leaderOf(wealthSeries[step]?.scores);
    if (candidate >= 0) {
      previousLeader = candidate;
      break;
    }
  }
  if (previousLeader >= 0 && previousLeader !== leader) {
    events.push({
      index,
      timestep: frame.timestep,
      kind: "lead",
      slot: leader,
      name: frame.slots[leader]?.name ?? `Population ${leader + 1}`,
      margin: after[0].score - (after[1]?.score ?? 0),
    });
  }
}

/** Which slot leads on these scores, or -1 when nothing does. A tie has no
 *  leader: ranked() breaks ties by slot index, and treating that as a result
 *  invented two lead changes around a leader who never lost it. */
function leaderOf(scores) {
  if (!Array.isArray(scores) || scores.length === 0) return -1;
  let best = 0;
  for (let slot = 1; slot < scores.length; slot += 1) {
    if (scores[slot] > scores[best]) best = slot;
  }
  const shared = scores.some((score, slot) => slot !== best && score === scores[best]);
  return shared ? -1 : best;
}

function recordFrame(frame) {
  if (state.streamId !== null && frame.streamId !== undefined
      && frame.streamId !== state.streamId) {
    resetStream();
  }
  if (frame.streamId !== undefined) state.streamId = frame.streamId;

  // A repeated timestep must update everything derived from it, not just the
  // frame: replacing in place and returning left the race chart and the event
  // feed describing the frame that was overwritten.
  const existing = frameIndexByTimestep.get(frame.timestep);
  if (existing !== undefined) {
    frames[existing] = frame;
    const rows = standings(frame);
    for (const row of rows) state.maxWealth = Math.max(state.maxWealth, row.score);
    wealthSeries[existing] = {
      timestep: frame.timestep,
      scores: rows.map((row) => row.score),
      sugar: rows.map((row) => row.sugar),
      spice: rows.map((row) => row.spice),
      population: rows.map((row) => row.population),
    };
    for (let index = events.length - 1; index >= 0; index -= 1) {
      if (events[index].index === existing) events.splice(index, 1);
    }
    deriveEvents(existing);
    // The world's scale is derived from the frames too, so a replacement has to
    // refresh it: replacing a frame that carried spice used to leave the score
    // still labelled "sugar".
    for (const cell of frame.cells) {
      if (cell[0] > state.maxSugar) state.maxSugar = cell[0];
      if (cell[1] > state.maxSpice) state.maxSpice = cell[1];
    }
    state.maxWealth = Math.max(1, ...wealthSeries.flatMap((point) => point.scores));
    standingsSignature = "";
    terrainShown = null;
    return;
  }

  frameIndexByTimestep.set(frame.timestep, frames.length);
  frames.push(frame);
  const index = frames.length - 1;

  if (frame.timestep === 0) state.sawStart = true;
  /* The world's SCALE comes from the server, not from the window in hand.
   *
   * Both of these used to be inferred - a running maximum over whatever cells
   * and agents had arrived - under a comment claiming that solved the
   * partly-eaten-world problem. It did not; it normalised against a partly-eaten
   * world with extra steps, and the population line was strictly worse: it took
   * the largest headcount ever SEEN, which is the exact "32 of 36 survived"
   * fiction the comment beside it warned about, and which any variant with
   * reproduction turns from latent into wrong. The server stamps
   * environmentMaxSugar, environmentMaxSpice and startingAgents on every frame
   * now, so read them; the inference is only a fallback for an older server, and
   * it no longer claims to have seen the start. */
  const declaredSugar = Number(frame.environmentMaxSugar ?? 0);
  const declaredSpice = Number(frame.environmentMaxSpice ?? 0);
  if (declaredSugar > 0) state.maxSugar = declaredSugar;
  if (declaredSpice > 0) state.maxSpice = Math.max(state.maxSpice, declaredSpice);
  const declaredAgents = Number(frame.startingAgents ?? 0);
  if (declaredAgents > 0) {
    state.startingPopulation = declaredAgents;
  } else if (frame.timestep === 0 || state.startingPopulation === 0) {
    // No declaration: frame zero is authoritative, and anything else is a guess
    // that must not be presented as a denominator - see sawStart.
    state.startingPopulation = frame.agents.length;
  }
  if (declaredSugar <= 0 || declaredSpice <= 0) {
    for (const cell of frame.cells) {
      if (declaredSugar <= 0 && cell[0] > state.maxSugar) state.maxSugar = cell[0];
      if (declaredSpice <= 0 && cell[1] > state.maxSpice) state.maxSpice = cell[1];
    }
  }
  // maxTimestep is stamped on every frame by the game server so the clock counts
  // to the SCHEDULED end of the match, not to whatever tick this recording
  // happens to stop at. An early extinction then freezes short of the buzzer.
  if (typeof frame.maxTimestep === "number") {
    state.maxTimestep = Math.max(state.maxTimestep, frame.maxTimestep);
  }
  state.maxTimestep = Math.max(state.maxTimestep, frame.timestep);

  const rows = standings(frame);
  for (const row of rows) state.maxWealth = Math.max(state.maxWealth, row.score);
  wealthSeries.push({
    timestep: frame.timestep,
    scores: rows.map((row) => row.score),
    sugar: rows.map((row) => row.sugar),
    spice: rows.map((row) => row.spice),
    population: rows.map((row) => row.population),
  });

  deriveEvents(index);
  syncScrub();
  if (state.live && state.playing) state.cursor = frames.length - 1;
}

function resetStream() {
  frames.length = 0;
  frameIndexByTimestep.clear();
  events.length = 0;
  wealthSeries.length = 0;
  motes.length = 0;
  state.cursor = 0;
  state.maxWealth = 1;
  state.maxSugar = 1;
  state.maxSpice = 0;
  state.maxTimestep = 0;
  state.startingPopulation = 0;
  state.sawStart = false;
  state.holdUntil = 0;
  terrainShown = null;
  state.finished = false;
  state.truncated = false;
  rejectedFormat = false;
  rejectedShape = false;
  notice.textContent = "";
  state.lastDrawnIndex = -1;
  spokenKey = "";
  spokenVerdict = false;
  markedLeads = -1;
  standingsSignature = "";
  beatsSignature = "";
  controls.scrub.min = "0";
  controls.scrub.max = "0";
  controls.scrub.value = "0";
}

// ---------------------------------------------------------------------------
// Terrain — composited once per timestep into an offscreen canvas, because it
// only changes when the frame does, while agents move every animation tick.
// ---------------------------------------------------------------------------

/* The board is a faithful rebuild of the DTL Sugarscape plate.
 *
 * The original renderer is vendored in this repo at reference/dtl-python/gui.py
 * and it is the oracle for the LOOK, exactly as the Python model is the oracle
 * for behaviour. It draws a white canvas, one rectangle per cell outlined in
 * #c0c0c0, filled by interpolating white -> #F2FA00 with sugar and -> #9B4722
 * with spice, and plain filled circles for agents coloured by decision model.
 *
 * An earlier pass here invented a warm painterly massif with generated terrain
 * textures, a relief pass and contours. It buried the per-cell resource under
 * texture, read as fog, and looked nothing like the model anyone recognises.
 * The lattice IS the picture; it does not want scenery. */

/* The two resources are matched for BRIGHTNESS, not just separated by hue.
 *
 * gui.py's #F2FA00 sugar and #9B4722 spice measure L=0.872 and L=0.115 — a 4.7:1
 * luminance gap between the two things the viewer is being asked to compare. At
 * equal coverage the yellow simply looked like more, so the eye read a sugar
 * majority on a board that did not have one. Sugar is a warm white and spice a
 * lit amber now: L=0.800 against L=0.478, a 1.5:1 gap, close enough that equal
 * masses read as equal masses. Hue says WHICH resource; density says how much.
 */
const SUGAR_HEX = "#f4ecdb";          // warm white; NEVER pure
const SPICE_HEX = "#f0a63c";          // the amber of the spice itself
const PLATE_HEX = "#1d1811";          // the field the grains lie on; NEVER pure black
const GRID_HEX = "#332a1e";           // one step up from the plate

let terrainShown = null;
/* ONE plate, and only the sand that CHANGED HANDS dissolves on it.
 *
 * A harvest is instantaneous in the model and used to be instantaneous on the
 * board — four units of sugar were simply gone on the tick a settler landed, and
 * one unit came back, whole, on each of the four ticks after it. Across the ~222
 * cells that change every timestep on the shipped 32x32 board that reads as a
 * flicker rather than as eating.
 *
 * The first fix for that was a CROSSFADE: keep the outgoing plate and dissolve
 * the incoming one over it. It does not work, and why is worth keeping. A
 * crossfade is a property of the whole image, so for as long as it ran, all 1,024
 * cells were drawn twice at partial alpha — including the 800 that had not
 * changed at all. Most of every dwell the entire plate was a half-transparent
 * double exposure of itself: contrast spent everywhere to animate a fifth of the
 * board. It reads as the picture going soft, not as sand moving.
 *
 * What actually happened is far more specific, and that is what is drawn now. A
 * cell going 4 -> 3 keeps three units of grains EXACTLY where they were, at full
 * strength, and loses the fourth unit's. Only those animate; every other grain on
 * the plate is untouched and solid. And they do not fade as a block — a unit is
 * baked as GRAIN_SIPS separate slices which go one after another, so the sand
 * thins in waves and the last of it lingers. That is a dissolve. The other thing
 * was a video transition. */
const terrain = document.createElement("canvas");
const terrainContext = terrain.getContext("2d");
let terrainFrom = null;               // the frame being dissolved FROM; null when settled
let terrainSettledAt = 0;             // when the dissolve began; 0 = nothing in flight
let terrainPainted = -1;              // the drift clock the plate currently stands at

/* How long the sand takes to settle after a timestep lands.
 *
 * Scaled by animFactor with everything else, and shorter than the gap between two
 * harvests (a dwell, 770ms at 1x) so a dissolve always finishes before the next
 * one starts. Longer than the 380ms the crossfade used, because this one costs
 * the picture nothing while it runs — the only grains in motion are the ones that
 * genuinely changed hands, so there is no reason to hurry it. */
const SETTLE_MS = 620;

/** How far through the dissolve the plate stands, 0 to 1. */
function terrainBlend(now) {
  if (!terrainSettledAt) return 1;
  const age = (now - terrainSettledAt) / (SETTLE_MS * animFactor(state.speed));
  if (age >= 1) return 1;
  return age * age * (3 - 2 * age);   // smoothstep; a linear dissolve pops at both ends
}

/** Show `frame`. `fade` dissolves from the frame being left; a scrub, a step, a
 *  pause, a reset or reduced motion cuts straight to the state asked for. */
function showTerrain(frame, fade, now) {
  terrainFrom = fade && terrainShown ? terrainShown : null;
  terrainShown = frame;
  terrainSettledAt = terrainFrom ? now : 0;
  paintTerrain(now);
}

/** Repaint the plate where it stands. The sand drifts continuously, so this runs
 *  every tick; it is also what carries a dissolve forward. */
function paintTerrain(now) {
  if (!terrainShown) return;
  const clock = driftAt(now);
  const dissolved = terrainBlend(now);
  buildTerrain(terrainShown, terrainFrom, clock, dissolved);
  terrainPainted = clock;
  if (dissolved >= 1) {
    terrainFrom = null;
    terrainSettledAt = 0;
  }
}

/* A SAND CLOUD, not a grid of countable grains.
 *
 * Resource is drawn as a dense mass of fine particles whose local density is the
 * local amount — the way spice looks blown across a dune rather than the way
 * counters look stacked in a square. Two earlier attempts are worth recording
 * because neither is obviously wrong until you look at it:
 *
 *   - One grain per unit, scattered anywhere in the cell, small enough not to
 *     collide. At that size the eye cannot integrate density from isolated dots,
 *     so the two sugar massifs and the two spice massifs dissolved into an even
 *     speckle. The picture lost its terrain entirely.
 *   - One grain per unit, PACKED on a per-cell sub-grid. Legible, and countable,
 *     but it read as a halftone screen: a regular pitch inside a regular pitch,
 *     which is a printing artefact rather than a landscape. Filling that
 *     sub-grid in raster order also struck continuous horizontal bands across
 *     the whole plate, because neighbouring cells hold similar amounts and so
 *     laid their first grains along the same row together.
 *
 * So: many particles per unit, scattered across the WHOLE cell with no inset, so
 * neighbouring cells merge into one continuous field and the drifts run across
 * cell boundaries the way real ones would. Local density carries the quantity,
 * which is a channel that survives greyscale, colour-vision deficiency, a
 * projector and a phone in sunlight — none of which the original's chroma ramp
 * did.
 *
 * Drawn once into a small sheet of TILES rather than particle-by-particle every
 * timestep: a full board is 1,024 cells holding up to eight units each, and at
 * the density that reads as a cloud that is a quarter of a million fills per
 * timestep. One tile per (resource, amount), several variants of each so the
 * repeat is not visible, built once per board size and then blitted — two blits
 * per cell, one for each resource standing in it.
 *
 * Per RESOURCE, not per (sugar, spice) PAIR. The two clouds are independent
 * streams (see grainCloud), so a pair sheet was storing every combination of two
 * things that never interact: (maxSugar+1)(maxSpice+1) tiles to say what
 * maxSugar+maxSpice tiles say. On the shipped 4/4 board that is 200 against 8,
 * and the saving is what pays for the loop frames below.
 */
/* 80 — and the mass a unit prints came DOWN this time, on purpose.
 *
 * Every earlier move here (26, then 36, then 220) held total coverage fixed while
 * the grains got finer, on the principle that coverage is the quantity. At a full
 * four units that was about three quarters of the cell inked, and three quarters
 * of a cell inked is not a field of sand — it is a solid: no gaps, no lanes, and
 * a hard boundary wherever it runs out. Nothing that full can have voids in it,
 * and the voids are the point.
 *
 * So a unit is worth roughly a fifth of the cell now instead of three quarters,
 * and the four levels are told apart by how CROWDED the sky is rather than by how
 * close it is to saturated. One unit reads as scattered, four as thick. Same
 * channel it always was, over a range where the eye can still see plate between
 * the grains.
 *
 * This constant, `particle` and GRAIN_HALO are one setting in three parts: move
 * any of them alone and a unit silently changes what it is worth. */
const PARTICLES_PER_UNIT = 80;
/* How far a grain's glow reaches, as a multiple of its core. Most of a soft
 * point's radius carries almost no ink, and that long tail is what makes specks
 * overlap into drifts rather than sit apart like punctuation. */
const GRAIN_HALO = 3.4;
/* Eight, not three, because the cloud is now NESTED (see grainCloud).
 *
 * Amount no longer varies the arrangement, so the only thing standing between
 * the eye and a visible repeat is the variant count. Three was already thin
 * inside a massif, where every cell holds the same amount and so drew from the
 * same three tiles. */
const TILE_VARIANTS = 8;

/* AND THE SAND IS NEVER STILL — CONTINUOUSLY, not in steps.
 *
 * A cloud that never moves is a halftone print OF a cloud. The thing this plate
 * is meant to look like — spice blown across a dune — is defined by the fact that
 * it drifts, and holding it still read as printing rather than as weather.
 *
 * The first two attempts both BAKED the motion: a strip of GRAIN_PHASES frames of
 * the same cloud, the cell showing one column of it, advanced on a clock. Both
 * failed, in instructive ways.
 *
 *   - Cross-fading between two adjacent phases. Two half-alpha copies of a grain
 *     do not average to one grain, they land at 1-f+f² of one, so every filled
 *     cell dimmed to three quarters at mid-step and recovered at the boundary.
 *     The whole plate breathed at the step rate.
 *   - No alpha, just more phases, so a step moved a grain a third of a pixel.
 *     Better, and still wrong, because the problem is not the SIZE of the step,
 *     it is that every cell on the plate takes its step at the same instant. A
 *     quarter of a million specks changing coverage together, fifteen times a
 *     second, is a strobe. It reads as twinkle, never as drift.
 *
 * And a baked loop cannot be slowed, which is the other thing that was asked for:
 * with a fixed number of frames, a longer period only means holding each frame
 * longer, so slower and smoother pull against each other. Memory settles it — a
 * 9-second loop at 60fps is 540 frames of the sheet, which is 150 MB.
 *
 * So nothing is baked. The tile holds ONE arrangement, and the tile itself is
 * drawn at a fractional offset that is a continuous function of the clock. Canvas
 * places a bitmap at sub-pixel coordinates for free — it costs the same as an
 * integer blit, measured — so the grains move smoothly at any speed, and the
 * speed is now a number rather than a memory budget.
 *
 * A tile is split into GRAIN_LAYERS of them, each drifting on its own path, or
 * the cell would slide about as one rigid raft. Every grain belongs to one layer
 * by index, so the layers are interleaved through the cloud rather than stacked,
 * and the paths are per CELL as well as per layer: cell A's first layer and cell
 * B's first layer are unrelated, so nothing marches across the plate together.
 * Three layers, each on a Lissajous of two incommensurable rates, and the pattern
 * never repeats.
 *
 * NOT scaled by animFactor, unlike every other motion on this stage: this is the
 * wind, not the clock. It keeps its own time while the replay is paused, sped up
 * or held on the end card, and it stops dead for a viewer who asked for reduced
 * motion. */
const GRAIN_LAYERS = 3;
/* How many slices a single unit's grains dissolve in. Four, so that a cell losing
 * one unit still thins in stages rather than fading as a block. */
const GRAIN_SIPS = 4;
/* One drift, end to end, in about this many seconds. Slow: a grain crosses a
 * twentieth of its cell over roughly nine, which is a float, not a stir. */
const GRAIN_DRIFT_RATE = 0.7;
const grainSheet = { key: "", solid: [[], []], sips: [[], []], size: 0, bleed: 0, box: 0, float: 0 };
const grainDrift = { cells: 0, phaseX: null, phaseY: null, rateX: null, rateY: null };

/* `?stir=off` holds the sand still, and it is not a debug flag — it is the only
 * way to see the two motions on this plate APART.
 *
 * There are two of them and they are easy to confuse for each other: the wind,
 * which moves every grain continuously and never stops, and the harvest, which is
 * the resource actually changing hands. With the wind running, a paused board is
 * never twice the same picture, so a viewer asked whether the resource still
 * flickers cannot answer — and neither can an audit.
 *
 * Off, the plate is motionless until a settler eats, which is what the flicker
 * work is for; on, it drifts. Default is on — this switches nothing off for a
 * viewer who does not ask. */
const stirWanted = new URLSearchParams(location.search).get("stir") !== "off";

/* The plate is repainted on this beat rather than on every one of the 16ms ticks.
 *
 * The drift is slow by design — a grain crosses two pixels in nine seconds — so at
 * 35 repaints a second it advances about eight thousandths of a pixel between
 * them. That is three orders of magnitude below anything the eye can resolve as a
 * step, and it halves what is the most expensive thing on the stage. */
const GRAIN_TICK_MS = 28;

/** The clock the sand drifts on — real milliseconds on the repaint beat, or a
 *  hard 0 when the wind is switched off, which is what freezes the plate. */
function driftAt(now) {
  if (reducedMotion || !stirWanted) return 0;
  return Math.round(now / GRAIN_TICK_MS) * GRAIN_TICK_MS;
}

/** The path each (cell, layer) drifts along. Built once per board size: two rates
 *  that never come back into step, so no layer ever retraces itself, and a phase
 *  per cell so no two cells drift alike. */
function buildGrainDrift(cells) {
  if (grainDrift.cells === cells) return;
  const slots = cells * GRAIN_LAYERS;
  grainDrift.cells = cells;
  grainDrift.phaseX = new Float32Array(slots);
  grainDrift.phaseY = new Float32Array(slots);
  grainDrift.rateX = new Float32Array(slots);
  grainDrift.rateY = new Float32Array(slots);
  for (let cell = 0; cell < cells; cell += 1) {
    for (let layer = 0; layer < GRAIN_LAYERS; layer += 1) {
      const slot = cell * GRAIN_LAYERS + layer;
      grainDrift.phaseX[slot] = grainOffset(cell, layer, 21) * Math.PI * 2;
      grainDrift.phaseY[slot] = grainOffset(cell, layer, 22) * Math.PI * 2;
      grainDrift.rateX[slot] = GRAIN_DRIFT_RATE * (0.62 + grainOffset(cell, layer, 23) * 0.76);
      grainDrift.rateY[slot] = GRAIN_DRIFT_RATE * (0.62 + grainOffset(cell, layer, 24) * 0.76);
    }
  }
}

/** `value` brought into [0, span) — the cell wraps, so a grain that orbits off
 *  one edge comes back on the other rather than being clipped away. */
function wrapInto(value, span) {
  return ((value % span) + span) % span;
}

/** A deterministic value in [0,1) from three integers. Positions must be stable
 *  across timesteps or the whole plate boils when one settler eats one unit. */
function grainOffset(a, b, c) {
  let hash = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791);
  hash = Math.imul(hash ^ (hash >>> 15), 2246822507);
  hash = Math.imul(hash ^ (hash >>> 13), 3266489909);
  return ((hash ^ (hash >>> 16)) >>> 0) / 4294967296;
}

/* The cloud for N units is the cloud for N-1 with one more handful ON TOP.
 *
 * This is the whole fix for the flicker the board used to have. The grain
 * positions used to be seeded from the cell's CONTENTS — `(sugar * 31 + spice)`
 * — so a cell going 4 -> 3 sugar did not lose a quarter of its grains, it threw
 * all of them away and scattered a completely different cloud, and it re-threw
 * its spice at the same time because the two shared one running seed. With
 * regrow rate 1 against a max of 4, a quarter of the board changes amount on
 * every timestep, so a quarter of the plate re-scattered every beat. Stable
 * positions per cell were not enough: the positions have to be stable per
 * AMOUNT too.
 *
 * So a cloud is keyed by its stream — the variant, and which of the two
 * resources — and never by how much is in the cell, and the tile for N units
 * draws the first N x PARTICLES_PER_UNIT grains of it. Losing a unit now
 * removes that unit's grains and moves nothing else; regrowing puts them back
 * where they were. Sugar and spice get separate streams, so eating one does not
 * disturb the other. */
/* Grains CLUMP, and the voids between the clumps are as much of the picture as
 * the clumps are.
 *
 * Scattered evenly — one hash for x, one for y — a cloud has the same density
 * everywhere, and a field with the same density everywhere has no shape. Past a
 * few units it stops looking like a field at all and starts looking like a solid
 * with an edge where it runs out, which is exactly what it looked like.
 *
 * So grains come in handfuls. A handful gets an origin and its own reach, and its
 * grains are placed by SUMMING two offsets rather than taking one, which crowds
 * them toward the middle and thins them at the rim instead of filling a box
 * evenly. Handfuls overlap, miss each other, and leave lanes of bare plate
 * between them — the gaps do the work.
 *
 * A handful WRAPS at the cell edge rather than being allowed to sit past it. The
 * obvious way round — let origins spill a little outside — was tried and printed
 * a dark rule along every boundary on the board, because a handful can reach
 * further than the spill allowed it to start, so the edges of the cell were the
 * one place no handful could be centred and the density fell away there. Wrapping
 * makes every point in the cell equally likely by construction, which is the only
 * version of this with no edge case at the edge. Grains still cross the boundary:
 * a point's glow reaches into the tile's margin and lands over the neighbour, and
 * the neighbour's does the same back, so the two fields overlap and the boundary
 * stops existing.
 *
 * The handful is keyed by index / GRAIN_PER_CLUMP, so it is a property of the
 * grain's place in the stream and nothing else. The nesting invariant holds: grain
 * i is in the same handful at the same spot however much the cell holds. */
const GRAIN_PER_CLUMP = 7;
function grainCloud(stream, count) {
  const cloud = [];
  for (let index = 0; index < count; index += 1) {
    const clump = Math.floor(index / GRAIN_PER_CLUMP);
    const originX = grainOffset(stream, clump, 30);
    const originY = grainOffset(stream, clump, 31);
    const reachX = 0.07 + grainOffset(stream, clump, 32) * 0.20;
    const reachY = 0.07 + grainOffset(stream, clump, 33) * 0.20;
    cloud.push([
      wrapInto(originX + (grainOffset(stream, index, 0) + grainOffset(stream, index, 8) - 1) * reachX, 1),
      wrapInto(originY + (grainOffset(stream, index, 1) + grainOffset(stream, index, 9) - 1) * reachY, 1),
      // Grains vary in size. A single particle size reads as television static;
      // sand does not have one grade, and the variation is what makes the mass
      // look blown rather than generated.
      0.55 + grainOffset(stream, index, 2) * 1.30,
      /* And in BRIGHTNESS, squared, so most are faint and a few are not.
       *
       * A field of equally bright specks is a texture; a field where brightness
       * runs over a wide range reads as depth, which is the whole difference
       * between static and a sky. Squaring the hash is what puts most of the
       * population at the dim end where it belongs. */
      0.16 + grainOffset(stream, index, 10) ** 2 * 0.84,
    ]);
  }
  return cloud;
}

/** The stream a resource's cloud is drawn from in a given variant. */
function grainStream(variant, resource) {
  return variant * 2 + resource;
}

/** How much of each resource a cell can hold, as [sugar, spice]. */
function grainCeiling() {
  return [Math.max(0, Math.round(state.maxSugar)), Math.max(0, Math.round(state.maxSpice))];
}

/** A theme hex as rgba at a given alpha, so the gradients below are derived from
 *  the palette block rather than restating it. */
function grainAlpha(hex, alpha) {
  const value = parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

/* A grain is a SOFT POINT, not a square.
 *
 * fillRect gives every speck four hard edges and one flat value, and a plate of
 * those reads as a printed screen however small they are — at any density above a
 * scatter it fuses into a solid with a cut edge where it stops. A soft point has
 * no edge to find: a bright core falling away to nothing, so grains overlap into
 * drifts rather than tiling into a surface, and the field ends by thinning out
 * instead of by stopping.
 *
 * Baked once per colour and blitted, because a radial gradient per grain across
 * ~20,000 of them at build time is not affordable and does not need to be — one
 * sprite scaled and faded is the same picture. */
function buildGrainSprite(colour) {
  const size = 64;
  const sprite = document.createElement("canvas");
  sprite.width = size;
  sprite.height = size;
  const spriteContext = sprite.getContext("2d");
  const middle = size / 2;
  const glow = spriteContext.createRadialGradient(middle, middle, 0, middle, middle, middle);
  // A small solid core, then a long tail. The tail is most of the radius and
  // almost none of the ink, which is what makes the point read as lit rather than
  // as drawn.
  glow.addColorStop(0, grainAlpha(colour, 1));
  glow.addColorStop(0.18, grainAlpha(colour, 0.82));
  glow.addColorStop(0.42, grainAlpha(colour, 0.28));
  glow.addColorStop(0.72, grainAlpha(colour, 0.06));
  glow.addColorStop(1, grainAlpha(colour, 0));
  spriteContext.fillStyle = glow;
  spriteContext.fillRect(0, 0, size, size);
  return sprite;
}

/** Which layer and which slice of its unit a grain belongs to. Both fall out of
 *  its index, so every grain lands in exactly one of each and the layers are
 *  interleaved THROUGH the cloud rather than stacked in bands of it. */
function grainLayer(index) {
  return index % GRAIN_LAYERS;
}
function grainSip(index) {
  return Math.floor(index / GRAIN_LAYERS) % GRAIN_SIPS;
}

/** The settled tile: everything a cell holding `units` of `resource` shows, in
 *  one layer. One blit, and it is what the plate is made of almost all the time. */
function grainSolid(resource, units, variant, layer) {
  return grainSheet.solid[resource][((units - 1) * TILE_VARIANTS + variant) * GRAIN_LAYERS + layer];
}

/** One slice of ONE unit — the granularity a harvest dissolves at. Drawn only
 *  while a cell is changing, which is a fifth of them for a fifth of a dwell. */
function grainSipTile(resource, unit, sip, variant, layer) {
  const slice = ((unit - 1) * GRAIN_SIPS + sip) * TILE_VARIANTS + variant;
  return grainSheet.sips[resource][slice * GRAIN_LAYERS + layer];
}

function buildGrainSheet(cellPx) {
  const ceiling = grainCeiling();
  const key = `${cellPx}:${ceiling[0]}:${ceiling[1]}`;
  if (grainSheet.key === key) return;
  grainSheet.key = key;
  grainSheet.solid = [[], []];
  grainSheet.sips = [[], []];
  const size = Math.max(2, Math.ceil(cellPx));
  grainSheet.size = size;
  /* SAND, not gravel: 0.026 of a cell, down from 0.075 and then 0.064.
   *
   * At a fortieth of the cell a grain lands under one device pixel once the
   * supersampled plate is scaled down, so it prints as a partial-coverage speck
   * rather than as a countable block with edges of its own. That is the whole
   * difference between a field of sand and a field of dots, and it is also what
   * stops the stir reading as static: a grain that is a fraction of a pixel
   * changes a fraction of a pixel's worth of ink when it moves.
   *
   * COVERAGE IS THE QUANTITY, and coverage goes with the SQUARE of the grade, so
   * the count has to pay for the fineness or a unit of sugar quietly becomes a
   * fifth of the ink it was: (0.064/0.026)^2 = 6.1, and 36 x 6.1 is the 220 in
   * PARTICLES_PER_UNIT. Move one of the two and you must move the other. */
  const particle = Math.max(0.5, size * 0.021);
  /* How far a grain travels from home, and it is the DRAWN tile that travels now
   * rather than anything baked. A twentieth of a cell, so a grain crosses two
   * pixels of the supersampled plate over the nine seconds of a drift — visible
   * as movement if you watch one, invisible as a change if you are reading the
   * board, which is the only setting that satisfies both. */
  const float = Math.max(0.8, size * 0.05);
  /* The cells BLEED INTO EACH OTHER rather than each holding its own sand.
   *
   * A grain that crossed the edge used to wrap round to the opposite side of the
   * same cell — the cell as a torus. Density stayed flat across the boundary,
   * which was the point, but nothing ever CROSSED one, so every cell was still a
   * closed box and the lattice could be read off the plate by anyone who looked.
   *
   * Now the tile carries a margin and the grain simply carries on into it, over
   * the neighbour, and the tiles mesh. The cost is the honest one: that spilled
   * grain belongs to the cell it came FROM, so when a settler eats that cell the
   * part lying over the neighbour goes with it. Which is correct — it was never
   * the neighbour's sand.
   *
   * The margin covers the reach of a grain's glow; the drift is added at DRAW
   * time, as a fractional offset on the blit, so it needs no margin of its own. */
  const bleed = Math.max(2, Math.min(Math.floor(size / 2), Math.round(size * 0.16)));
  const box = size + bleed * 2;
  grainSheet.bleed = bleed;
  grainSheet.box = box;
  grainSheet.float = float;

  /* NO CELL HAS AN EDGE. Every tile is FEATHERED, and the feathers sum to one.
   *
   * With each cell's sand stopping dead at its own boundary, an emptied cell
   * printed as a hard black square with four straight sides — the sharpest thing
   * on a plate that is meant to read as weather. Softening it by simply letting
   * tiles overhang does not work either: where two full cells meet you then have
   * both fields at full strength and the seam comes back inverted, as a bright
   * rule instead of a dark one.
   *
   * So the field is EXTENDED past the cell — the wrapped cloud repeats into the
   * margin — and the tile's alpha is a triangular ramp: zero at the outer edge of
   * the margin, full one margin-width in, flat across the middle. Tiles are laid
   * one cell apart and overlap by exactly two margins, so on any run of cells the
   * falling ramp of one lands on the rising ramp of the next and the two sum to
   * exactly one. Uniform sand stays uniform, with no seam of either sign.
   *
   * What it buys is the empty cell: with no neighbour tile to complete the sum,
   * the surrounding sand simply ramps down into the hole across a sixth of a cell
   * on every side. The void gets a soft shore instead of four straight sides. */
  const feather = document.createElement("canvas");
  feather.width = box;
  feather.height = box;
  const featherContext = feather.getContext("2d");
  const ramp = (context2d, horizontal) => {
    const shade = horizontal
      ? context2d.createLinearGradient(0, 0, box, 0)
      : context2d.createLinearGradient(0, 0, 0, box);
    shade.addColorStop(0, C.maskOut);
    shade.addColorStop((bleed * 2) / box, C.maskIn);
    shade.addColorStop(size / box, C.maskIn);
    shade.addColorStop(1, C.maskOut);
    return shade;
  };
  featherContext.fillStyle = ramp(featherContext, true);
  featherContext.fillRect(0, 0, box, box);
  // Separable: the vertical ramp multiplies the horizontal one, so a corner gets
  // the product of the two and the partition still sums to one along both axes.
  featherContext.globalCompositeOperation = "destination-in";
  featherContext.fillStyle = ramp(featherContext, false);
  featherContext.fillRect(0, 0, box, box);

  /** One tile: the grains of `cloud` in `layer`, optionally only those in `sip`. */
  const bake = (sprite, cloud, from, layer, sip) => {
    const tile = document.createElement("canvas");
    tile.width = box;
    tile.height = box;
    const tileContext = tile.getContext("2d");
    // The cell's own origin sits one margin in, so what continues past the cell is
    // drawn into the margin rather than clipped off.
    tileContext.translate(bleed, bleed);
    let lit = -1;
    for (let index = from; index < cloud.length; index += 1) {
      if (grainLayer(index) !== layer) continue;
      if (sip >= 0 && grainSip(index) !== sip) continue;
      const [x, y, scale, glow] = cloud[index];
      const reach = particle * scale * GRAIN_HALO;
      if (glow !== lit) {
        lit = glow;
        tileContext.globalAlpha = glow;
      }
      const atX = x * size;
      const atY = y * size;
      // The cloud repeats into the margin, so the field carries on past the cell
      // instead of stopping at it. Only grains near an edge have a copy to draw.
      const alsoX = atX < bleed + reach ? atX + size : (atX > size - bleed - reach ? atX - size : null);
      const alsoY = atY < bleed + reach ? atY + size : (atY > size - bleed - reach ? atY - size : null);
      const place = (px, py) => tileContext.drawImage(
        sprite, px - reach / 2, py - reach / 2, reach, reach);
      place(atX, atY);
      if (alsoX !== null) place(alsoX, atY);
      if (alsoY !== null) place(atX, alsoY);
      if (alsoX !== null && alsoY !== null) place(alsoX, alsoY);
    }
    tileContext.setTransform(1, 0, 0, 1, 0, 0);
    tileContext.globalAlpha = 1;
    tileContext.globalCompositeOperation = "destination-in";
    tileContext.drawImage(feather, 0, 0);
    return tile;
  };

  for (const [resource, colour] of [[0, SUGAR_HEX], [1, SPICE_HEX]]) {
    const sprite = buildGrainSprite(colour);
    const full = ceiling[resource] * PARTICLES_PER_UNIT;
    for (let variant = 0; variant < TILE_VARIANTS; variant += 1) {
      const cloud = grainCloud(grainStream(variant, resource), full);
      for (let units = 1; units <= ceiling[resource]; units += 1) {
        const held = cloud.slice(0, units * PARTICLES_PER_UNIT);
        for (let layer = 0; layer < GRAIN_LAYERS; layer += 1) {
          grainSheet.solid[resource][((units - 1) * TILE_VARIANTS + variant) * GRAIN_LAYERS + layer]
            = bake(sprite, held, 0, layer, -1);
          for (let sip = 0; sip < GRAIN_SIPS; sip += 1) {
            // Only THIS unit's grains: the slice a harvest takes, on its own, so
            // it can be dissolved without touching the ones underneath it.
            const slice = ((units - 1) * GRAIN_SIPS + sip) * TILE_VARIANTS + variant;
            grainSheet.sips[resource][slice * GRAIN_LAYERS + layer]
              = bake(sprite, held, (units - 1) * PARTICLES_PER_UNIT, layer, sip);
          }
        }
      }
    }
  }
}

/** How many whole units of `resource` a recorded cell holds. */
function grainUnits(cell, resource, ceiling) {
  return Math.min(ceiling[resource], Math.max(0, Math.round(cell[resource])));
}

/* How much of the slice standing at `place` in a queue of `queue` is showing.
 *
 * This one expression is the whole difference between a dissolve and a crossfade.
 * A crossfade puts EVERY element at partial alpha at once — the entire plate at
 * 50% halfway through. Here the queue is walked: the slices behind the head are
 * still at 1, the ones in front of it are at 0 and not drawn at all, and only the
 * slice at the head is anywhere in between. At most one thing on the plate is
 * ever semi-transparent, so the picture never goes soft. */
function grainShare(dissolved, queue, place, rising) {
  const reached = dissolved * queue - place;
  return Math.max(0, Math.min(1, rising ? reached : 1 - reached));
}

/* THE HEIGHT UNDER THE SAND.
 *
 * Grain density alone cannot carry how much a cell holds, and this was measured
 * on the real recording rather than argued: sampling the rendered plate cell by
 * cell against the frame it was drawn from, one unit of sugar to the next moved
 * the mean luminance by 4 to 9 values — 1.06:1 to 1.13:1, where a non-text
 * graphic needs 3:1 — while the scatter WITHIN a single level was 7 to 13. The
 * encoding was quieter than its own noise (gap/sigma 0.32 to 0.92), so a 1-cell
 * and a 4-cell were not distinguishable and the four massifs printed as an even
 * speckle. Grains saturate: past the first unit each new one lands on sand that
 * is already lit, so it buys coverage the eye has mostly been sold already.
 *
 * So the sand sits on a WASH that carries the height on its own — one source
 * pixel per cell, blended off the plate toward each resource's own hue in
 * proportion to what the cell holds, upscaled with smoothing so the field
 * interpolates between cell centres instead of terracing into squares. It is
 * gui.py's two-axis ramp restored as a floor: deterministic, seamless, and free
 * of the stochastic scatter that was drowning the signal. The sand keeps its
 * job — texture, and the harvest animation — and stops having to carry depth
 * by itself.
 *
 * Amplitude is set by what else has to survive on the plate. A settler is a
 * ~115-value seat colour inside a C.ink ring; holding a full cell of both
 * resources near 75 keeps the bodies clearly the brightest thing on the board
 * and leaves the ring its job. */
const WASH_GAIN = 0.16;
const washPlate = document.createElement("canvas");
const washContext = washPlate.getContext("2d");

function washRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

const WASH_BASE = washRgb(PLATE_HEX);
const WASH_SUGAR = washRgb(SUGAR_HEX);
const WASH_SPICE = washRgb(SPICE_HEX);

function paintHeightWash(frame, cell) {
  const ceiling = grainCeiling();
  if (ceiling[0] <= 0 && ceiling[1] <= 0) return;
  if (washPlate.width !== frame.width || washPlate.height !== frame.height) {
    washPlate.width = frame.width;
    washPlate.height = frame.height;
  }
  const field = washContext.createImageData(frame.width, frame.height);
  const pixels = field.data;
  for (let index = 0; index < frame.cells.length; index += 1) {
    const holds = frame.cells[index];
    // cellId = x * height + y, and the wash is a row-major bitmap.
    const x = Math.floor(index / frame.height);
    const y = index % frame.height;
    const sugar = ceiling[0] > 0 ? Math.min(1, Math.max(0, holds[0] / ceiling[0])) : 0;
    const spice = ceiling[1] > 0 ? Math.min(1, Math.max(0, holds[1] / ceiling[1])) : 0;
    const at = (y * frame.width + x) * 4;
    for (let channel = 0; channel < 3; channel += 1) {
      // Each resource pulls the plate toward its own hue independently, so a
      // cell holding both lands warm and bright and a cell holding one lands on
      // that one's colour. Additive at THIS amplitude stays on the plate: the
      // full-both corner measures ~75, well under the seat colours above it.
      const base = WASH_BASE[channel];
      pixels[at + channel] = Math.min(255, base
        + sugar * WASH_GAIN * (WASH_SUGAR[channel] - base)
        + spice * WASH_GAIN * (WASH_SPICE[channel] - base));
    }
    pixels[at + 3] = 255;
  }
  washContext.putImageData(field, 0, 0);
  terrainContext.imageSmoothingEnabled = true;
  terrainContext.imageSmoothingQuality = "high";
  // Source pixel centres land on cell centres under a plain scale, so the
  // bilinear ramp between two cells is centred on the boundary they share.
  terrainContext.drawImage(washPlate, 0, 0, cell * frame.width, cell * frame.height);
}

/* Paint the plate: every cell's settled sand at wherever its layers have drifted
 * to, and, for the cells that just changed hands, the slice going or arriving.
 *
 * `dissolved` runs 0 to 1 across one harvest. A departing unit's slices leave in
 * order, TOP FIRST, because the top of the pile is what a settler takes; an
 * arriving unit's land in the order they were laid. Only the slice at the head of
 * the queue is ever part-transparent — the ones behind it are still solid and the
 * ones ahead are simply not drawn — so at no point is the plate a double exposure
 * of itself, which is what the crossfade this replaced could never avoid. */
/* COUNTABLE DOTS, one per unit held. A tile carries up to four of each.
 *
 * This replaces the sand cloud, and the reason the cloud existed no longer
 * holds. The cloud drew many particles per unit and let local DENSITY carry the
 * amount; one-dot-per-unit had been tried before it and rejected, because on a
 * 50x50 board a cell is about fourteen pixels and four dots inside that is a
 * speckle the eye cannot integrate into a massif.
 *
 * v3's world is 20x20. The same board gives a cell roughly six times the area,
 * which is the measurement that changed — enough room to lay eight dots out on
 * fixed slots and still see plate between them. So the amount is now exactly
 * what it is in the model: a count you can point at, not a texture you estimate.
 * Density was always a proxy for counting; at this cell size we can just count.
 *
 * Sugar takes the square, spice takes the diamond. Two interleaved lattices that
 * never collide, so a tile holding four of each reads as four and four rather
 * than as eight of something. Slots fill in a fixed order, so one more unit is
 * one more dot in a place the eye already knows to look.
 */
const DOT_RADIUS = 0.055;   // of a cell
const DOT_HALO = 0.016;     // plate-coloured rim so touching dots stay separate
/* Each cell gets its OWN scattered layout, not a shared lattice.
 *
 * The first attempt kept one fixed constellation — sugar on a square, spice on a
 * diamond — and nudged each dot off it. That still printed a pattern, and the
 * arithmetic says why: the nudge was 0.038 of a cell against a slot spacing of
 * 0.40, about two pixels at the size these draw. Every cell repeated the same
 * motif in the same places, so the eye read the repeat straight through the
 * jitter, and dots stayed aligned in columns across neighbouring cells.
 *
 * So the positions themselves are drawn per cell now, by rejection sampling
 * against a minimum separation: genuinely irregular placement, with the gap that
 * keeps every dot a countable mark preserved as a CONSTRAINT rather than as a
 * consequence of sitting on a grid. Deterministic — hashed off the cell index,
 * never Math.random — because the plate repaints every tick and anything drawn
 * fresh each time would boil. Cached, because rejection sampling per repaint
 * would be wasted work for an answer that never changes.
 */
const DOT_MARGIN = 0.085;   // keep a whole dot inside its own cell
const DOT_MIN_GAP = 0.20;   // centre-to-centre, comfortably over the dot span
const DOT_TRIES = 48;
const dotLayouts = new Map();

/** Up to `sugarCap + spiceCap` separated points in one cell, sugar taking the
 *  first `sugarCap` of them. Stable for the life of the page. */
function cellDotLayout(index, sugarCap, spiceCap) {
  const key = `${index}:${sugarCap}:${spiceCap}`;
  const cached = dotLayouts.get(key);
  if (cached) return cached;
  const span = 1 - 2 * DOT_MARGIN;
  const points = [];
  let salt = 1;
  for (let n = 0; n < sugarCap + spiceCap; n += 1) {
    let best = null;
    let bestGap = -1;
    for (let attempt = 0; attempt < DOT_TRIES; attempt += 1) {
      salt += 1;
      const x = DOT_MARGIN + grainOffset(index, salt, 61) * span;
      const y = DOT_MARGIN + grainOffset(index, salt, 67) * span;
      let gap = Infinity;
      for (const point of points) {
        gap = Math.min(gap, Math.hypot(point[0] - x, point[1] - y));
      }
      if (gap >= DOT_MIN_GAP) { best = [x, y]; bestGap = gap; break; }
      // Nothing cleared the gap yet — keep the roomiest candidate so a crowded
      // cell degrades to "as far apart as we found" rather than to a collision.
      if (gap > bestGap) { best = [x, y]; bestGap = gap; }
    }
    points.push(best);
  }
  dotLayouts.set(key, points);
  return points;
}
// Terrain pixels on the supersampled canvas. A dot is a countable OBJECT, so it
// gets a floor: at the 640 embed width the fraction alone would put a grain of
// sand at each slot and the count would stop being readable as a count.
const DOT_MIN_PX = 1.6;

function paintResourceDots(frame, cell) {
  const radius = Math.max(cell * DOT_RADIUS, DOT_MIN_PX);
  const halo = Math.max(cell * DOT_HALO, 0.5);
  for (let index = 0; index < frame.cells.length; index += 1) {
    const holds = frame.cells[index];
    if (holds[0] <= 0 && holds[1] <= 0) continue;
    // cellId = x * height + y (column-major).
    const originX = Math.floor(index / frame.height) * cell;
    const originY = (index % frame.height) * cell;
    // The model's own caps, so a board configured for more than four still draws
    // every unit it holds rather than silently clipping at four.
    const sugarCap = frame.environmentMaxSugar || 4;
    const spiceCap = frame.environmentMaxSpice || 4;
    const layout = cellDotLayout(index, sugarCap, spiceCap);
    for (let resource = 0; resource < 2; resource += 1) {
      const cap = resource === 0 ? sugarCap : spiceCap;
      const units = Math.max(0, Math.min(cap, Math.round(holds[resource])));
      if (units <= 0) continue;
      terrainContext.fillStyle = resource === 0 ? SUGAR_HEX : SPICE_HEX;
      for (let unit = 0; unit < units; unit += 1) {
        const point = layout[resource === 0 ? unit : sugarCap + unit];
        if (!point) continue;
        const cx = originX + point[0] * cell;
        const cy = originY + point[1] * cell;
        if (halo > 0) {
          terrainContext.beginPath();
          terrainContext.arc(cx, cy, radius + halo, 0, Math.PI * 2);
          terrainContext.fillStyle = PLATE_HEX;
          terrainContext.fill();
          terrainContext.fillStyle = resource === 0 ? SUGAR_HEX : SPICE_HEX;
        }
        terrainContext.beginPath();
        terrainContext.arc(cx, cy, radius, 0, Math.PI * 2);
        terrainContext.fill();
      }
    }
  }
}

function buildTerrain(frame, from, clock, dissolved) {
  const size = Math.round(BOARD.w * RENDER_SCALE);
  if (terrain.width !== size) terrain.width = terrain.height = size;
  const cell = size / Math.max(frame.width, frame.height);
  terrainContext.setTransform(1, 0, 0, 1, 0, 0);
  terrainContext.clearRect(0, 0, terrain.width, terrain.height);
  terrainContext.fillStyle = PLATE_HEX;
  terrainContext.fillRect(0, 0, cell * frame.width, cell * frame.height);
  paintResourceDots(frame, cell);
  terrainContext.globalAlpha = 1;
}

/* THE SURROUND IS THE SAME DESERT.
 *
 * A flat fill behind the lattice said "chart, on a slab". But the plate is a
 * window cut into a sand world, and the stage around it is the rest of that
 * world: a low warm horizon pooling behind the board, the corners falling away
 * from it, and the far sand blowing across both — the same two resources, at the
 * same rough proportion the lattice holds them, a long way off and lit by
 * nothing. It costs one gradient, one gradient and one pattern fill.
 *
 * It also does a job the flat fill could not. PLATE_HEX #1d1811 against
 * C.ground #14100a is a difference of nine values; the plate had no edge of its
 * own and depended entirely on the lit rule drawn round it. The horizon lifts the
 * ground behind the board to about #241b0e, so the plate now reads as the DARKER
 * shape — figure against ground, the way a window is darker than the wall.
 *
 * Everything here is held at a whisper because every panel, every number and
 * every settler on this stage has to be read over it. Worst case is C.paper on
 * the brightest point of the horizon: 15.4:1 becomes 13.7:1, and the panels, which
 * are 86% opaque, move by under one value. The scrims behind the scorebug and the
 * end card are untouched and still carry their own contrast.
 *
 * NO SCENERY. An earlier pass on this build invented a painterly massif with
 * generated terrain and contour lines, and the owner rejected it on sight: it
 * buried the resource and read as fog. The rule that came out of that holds here
 * — this is MATERIAL, the same sand the board is made of, not landscape. Nothing
 * in the surround draws a shape.
 */
/* The haze is made of DRIFTS, not of evenly scattered specks.
 *
 * An even Poisson scatter of square grains was the first version of this and it
 * read as sensor noise — a dead-pixel starfield behind the broadcast. What makes
 * a haze look blown is that it is UNEVEN: sand piles into long low streaks with
 * clear air between them. So the tile is built as a few dozen drifts, each a
 * bunch of short streaks summed from two offsets so they crowd toward the middle
 * of the drift rather than filling its box; and each mark is longer than it is
 * tall, lying along the direction the whole field travels. */
const DUST_TILE = 360;              // stage units; the haze repeats on this square
const DUST_DRIFTS = 96;
const DUST_PER_DRIFT = 9;
const DUST_DRIFT_MS = 84000;        // one tile-length of travel, so ~4 units a second
const dustTile = document.createElement("canvas");
let dustPattern = null;
let groundHorizon = null;
let groundHollow = null;

function buildGround() {
  if (dustPattern) return;
  dustTile.width = DUST_TILE;
  dustTile.height = DUST_TILE;
  const dustContext = dustTile.getContext("2d");
  for (let drift = 0; drift < DUST_DRIFTS; drift += 1) {
    const originX = grainOffset(drift, 5, 0) * DUST_TILE;
    const originY = grainOffset(drift, 5, 1) * DUST_TILE;
    // Long and low, like everything the wind makes.
    const reachX = 16 + grainOffset(drift, 5, 2) * 48;
    const reachY = 3 + grainOffset(drift, 5, 3) * 9;
    // Roughly a third spice to two thirds sugar, which is about what the lattice
    // carries; the surround is downwind of the board, not a different world.
    dustContext.fillStyle = grainOffset(drift, 5, 4) < 0.34 ? C.dustWarm : C.dust;
    for (let index = 0; index < DUST_PER_DRIFT; index += 1) {
      const spanX = (grainOffset(drift, index, 6) + grainOffset(drift, index, 7) - 1) * reachX;
      const spanY = (grainOffset(drift, index, 8) + grainOffset(drift, index, 9) - 1) * reachY;
      const length = 1 + grainOffset(drift, index, 10) * 5;
      const height = 1 + grainOffset(drift, index, 11);
      // Wrapped for the same reason the cell grains are: the tile repeats, and a
      // drift cut off at its edge would print a hard vertical seam every 360.
      const x = wrapInto(originX + spanX, DUST_TILE);
      const y = wrapInto(originY + spanY, DUST_TILE);
      dustContext.fillRect(x, y, length, height);
      if (x + length > DUST_TILE) dustContext.fillRect(x - DUST_TILE, y, length, height);
      if (y + height > DUST_TILE) dustContext.fillRect(x, y - DUST_TILE, length, height);
    }
  }
  dustPattern = context.createPattern(dustTile, "repeat");

  // Centred on the board rather than on the stage: the light in this picture
  // comes from the thing the picture is about.
  const hx = BOARD.x + BOARD.w * 0.5;
  const hy = BOARD.y + BOARD.h * 0.44;
  groundHorizon = context.createRadialGradient(hx, hy, 0, hx, hy, W * 0.62);
  groundHorizon.addColorStop(0, C.horizon);
  groundHorizon.addColorStop(0.55, C.horizonFar);
  groundHorizon.addColorStop(1, C.horizonOut);

  groundHollow = context.createRadialGradient(W / 2, H / 2, W * 0.3, W / 2, H / 2, W * 0.78);
  groundHollow.addColorStop(0, C.hollowIn);
  groundHollow.addColorStop(1, C.hollow);
}

function drawGround(now) {
  buildGround();
  context.fillStyle = C.ground;
  context.fillRect(0, 0, W, H);
  context.fillStyle = groundHorizon;
  context.fillRect(0, 0, W, H);
  // The far sand, blowing. One pattern fill under a translation, so the whole
  // haze costs a single rect no matter how many grains are in the tile. Slow
  // enough — about four stage units a second — that it never competes with the
  // board for attention; it is only there so the stage is not dead.
  const travel = reducedMotion ? 0 : (now % DUST_DRIFT_MS) / DUST_DRIFT_MS * DUST_TILE;
  context.save();
  context.translate(-travel, travel * 0.34);
  context.fillStyle = dustPattern;
  context.fillRect(travel, -travel * 0.34, W, H);
  context.restore();
  // Drawn last so it takes the dust down with it into the corners.
  context.fillStyle = groundHollow;
  context.fillRect(0, 0, W, H);
}

function cellPosition(frame, cell) {
  return { x: Math.floor(cell / frame.height), y: cell % frame.height };
}

/** Interpolate every agent between two recorded timesteps. Sugarscape records
 *  one frame per timestep and agents move several cells at a time, so without
 *  this they teleport. A move longer than half the lattice is a wrap-around and
 *  snaps rather than sliding across the whole board. */
/** Does this replay record wealth in presentation buckets rather than units? */
function quantised(frame) {
  return Number(frame.wealthQuantum || 0) > 1;
}

function interpolate(previous, frame, t) {
  const before = new Map(previous ? previous.agents.map((agent) => [agent.id, agent]) : []);
  const cell = BOARD.w / frame.width;
  return frame.agents.map((agent) => {
    const target = cellPosition(frame, agent.cell);
    const source = before.get(agent.id);
    let x = target.x;
    let y = target.y;
    let wealth = agent.sugar + agent.spice;
    if (source) {
      const from = cellPosition(frame, source.cell);
      const wrapped = Math.abs(from.x - target.x) > frame.width / 2
        || Math.abs(from.y - target.y) > frame.height / 2;
      if (!wrapped) {
        x = from.x + (target.x - from.x) * t;
        y = from.y + (target.y - from.y) * t;
      }
      wealth = (source.sugar + source.spice) + (wealth - (source.sugar + source.spice)) * t;
    }
    return {
      agent,
      slot: slotOf(agent),
      px: BOARD.x + (x + 0.5) * cell,
      py: BOARD.y + (y + 0.5) * cell,
      wealth,
      // The engine kills when metabolism takes a settler to or below zero
      // (simulation.nim doTimestep), so the test is <=, not <. At < it missed
      // 12 of the 32 deaths in the reference recording while the board's key
      // promised "about to starve"; at < 2x metabolism it over-warned sevenfold.
      /* And only when the replay holds the units to answer it.
       *
       * The test needs a raw stock to set against a metabolism. A v3 replay does
       * not carry one: it records wealth in 50-unit presentation buckets, so
       * every agent under the first bucket reads as 0 and is then compared
       * against a metabolism of 1-4. Measured before this guard: 24.2% of all
       * agent-frames were marked starving and a quarter of the board was faded
       * for nothing. Quantised data cannot answer the question, so it does not
       * get to — the marker goes silent rather than wrong, and the key drops its
       * swatch to match. */
      starving: !quantised(frame)
        && (agent.sugar <= agent.sugarMetabolism
          || (agent.spiceMetabolism > 0 && agent.spice <= agent.spiceMetabolism)),
      tribe: agent.tribe,
      // A settler that changed culture between the frame it came from and this
      // one. The comparison has to be against the SAME agent's previous tag, so
      // it is made here where the pairing already exists; a newborn has no
      // previous tag and so is never a sway.
      swayed: Boolean(source) && source.tribe !== undefined
        && agent.tribe !== undefined && source.tribe !== agent.tribe,
      // The culture it LEFT. A ring around a settler that has already taken its
      // new colour says only "something happened here"; the reading a viewer
      // actually wants is which way it went, and that needs both colours on
      // screen at once.
      wasTribe: source ? source.tribe : undefined,
      // Walking, not floating: the legs only swap for a settler that changed
      // cell this timestep, and t < 1 means the walk is still in progress.
      moving: Boolean(source) && source.cell !== agent.cell && t < 1,
    };
  });
}

function drawBoard(frame, previous, t, now) {
  // One cell size for both axes is only right for a SQUARE world.
  // initEnvironment takes independent width and height, and gui.py computes its
  // site height and width separately, so a 64x32 world filled the top half of
  // the plate and a 32x64 one ran off the bottom.
  const cell = Math.min(BOARD.w / frame.width, BOARD.h / frame.height);

  context.setTransform(RENDER_SCALE, 0, 0, RENDER_SCALE, 0, 0);
  context.clearRect(0, 0, W, H);
  drawGround(now);

  // A bright plate seated on the dark broadcast surround by a thin warm mat.
  // A dark plate on a dark surround has no luminance edge of its own, so the
  // mat is drawn as a lit warm rule. The shadow still seats it.
  context.save();
  context.shadowColor = C.mat;
  context.shadowBlur = 22;
  context.shadowOffsetY = 5;
  context.fillStyle = C.edge;
  context.fillRect(BOARD.x - 2, BOARD.y - 2, BOARD.w + 4, BOARD.h + 4);
  context.restore();
  // One plate. The dissolve happens INSIDE it, on the grains that changed hands,
  // so there is never a second copy of the board to blend against.
  context.drawImage(terrain, BOARD.x, BOARD.y, BOARD.w, BOARD.h);

  // A settler starving leaves an expanding ring where it stood.
  for (let index = motes.length - 1; index >= 0; index -= 1) {
    const mote = motes[index];
    const age = (now - mote.born) / (MOTE_MS * animFactor(state.speed));
    if (age >= 1) { motes.splice(index, 1); continue; }
    context.globalAlpha = (1 - age) * 0.85;
    context.strokeStyle = C.loss;
    context.lineWidth = Math.max(1.4, cell * 0.22 * (1 - age));
    context.beginPath();
    context.arc(mote.px, mote.py, cell * (0.32 + age * 1.05), 0, Math.PI * 2);
    context.stroke();
  }
  context.globalAlpha = 1;

  /* Settlers are plain filled circles.
   *
   * A deliberate deviation, stated honestly: gui.py's DEFAULT view has no agent
   * mark at all - `lookupFillColor` recolours the whole cell rectangle, so a
   * settler is a solid square that HIDES the sugar beneath it. (Its create_oval
   * call is the network overlay's per-cell shape, not the agent.) A dot keeps
   * the resource visible under the swarm, which is the read this broadcast is
   * built on, and it is how Epstein and Axtell's own plates draw agents.
   *
   * Sized by wealth; hollow when a settler has less than one timestep of food
   * left, so the die-off is visible just before it happens. */
  const bodies = interpolate(previous, frame, t);
  // 0.31 of a cell put a dot two thirds the width of the square it stood in, and
  // with 64 of them the swarm was reading as the subject and the lattice as its
  // backdrop. It is the other way round: the sand is the picture. Smaller, and
  // the settlers become what they are — bodies moving over a landscape. The
  // embed floor is the constraint on going further: at 640 a cell is 8 CSS px,
  // so this is a 4px dot, and the ring below is what keeps it a body.
  const radius = cell * 0.26;
  // A settler is red or blue and so is the ground it stands on - sugar ramps to
  // yellow, spice to rust - so a bare dot separated by HUE ALONE, which is the
  // one channel the terrain already uses. The ring makes it structural: every
  // settler carries the surround's own ink, so it reads as a body on a plate at
  // any resource depth and under any colour-vision deficiency.
  // An INK ring, now that the plate is dark.
  //
  // A red settler on the spice peak measured 1.07:1 against the ground it stood
  // on, and the ink ring meant to separate them is itself only 2.55:1 there. The
  // seat colours are the brightest things on the plate now, and the ring's job
  // is to hold them off the grains they stand among rather than off a bright
  // field. Keep it thin: a first attempt at cell*0.13 swallowed the body and the
  // settlers read as asterisks at the embed floor.
  const ring = Math.max(1, cell * 0.075);
  /* A settler's BODY is its culture, when the world has cultures.
   *
   * Cultural tagging is live in the shipped world and every settler carries a
   * tribe, so the dot that was a population marker now carries the one attribute
   * that actually changes during a run. Tribes are a property of the world, not
   * of a seat, so this reads correctly however many seats there are — but it
   * does mean seat identity is no longer in the body colour. With one seat that
   * costs nothing; a multi-seat world would need the seat back as a second ring.
   */
  const tribal = frame.agents.some((agent) => typeof agent.tribe === "number" && agent.tribe >= 0);
  const sheet = settlerSheet();
  for (const body of bodies) {
    const seat = seatOf(body.slot);
    const skin = tribal && typeof body.tribe === "number" && body.tribe >= 0
      ? TRIBE_INK[body.tribe % TRIBE_INK.length]
      : seat.color;
    const size = radius * (0.82 + 0.36 * Math.min(1, Math.log10(1 + body.wealth) / 2.4));
    /* SWAYED — a pulse in the culture it is changing TO.
     *
     * Three passes, and the difference between them is what the mark is FOR. A
     * paper halo said only "something happened to this one". Painting it in the
     * culture the settler LEFT put both colours on screen at once, which was
     * legible but read backwards: a ring is a thing radiating OUTWARD, and what
     * spreads through a Sugarscape is the culture doing the converting, not the
     * one being displaced. So the ring takes the NEW culture and opens — the
     * settler has just been reached by something spreading, and the pulse is
     * that arrival.
     *
     * Driven by the interpolation fraction, so it opens across the timestep it
     * belongs to. A cursor at rest holds it part-open rather than letting it
     * finish and vanish: a paused or scrubbed frame still has to show the event.
     */
    if (body.swayed) {
      // The pulse has to CLEAR the figure. A first pass opened from 0.26 to
      // 0.42 of a cell, which is inside the 0.45 the sprite box occupies, so the
      // ring drew under the gnome and what showed was a coloured blob rather
      // than something radiating. It starts outside the silhouette now.
      const open = (reducedMotion || t >= 1) ? 0.5 : t;
      context.beginPath();
      context.arc(body.px, body.py, cell * (0.42 + 0.26 * open), 0, Math.PI * 2);
      context.lineWidth = Math.max(1.6, cell * 0.11 * (1 - 0.4 * open));
      context.strokeStyle = skin;
      context.globalAlpha = 0.95 - 0.45 * open;
      context.stroke();
      context.globalAlpha = 1;
    }
    // A GNOME, when the atlas is present and the cell is big enough to hold one.
    const tile = sheet && sheet.tileFor(skin, hatRung(body.wealth), walkFrame(body, now));
    if (tile && cell >= SETTLER_MIN_CELL) {
      const box = cell * SETTLER_BOX;
      // STARVING FADES OUT. The hollow outline was a dot idiom: it worked when
      // the mark was a disc whose fill could be removed. A gnome has no single
      // fill to hollow, and outlining it just drew a second gnome. A settler with
      // less than a timestep of food left is going, so it goes translucent —
      // still placed, still its culture's colour, visibly not long for the world.
      context.globalAlpha = body.starving ? STARVING_ALPHA : 1;
      context.imageSmoothingEnabled = false;
      context.drawImage(tile, body.px - box / 2, body.py - box / 2, box, box);
      context.imageSmoothingEnabled = true;
      context.globalAlpha = 1;
      continue;
    }
    context.beginPath();
    context.arc(body.px, body.py, size, 0, Math.PI * 2);
    if (body.starving) {
      // Hollow means EMPTY, so it has to be the plate showing through. Filling
      // it with paper was right on a white field and is the brightest blob on
      // screen on a dark one — the exact opposite of the meaning.
      context.fillStyle = PLATE_HEX;
      context.fill();
      context.lineWidth = Math.max(1.2, cell * 0.12);
      context.strokeStyle = skin;
      context.stroke();
    } else {
      // seat.color, not seat.board: the board variants were darkened to sit on a
      // white field and disappear into this one.
      context.fillStyle = skin;
      context.fill();
      context.lineWidth = ring;
      context.strokeStyle = C.ink;
      context.stroke();
    }
  }

}

// ---------------------------------------------------------------------------
// Broadcast overlay
// ---------------------------------------------------------------------------

function escapeText(value) {
  return String(value).replace(/[&<>"]/g, (character) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character]
  ));
}

function format(value) {
  return Math.round(value).toLocaleString("en-US");
}

/** What the score actually counts. The engine sums sugar AND spice, but spice is
 *  inert in most variants, so saying "sugar plus spice" over a board with no
 *  spice on it is worse than saying what a viewer can see. One source, used by
 *  the masthead, the chart caption and the end card, so they cannot disagree. */
/** Total wealth held by everything alive. Used to tell an engine gini SENTINEL
 *  (0 for an empty world, 1 for a destitute one) from a real measurement. */
/* The ACTUAL value of a target's variable, from the engine's own per-tick stats.
 *
 * A distribution match of 0.930 says how closely the shape was hit but not what
 * the world actually did, and those are different questions — a run can match a
 * skewed-wealth target well while you still want to know the Gini it landed on.
 * Every one of these is a stat DTL already publishes, so none of it is re-derived
 * here and none of it can disagree with the score beside it.
 */
function targetActual(frame, variable) {
  const stats = frame.stats ?? {};
  const living = Number(stats.population ?? frame.agents.length) || 0;
  const num = (key, fallback = 0) => Number(stats[key] ?? fallback);
  switch (variable) {
    case "wealth":
      return { label: "Gini", value: num("giniCoefficient").toFixed(3) };
    case "population":
      return { label: "alive", value: `${Math.round(living)}` };
    case "age":
      return { label: "mean age", value: num("meanAge").toFixed(1) };
    case "age_at_death":
      return { label: "mean age at death", value: num("meanAgeAtDeath").toFixed(1) };
    case "majority_tribe_share":
      return {
        label: "largest tribe",
        value: living > 0 ? `${Math.round((num("largestTribeSize") / living) * 100)}%` : "—",
      };
    case "sick_fraction":
      return { label: "sick", value: `${num("sickAgentsPercentage").toFixed(0)}%` };
    case "mean_trade_price":
      return { label: "mean price", value: num("meanTradePrice").toFixed(2) };
    default:
      return null;
  }
}

/* THE SETTLER IS A GNOME, AND ITS HAT IS ITS WEALTH.
 *
 * The art is heartleaf's (src/sugarscape/art/, ATTRIBUTION.md), exported to a
 * 16x16 indexed atlas of three hat rungs by tools/export_settler.nim and inlined
 * here as base64 at build time. Indexed, not a PNG data URI, for three reasons
 * that all turned out to matter: it decodes SYNCHRONOUSLY so nothing here needs
 * Image or atob — a top-level use of either takes down every sandboxed block in
 * tools/test_viewer.mjs; it is ~1.6 KB against ~20 KB; and tribe colour becomes
 * a PALETTE SWAP rather than a canvas tint, which is the only way the recolour
 * does not fight the art.
 *
 * Three rungs, not more, and the size rides on the BRIM's width rather than the
 * crown's height. Both facts are measured, through the real 4.5:1 downscale at
 * the embed floor: brims of 0.42/0.64/0.90 cell render as 6/9/12 columns, while
 * a five-rung ladder puts two of its steps 1-2 columns apart, which cannot read
 * on a moving 9px body. A crown at 0.09 cell is 1.24px and half-dissolves.
 */
const SETTLER_ATLAS_B64 = "{{SETTLERS}}";
const SETTLER_BOX = 0.9;        // of a cell; 1.036 is where neighbours fuse
const SETTLER_MIN_CELL = 14;    // board units; below this the dot reads better
const STARVING_ALPHA = 0.38;    // a settler about to go, going
const WALK_MS = 150;            // one step; only ever runs while a settler moves
// Absolute, not relative to the frame: thresholds computed from the live
// population would move a settler's hat when OTHER settlers changed.
const HAT_RUNGS = [80, 220];

function hatRung(wealth) {
  let rung = 0;
  for (const edge of HAT_RUNGS) if (wealth >= edge) rung += 1;
  return rung;
}

/** Which walk frame a settler is on. A settler that did not move stands still —
 *  animating a stationary figure is a treadmill, not a walk. */
function walkFrame(body, now) {
  if (!body.moving || reducedMotion) return 0;
  return Math.floor(now / WALK_MS) % 2;
}

/** base64 -> bytes, by hand. `atob` is a browser global the test sandbox lacks. */
function unbase64(text) {
  const set = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = text.replace(/=+$/, "");
  const out = new Uint8Array(Math.floor((clean.length * 6) / 8));
  let bits = 0;
  let held = 0;
  let at = 0;
  for (const character of clean) {
    const value = set.indexOf(character);
    if (value < 0) continue;
    held = (held << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[at] = (held >> bits) & 0xff;
      at += 1;
    }
  }
  return out.subarray(0, at);
}

function shade(hex, amount) {
  const value = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16));
  const mix = (channel) => Math.round(channel * amount);
  return `rgb(${mix(r)},${mix(g)},${mix(b)})`;
}

let settlerAtlas;
function settlerSheet() {
  if (settlerAtlas !== undefined) return settlerAtlas;
  settlerAtlas = null;
  // An unsubstituted token means the build step did not run; fall back to dots
  // rather than throwing, so a hand-edited broadcast.js still renders.
  if (!SETTLER_ATLAS_B64 || SETTLER_ATLAS_B64.indexOf("{{") === 0) return settlerAtlas;
  let atlas;
  try {
    atlas = JSON.parse(new TextDecoder().decode(unbase64(SETTLER_ATLAS_B64)));
  } catch (error) {
    return settlerAtlas;
  }
  if (!atlas || !atlas.pix || !atlas.palette) return settlerAtlas;
  const pixels = unbase64(atlas.pix);
  if (pixels.length < atlas.w * atlas.h * atlas.rungs * (atlas.frames || 1)) return settlerAtlas;
  const cache = new Map();
  const hats = new Set(atlas.hat ?? []);
  const tunics = new Set(atlas.tunic ?? []);

  settlerAtlas = {
    atlas,
    tileFor(ink, rung, frame) {
      const frames = atlas.frames || 1;
      const step = Math.min(frames - 1, Math.max(0, frame | 0));
      const key = `${ink}:${rung}:${step}`;
      const held = cache.get(key);
      if (held) return held;
      const { w, h } = atlas;
      const tile = document.createElement("canvas");
      tile.width = w;
      tile.height = h;
      const paint = tile.getContext("2d");
      /* The palette swap, and it is the whole reason this is indexed art.
       *
       * The hat takes the tribe at full strength and its shadow stop a little
       * under, so the crown reads as one lit object rather than a flat wedge;
       * the tunic sits lower again so hat and body do not merge into a single
       * coloured mass. Beard, skin and boots are left exactly as authored — they
       * are what makes it a gnome rather than a coloured pawn, and tinting them
       * would take the figure with them.
       *
       * There is no outline role any more. A keyline around a sixteen-pixel
       * gnome draws a second gnome; the contrast is carried by the body values,
       * which clear 7:1 against the plate, and by the beard, which is the
       * brightest thing on the figure.
       */
      const palette = atlas.palette.map((colour, index) => {
        if (hats.has(index)) return index === atlas.hat[0] ? ink : shade(ink, 0.68);
        if (tunics.has(index)) return shade(ink, 0.80);
        return colour;
      });
      const base = (rung * frames + step) * w * h;
      for (let y = 0; y < h; y += 1) {
        for (let x = 0; x < w; x += 1) {
          const index = pixels[base + y * w + x];
          if (index === 0) continue;
          paint.fillStyle = palette[index] ?? "#000";
          paint.fillRect(x, y, 1, 1);
        }
      }
      cache.set(key, tile);
      return tile;
    },
  };
  return settlerAtlas;
}

function wealthTotal(frame) {
  let total = 0;
  for (const agent of frame.agents) total += agent.sugar + agent.spice;
  return total;
}

/** What this world is won by, in one line. See the masthead for why it varies. */
function mastheadStrapline(frame, big) {
  const seats = frame.coworld?.seats ?? [];
  if (seats.length > 0) {
    const variable = seats[0].variable ?? "wealth";
    // Measured, like the wording it replaces: the sparse line shares its band
    // with the clock panel, which starts at 506. "one ruleset each · closest
    // wealth to target wins" ended at 508.1 and printed into it.
    return big
      ? `match the target ${variable}`
      : `${count(seats.length, "seat")} · one ruleset · match the target ${variable}`;
  }
  if (big) return `most ${resourceName()} wins`;
  return `${count(frame.slots.length, "population")}, one lattice · most ${resourceName()} wins`;
}

/** "1 seat", "2 seats" — the plural has to agree with the world it describes. */
function count(value, noun) {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}

function resourceName() {
  return state.maxSpice > 0 ? "sugar + spice" : "sugar";
}

/** Every label gets a fat warm-ink outline so it survives scaling to the 360px
 *  embed floor over busy terrain. */
function text(content, x, y, options = {}) {
  const {
    size = 20, weight = 500, fill = C.paper, family = F.display,
    anchor = "start", spacing = null, outline = null, opacity = 1,
  } = options;
  // Mono gives a comma and a point a full cell, so a big figure reads loose.
  const track = spacing ?? (family === F.mono && size >= 28 ? -size * 0.035 : 0);
  // Scale the halo with the type: a fixed 3.4 units closed the counters on the
  // small labels it was meant to protect.
  const stroke = outline ?? Math.max(1.6, size * 0.14);
  return `<text x="${x}" y="${y}" font-family="${family}" font-size="${size}" `
    + `font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" `
    + `letter-spacing="${track}" opacity="${opacity}" `
    + `paint-order="stroke" stroke="${C.ink}" stroke-width="${stroke}" `
    + `stroke-linejoin="round">${escapeText(content)}</text>`;
}

/** Break a sentence into lines that fit `width` stage units at `size`.
 *
 *  SVG has no automatic wrapping and the end card's verdict is a full sentence —
 *  at 27 units a hundred characters is 1,400 units wide against a 1,068-unit
 *  plate, so the result ran off the card and the fix has to be measured rather
 *  than eyeballed. The 0.52em estimate is conservative for Space Grotesk's mixed
 *  case; erring narrow costs a line break, erring wide costs an overflow. */
function wrap(content, width, size) {
  const limit = Math.max(8, Math.floor(width / (size * 0.52)));
  const lines = [];
  let line = "";
  for (const word of String(content).split(/\s+/)) {
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length <= limit || !line) {
      line = candidate;
      continue;
    }
    lines.push(line);
    line = word;
  }
  if (line) lines.push(line);
  return lines;
}

/** "a" or "an" for a spoken number. `an 18.4% margin`, not `a 18.4% margin` -
 *  8, 11 and 18 are the leading forms that take "an", and this string is the
 *  largest sentence on the finish card. */
function article(value) {
  const digits = String(value).replace(/[^0-9]/g, "");
  return /^(8|11|18)/.test(digits) ? "an" : "a";
}

function eyebrow(content, x, y) {
  return text(content.toUpperCase(), x, y, {
    size: T(21), weight: 700, fill: C.muted, spacing: T(21) > 24 ? 2.0 : 2.6, outline: 3,
  });
}

function panel(x, y, width, height, radius = 10) {
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" `
    + `fill="${C.panel}" stroke="${C.border}" stroke-width="1.5"/>`;
}

/** The original draws every agent as a plain oval, so the board carries no shape
 *  encoding and neither does the HUD - a legend teaching a key the field does not
 *  use is worse than none. Identity is the seat colour plus the name and rank,
 *  which is the strongest redundancy available; red and blue also stay separable
 *  under every common colour-vision deficiency. */
function seatMark(x, y, slot, radius) {
  const seat = seatOf(slot);
  return `<circle cx="${x}" cy="${y}" r="${radius}" fill="${seat.color}" `
    + `stroke="${C.ink}" stroke-width="1.6"/>`;
}

/** The board's key. Nothing on screen said the yellow field was sugar, and the
 *  hollow settler was a visible state a viewer could not decode - the legend
 *  for it used to live in the feed's header and vanished at the embed floor. */
function boardKey(frame) {
  /* The key teaches what the board DRAWS, and it has been wrong every time the
   * board changed underneath it — a colour ramp after the plate became grain
   * density, grain density after the grains became countable dots, and coloured
   * discs after the settlers became gnomes. Each swatch below is now made the
   * same way its subject is: the resource marks are the same dots at the same
   * radius, and the culture swatches are the real sprite, tinted the real way.
   */
  const y = BOARD.y - Math.round(keyH * 0.28);
  let x = BOARD.x + 2;
  let markup = "";
  const size = T(18);
  const gap = G(20);
  const style = { size, weight: 600, fill: C.muted, outline: 2.6 };
  const spot = Math.max(1, G(3.2));
  const pitch = spot * 3.4;

  // One dot per unit, four of them, because four is the cap a tile can hold.
  // The old five-box 0..4 ramp printed boxes 13 units wide with sub-pixel specks
  // inside and read as punctuation.
  const ramps = [["sugar", SUGAR_HEX, state.maxSugar]];
  if (state.maxSpice > 0) ramps.push(["spice", SPICE_HEX, state.maxSpice]);
  for (const [label, ink, peak] of ramps) {
    const most = Math.max(1, Math.min(4, Math.round(peak)));
    for (let unit = 0; unit < most; unit += 1) {
      markup += `<circle cx="${(x + unit * pitch).toFixed(1)}" cy="${y - size * 0.32}" `
        + `r="${spot.toFixed(2)}" fill="${ink}"/>`;
    }
    x += (most - 1) * pitch + spot + G(8);
    markup += text(`${label} 1\u2013${most}`, x, y, style);
    x += advance(`${label} 1\u2013${most}`, size) + gap;
  }

  // The settlers themselves, drawn from the atlas so the key cannot drift from
  // the board again. Falls back to a disc when the sprite is not in play.
  const tribes = [...new Set(frame.agents
    .map((agent) => agent.tribe)
    .filter((tribe) => typeof tribe === "number" && tribe >= 0))].sort((a, b) => a - b);
  const mark = G(15);
  if (tribes.length > 0) {
    markup += text("cultures", x, y, style);
    x += advance("cultures", size) + G(8);
    for (const tribe of tribes) {
      const ink = TRIBE_INK[tribe % TRIBE_INK.length];
      markup += settlerSwatch(ink, x, y - mark + G(3), mark, 1);
      x += mark + G(2);
    }
    x += gap - G(2);
    // Swayed is the culture it LEFT, so the swatch has to be a ring, not a dot.
    markup += `<circle cx="${x + mark / 2}" cy="${y - mark / 2 + G(2)}" r="${mark / 2}" `
      + `fill="none" stroke="${TRIBE_INK[0]}" stroke-width="${G(2.4)}"/>`;
    markup += text("just swayed", x + mark + G(7), y, style);
    x += mark + G(7) + advance("just swayed", size) + gap;
    // Starving fades rather than hollows, so the swatch fades too — and it is
    // only offered when the replay can actually answer the question.
    if (!quantised(frame)) {
      markup += settlerSwatch(TRIBE_INK[1 % TRIBE_INK.length], x, y - mark + G(3), mark, STARVING_ALPHA);
      markup += text("about to starve", x + mark + G(7), y, style);
    }
    return markup;
  }

  const rightEdge = BOARD.x + BOARD.w;
  const tailWidth = mark + G(7) + advance("about to starve", size) + gap;
  const budget = (rightEdge - x - tailWidth) / Math.max(1, frame.slots.length);
  frame.slots.forEach((slot, index) => {
    markup += `<circle cx="${x}" cy="${y - G(6)}" r="${G(6)}" fill="${seatOf(index).color}"/>`;
    const full = slot.name || `Population ${index + 1}`;
    let label = dense() ? full.split(/\s+/).at(-1) : full;
    while (label.length > 1 && advance(label, size) + G(13) + gap > budget) {
      label = `${label.slice(0, -2)}\u2026`;
    }
    markup += text(label, x + G(13), y, style);
    x += G(13) + advance(label, size) + gap;
  });
  markup += `<circle cx="${x}" cy="${y - G(6)}" r="${G(6)}" fill="none" `
    + `stroke="${C.muted}" stroke-width="${G(2.2)}"/>`;
  markup += text("about to starve", x + G(13), y, style);
  return markup;
}

/** One settler, at key size, as an inline image so the legend is literally the
 *  same art the board blits. Cached: toDataURL is far too slow for a redraw. */
const swatchCache = new Map();
function settlerSwatch(ink, x, y, box, alpha) {
  const sheet = settlerSheet();
  if (!sheet) {
    return `<circle cx="${x + box / 2}" cy="${y + box / 2}" r="${box / 2}" `
      + `fill="${ink}" opacity="${alpha}"/>`;
  }
  let url = swatchCache.get(ink);
  if (!url) {
    url = sheet.tileFor(ink, 1, 0).toDataURL();
    swatchCache.set(ink, url);
  }
  return `<image href="${url}" x="${x}" y="${y}" width="${box}" height="${box}" `
    + `opacity="${alpha}" style="image-rendering:pixelated"/>`;
}

function scorebug(frame) {
  const rows = ranked(frame);
  const scheduled = state.maxTimestep || frame.timestep;
  const progress = scheduled > 0 ? Math.min(1, frame.timestep / scheduled) : 0;
  const big = dense();
  let markup = `<rect x="0" y="0" width="${W}" height="${BUG_H + 18}" fill="url(#bug-scrim)"/>`;

  // FINAL belongs to where the CURSOR is, not to whether the stream has ended:
  // scrubbing back into the middle of a finished episode is mid-match again.
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  // No percentage. On a 100-timestep match "62 / 100", a filled bar and "62%"
  // are three encodings of one number, two of them the same digits, in the
  // scarcest space on the frame. The fraction and the bar stay; the badge now
  // only carries what the fraction cannot say.
  const stateLabel = state.truncated ? "CUT SHORT" : atEnd ? "FINAL" : "";
  const stateFill = state.truncated ? C.loss : atEnd ? C.gold : C.muted;

  // Name the broadcast. Without it a first-time viewer can see two populations
  // and a number going up, but never learns what they are competing FOR.
  markup += text("SUGARSCAPE", MARGIN + 2, big ? 48 : 38, {
    size: T(27), weight: 700, fill: C.paper, spacing: big ? 4.2 : 5.2,
  });
  markup += text(
    // Not "one mountain": configuration.nim re-seats an out-of-range peak to a
    // RANDOM in-range coordinate, so how many massifs a world has is a property
    // of the seed, not of the config. Do not assert what the board can show.
    // Measured, not eyeballed: at 18 units the old "populations forage one
    // lattice" wording ran 524 units against a clock panel starting at 506.
    // The strapline states the WIN CONDITION, so it has to follow the world.
    // v3 hands each seat a target distribution and scores how closely its
    // ruleset grew that shape; nothing is won by holding the most of anything,
    // and printing "most sugar + spice wins" over it was simply false. A v1
    // replay is still a race and still says so. The plural also has to agree:
    // a one-seat world was reading "1 populations".
    mastheadStrapline(frame, big),
    MARGIN + 2, big ? 88 : 66, { size: T(18), weight: 500, fill: C.muted });

  // Clock — counts to the SCHEDULED end of the match, so an early extinction
  // freezes short of the buzzer instead of always landing on the last tick.
  //
  // The band is 92 units tall and the dense ramp sets the figure at 66, which
  // leaves no room to stack an eyebrow above it or run a progress bar beside it.
  // So dense states the fraction on one line and lets the transport's own played
  // track carry the bar — it already did, at both densities.
  /* THE CLOCK SITS IN THE TOP-RIGHT CORNER, ON NOTHING.
   *
   * It used to be a bordered card parked mid-band beside the masthead, which is
   * the treatment a panel earns by holding a navigable unit — a clock is one
   * number. The plate under it is already the darkest thing on the stage, so the
   * figure needs no card to sit on; the border was decoration and it competed
   * with the rail's panels, which are real. Right-aligned to the stage margin,
   * which is the same axis the rail's right edge uses.
   */
  const clockRight = W - MARGIN - 2;
  markup += text(`${frame.timestep} / ${scheduled}`, clockRight, big ? 62 : 66, {
    size: T(40), weight: 600, family: F.mono, fill: C.paper, anchor: "end",
  });
  if (stateLabel) {
    markup += text(stateLabel, clockRight, big ? 86 : 92, {
      size: T(18), weight: 700, family: F.mono, anchor: "end",
      fill: stateFill, spacing: 1.4,
    });
  } else if (!big) {
    // The played track already carries progress at the transport, so the bar
    // here is only worth its room when nothing else is using the second line.
    const barW = 240;
    markup += `<rect x="${clockRight - barW}" y="80" width="${barW}" height="7" rx="3.5" fill="${C.trackBed}"/>`;
    markup += `<rect x="${clockRight - barW}" y="80" width="${Math.max(3, barW * progress)}" `
      + `height="7" rx="3.5" fill="${C.gold}"/>`;
  }
  // Dense has no room for the second line, and CUT SHORT already stands in the
  // clock; the spoken broadcast carries the full sentence at both densities.
  //
  // Two different mutilations, and BOTH used to be silent about the timeline.
  // The server keeps a bounded live backlog, so a spectator who joins a long
  // episode late is handed a stream whose first frame is not t0 — the transport
  // then scrubs a window while looking exactly like a whole match. Say so.
  if (!big) {
    const note = state.truncated
      ? `stream ended at t${frames.at(-1).timestep} of ${scheduled} — no result`
      : joinedLate()
        ? `joined at t${frames[0].timestep} — earlier timesteps were not delivered`
        : "";
    if (note) {
      markup += text(note, MARGIN + 2, 92, {
        size: T(18), weight: 600, fill: state.truncated ? C.loss : C.muted,
      });
    }
  }

  /* NO CHIP STRIP ON A SCORED WORLD.
   *
   * The chip is a scoreboard: rank, name, score, margin over the field. That is
   * the right furniture for a race between populations and the wrong furniture
   * for a world where one seat is graded against a target — there is no rank to
   * hold, no field to lead, and the score it would print is already the headline
   * of the panel DIRECTLY BELOW it. Restating it in the corner was the whole
   * defect; changing which number it restated did not fix it.
   *
   * A v1 replay is a race and keeps its scoreboard.
   */
  if (frame.coworld?.seats?.some((entry) => typeof entry.score === "number")) {
    return markup;
  }

  // Standing — the score axis is total living wealth; population rides along as
  // the secondary figure because the visible race and the win metric differ.
  /* The chip strip IS the rail's column.
   *
   * chipW was a hardcoded 470, so the strip landed 22 units left of RAIL.x: the
   * right edges lined up and the left edges missed, on a layout whose entire
   * structure is two hard vertical axes. Deriving it from the rail makes the
   * miss impossible, and the clamp keeps a sixteen-population match from
   * printing chips too narrow to hold a name.
   */
  const gap = 14;
  const chipW = Math.max(210,
    (RAIL.w - gap * (rows.length - 1)) / rows.length);
  const total = rows.length * chipW + (rows.length - 1) * gap;
  let x = W - MARGIN - total;
  rows.forEach((row, rank) => {
    const leader = rank === 0 && !(rows[1] && rows[1].score === row.score);
    // The leader's margin is over second place; everyone else's is their gap to
    // the leader — measuring rank 2 against itself always printed "-0".
    const margin = rank === 0
      ? row.score - (rows[1]?.score ?? 0)
      : row.score - rows[0].score;
    // A saturated seat-colour border on the challenger out-shouted the leader's
    // gold; the seat colour lives on the dot, and the border only marks rank.
    markup += `<rect x="${x}" y="14" width="${chipW}" height="${BUG_H}" rx="10" `
      + `fill="${C.panel}" stroke="${leader ? C.gold : C.border}" `
      + `stroke-width="${leader ? 2.5 : 1.5}"/>`;
    markup += text(`${rank + 1}`, x + (big ? 30 : 26), big ? 66 : 70, {
      size: T(30), weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + (big ? 76 : 62), big ? 58 : 60, row.index, big ? 15 : 11);
    // The crown is a 3px smudge at the embed floor; the gold border and the rank
    // numeral already say the same thing there.
    if (leader && !big) {
      markup += `<path d="M ${x + 52} 32 l 5 -10 l 5 6.5 l 5 -11 l 5 11 l 5 -6.5 l 5 10 z" `
        + `fill="${C.gold}" stroke="${C.ink}" stroke-width="1.4" stroke-linejoin="round"/>`;
    }
    // Dense drops the secondary line rather than shrinking it — the population
    // count is still on the emergence panel and in the spoken standing — and
    // shortens the name, because a 92-unit chip cannot hold two dense lines.
    const nameX = x + (big ? 104 : 84);
    const nameW = Math.max(60, chipW - (big ? 300 : 250));
    const name = big ? row.name.split(/\s+/).at(-1) : row.name;
    markup += `<clipPath id="chip-${row.index}"><rect x="${nameX}" y="14" `
      + `width="${nameW}" height="${BUG_H}"/></clipPath>`;
    markup += `<g clip-path="url(#chip-${row.index})">`
      + text(name, nameX, big ? 70 : 52, {
        size: T(25), weight: 700, fill: C.paper, spacing: 0.3,
      })
      + `</g>`;
    if (!big) {
      // Just the headcount. It used to carry "· sugar + spice" as well, and on
      // the shipped dual-resource config that ran 27 characters of mono type
      // straight under the margin figure anchored at the chip's other end — the
      // two collided on every frame. The masthead already names what wins.
      markup += text(
        `${row.population} settler${row.population === 1 ? "" : "s"}`,
        nameX, 78,
        { size: T(20), weight: 500, family: F.mono, fill: C.muted },
      );
    }
    /* THE HEADLINE NUMBER IS WHAT THE EPISODE IS SCORED ON.
     *
     * On a v3 world that is the distribution match, not accumulated wealth. The
     * chip used to print total sugar + spice with a "+1,600" margin beside it,
     * which was the seat's own total restated as a lead over a rival that does
     * not exist in a one-seat world — a number that could only mislead. The
     * match score is the same figure the end card settles on, and the actual
     * value of the targeted variable rides underneath it. */
    const seatScore = frame.coworld?.seats?.find((entry) => entry.seat === row.index);
    const matched = seatScore && typeof seatScore.score === "number";
    markup += text(
      matched ? seatScore.score.toFixed(3) : format(row.score),
      x + chipW - 20, big ? 58 : 62,
      {
        size: T(40), weight: 700, family: F.mono, anchor: "end",
        fill: leader ? C.gold : C.muted,
      },
    );
    if (matched) {
      const actual = targetActual(frame, seatScore.variable);
      markup += text(
        actual ? `${actual.label} ${actual.value}` : "distribution match",
        x + chipW - 20, big ? 96 : 84,
        { size: big ? T(18) : T(20), weight: 600, family: F.mono, anchor: "end", fill: C.muted },
      );
    }
    /* THE GAP IS ONE FACT, so a two-horse race states it ONCE.
     *
     * Every chip used to carry a margin, so a two-population match printed "+236"
     * on the leader and "\u2212236" on the challenger: the same number, twice, in the
     * scarcest space on the frame, and the second copy carries nothing the first
     * did not. It reads as two statistics and is one.
     *
     * With three or more it stops being redundant \u2014 each chip's distance to the
     * leader is a different number \u2014 so they keep it, and the leader keeps its
     * margin over second place, which is a different quantity again. */
    const worthSaying = !matched && (rank === 0 || rows.length > 2);
    if (worthSaying) {
      markup += text(
        margin === 0 ? "level" : margin > 0 ? `+${format(margin)}` : `\u2212${format(-margin)}`,
        x + chipW - 20, big ? 96 : 84,
        {
          size: big ? T(18) : T(20), weight: 700, family: F.mono, anchor: "end",
          fill: margin > 0 ? C.gold : C.muted,
        },
      );
    }
    x += chipW + gap;
  });
  return markup;
}

/** The race.
 *
 *  Two populations farming the same mountain accumulate wealth on almost
 *  identical curves — plotted on a shared absolute axis their lines sit on top
 *  of each other and the contest is invisible. What is actually dramatic is the
 *  GAP: who is ahead, by how much, and every moment it flipped. So a two-horse
 *  race is drawn diverging about zero, which fills the plot from the first
 *  timestep and renders each lead change as a visible crossing. Three or more
 *  populations fall back to absolute lines, where a single gap is meaningless. */
/** The live figure beside each head dot, in that population's own colour.
 *
 *  Two populations dying at the same rate draw two lines on top of each other,
 *  so the shape alone cannot say which is which or by how much — and the count
 *  that mattered was the one thing the die-off banner did carry. It travels with
 *  the head now and changes on every timestep, instead of being shouted once and
 *  taken away.
 *
 *  Set to the RIGHT of the head, into the stretch of axis the episode has not
 *  reached yet, and flipped to the left of it for the last few timesteps, where
 *  it would otherwise print past the panel's edge. Two heads at nearly the same
 *  value would overprint, so they are pushed apart from the top down: the highest
 *  keeps its place and anything under it steps clear.
 *
 *  @param heads {{ slot, y, label }[]} one entry per line, unordered. */
function headCounts(heads, headX, bounds) {
  const size = T(18);
  const step = size * 1.15;
  /* A sixteen-population match — which the manifest permits — cannot carry
   * sixteen figures in a strip this short, and a pile-up reads as a fault rather
   * than as data. The lines and the scorebug still carry it; the labels go.
   *
   * The test is whether the pushed-apart stack SPANS the plot: first label at the
   * top, last at the baseline, one step between each. Measuring the stack's full
   * height instead cost one head's worth of room and dropped the labels for two
   * populations at the embed floor, which is the shipped config and the exact
   * case the figures were added for. */
  if (heads.length === 0 || (heads.length - 1) * step > bounds.base - bounds.top) return "";
  const widest = Math.max(...heads.map((head) => advance(head.label, size)));
  const after = bounds.left + bounds.plotW - headX > widest + G(20);
  const x = after ? headX + G(11) : headX - G(11);
  let markup = "";
  let previous = -Infinity;
  for (const head of [...heads].sort((first, second) => first.y - second.y)) {
    // Held inside the plot at both ends. An extinct population sits ON the
    // baseline, and below that is the shared time axis.
    const y = Math.min(
      bounds.base - 2,
      Math.max(head.y + size * 0.34, bounds.top + size * 0.8, previous + step),
    );
    previous = y;
    markup += text(head.label, x, y, {
      size, weight: 700, family: F.mono, fill: seatOf(head.slot).text,
      anchor: after ? "start" : "end", outline: 3,
    });
  }
  return markup;
}

/** The second plot on the race panel's time axis: how many settlers each
 *  population still has, timestep by timestep.
 *
 *  This is where the die-off went. It used to be a STINGER — a plate dropped over
 *  the middle of the board for two seconds whenever three settlers went at once,
 *  which on the shipped config is most timesteps, so the thing a viewer came to
 *  watch spent the episode behind a banner announcing what the board was already
 *  showing. A population that is dying is a line that falls: it reads at a
 *  glance, it keeps its whole history instead of two seconds of it, it says
 *  WHOSE settlers went, and because it hangs off the same time axis as the lead
 *  band above it, a collapse and the lead it cost sit on the same vertical. */
function settlerStrip(frame, plot) {
  const { left, plotW, scaleX, top, height, visible } = plot;
  const base = top + height;
  const axis = {
    size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  };
  // The scale is the largest headcount any ONE population has held, not the
  // starting figure: a variant with reproduction climbs past it, and a spectator
  // who joined late never saw it (see sawStart).
  const cap = Math.max(1, ...visible.flatMap((point) => point.population ?? []));
  const scaleY = (count) => base - (Math.max(0, count) / cap) * height;

  let markup = `<line x1="${left}" y1="${base}" x2="${left + plotW}" y2="${base}" `
    + `stroke="${C.axis}" stroke-width="1.5"/>`;
  markup += text(format(cap), left - 10, top + T(18) * 0.7, axis);
  // ABOVE its baseline, unlike the lead plot's "level". The strip is the bottom
  // plot on the panel, so below the baseline is the shared time axis — and a "0"
  // set there printed on top of the "t0" underneath it.
  //
  // Dropped at the embed floor, where the compact ramp sets both gutter figures
  // at 34 units against a 76-unit strip: the pair filled the plot they were
  // scaling. The floor is a baseline drawn under two lines that only fall, which
  // is the one end of a headcount axis a viewer can infer.
  if (!plot.big) markup += text("0", left - 10, base - 3, axis);
  if (visible.length === 0) return markup;

  const last = visible.at(-1);
  const headX = scaleX(last.timestep);
  const heads = [];
  frame.slots.forEach((_, slot) => {
    const points = visible
      .map((point) => `${scaleX(point.timestep).toFixed(1)},`
        + `${scaleY(point.population?.[slot] ?? 0).toFixed(1)}`)
      .join(" ");
    markup += `<polyline points="${points}" fill="none" stroke="${seatOf(slot).color}" `
      + `stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`;
    const count = last.population?.[slot] ?? 0;
    heads.push({ slot, label: format(count), y: scaleY(count) });
    // The head is drawn separately so a stream one timestep old is still a mark:
    // a polyline with a single point draws nothing at all.
    markup += `<circle cx="${headX.toFixed(1)}" cy="${scaleY(count).toFixed(1)}" `
      + `r="${G(5)}" fill="${seatOf(slot).color}" stroke="${C.ink}" stroke-width="1.6"/>`;
  });
  markup += headCounts(heads, headX, { left, plotW, top, base });

  /* Named inside the plot at its foot, on THE SIDE THE HEADS ARE NOT.
   *
   * The label was pinned to the bottom-left, on the reasoning that the lines
   * enter at the cap on the left and only fall, so the bottom-left is the
   * corner they leave empty. That holds at the END of an episode. It does not
   * hold at the start of one: the head sits where the episode has got to, its
   * figure is printed a few units to the right of it, and while that is still
   * near the left edge a steep early die-off puts both straight through the
   * caption. Restoring spice made this the common case rather than the rare
   * one — two metabolisms burn a settler down faster, so the headcount is
   * already at the foot of the plot while the head is barely off the axis.
   *
   * So the caption takes the far side from the head and swaps once, halfway
   * across. The heads only ever travel left to right, so whichever half they
   * are not in is empty for as long as they are not in it. */
  const captionLeft = headX >= left + plotW * 0.5;
  markup += text("settlers alive", captionLeft ? left + 12 : left + plotW - 12, base - 10, {
    size: T(18), weight: 600, fill: C.muted, outline: 3,
    anchor: captionLeft ? "start" : "end",
  });
  return markup;
}

/** What the panel's two plots share: the strip, and the one time axis both of
 *  them are drawn against. Called from both the lead-band path and the
 *  many-populations path, which is why it is not inlined in either. */
function raceTail(frame, plot) {
  let markup = settlerStrip(frame, plot);
  // At the embed floor these land under 7px, so the panel keeps its two plots and
  // drops the annotations rather than printing a smear.
  if (plot.big) return markup;
  const axis = {
    size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  };
  markup += text("t0", plot.left, plot.footY, { ...axis, anchor: "start" });
  markup += text(`t${plot.scheduled}`, plot.left + plot.plotW, plot.footY, axis);
  return markup;
}

function raceChart(frame, x, y, width, height) {
  const big = dense();
  const scheduled = state.maxTimestep || 1;
  const top = y + (big ? 62 : 46);
  /* The panel carries TWO plots against one time axis — the lead above, the
   * headcount below — so the height it used to give entirely to the lead is now
   * split three ways. The strip takes 30%: enough for two lines and their scale,
   * little enough that the lead band is still the thing the panel is about.
   *
   * The gap between them holds the lead plot's own axis caption, which used to
   * sit at the foot of the panel where the strip now is. Dense drops that caption
   * — its eyebrow already names the unit — and keeps the gap hairline-thin. */
  const plotArea = height - (big ? 84 : 76);
  const stripH = Math.round(plotArea * (big ? 0.32 : 0.3));
  // One caption's worth of clear air at either ramp. At 16 units the compact
  // ramp's "level" and the strip's own scale figure — 34 units each — printed
  // into one another across the join.
  const plotGap = big ? T(18) : T(18) + 12;
  const plotH = plotArea - stripH - plotGap;
  // The gutter has to hold the axis figure, which is set on the ramp: at 34
  // units "+2,334" is 122 units wide and a 62-unit gutter pushed it clean off
  // the panel's left edge.
  const left = x + (big ? 138 : 62);
  const plotW = width - left + x - 18;
  const scaleX = (timestep) => left + (timestep / scheduled) * plotW;
  const visible = wealthSeries.filter((point) => point.timestep <= frame.timestep);
  const plot = {
    big,
    left,
    plotW,
    scaleX,
    scheduled,
    visible,
    top: top + plotH + plotGap,
    height: stripH,
    footY: y + height - 16,
  };
  const leadCount = events.filter((event) => event.kind === "lead"
    && event.timestep <= frame.timestep).length;
  const axis = {
    size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  };

  let markup = panel(x, y, width, height);
  markup += eyebrow(big ? `Lead, in ${resourceName()}` : "The race", x + 18, y + (big ? 46 : 26));
  // The dense eyebrow names the unit because the bottom annotations are dropped,
  // and at 34 units it is already 508 units wide — the long form of this count
  // then ran the two headings into each other with nothing between them.
  markup += text(
    big
      ? `${leadCount} change${leadCount === 1 ? "" : "s"}`
      : leadCount === 0 ? "no lead change yet"
        : `${leadCount} lead change${leadCount === 1 ? "" : "s"}`,
    x + width - 18, y + (big ? 46 : 26),
    { size: T(18), weight: 600, family: F.mono, fill: C.gold, anchor: "end", spacing: 1 },
  );

  if (frame.slots.length !== 2) {
    // Absolute wealth lines — the general case.
    const scaleY = (score) => top + plotH - (score / state.maxWealth) * plotH;
    markup += `<line x1="${left}" y1="${top + plotH}" x2="${left + plotW}" y2="${top + plotH}" `
      + `stroke="${C.hairlineSoft}" stroke-width="1"/>`;
    markup += text(format(state.maxWealth), left - 10, top + 6, axis);
    frame.slots.forEach((_, slot) => {
      const points = visible
        .map((point) => `${scaleX(point.timestep).toFixed(1)},${scaleY(point.scores[slot] ?? 0).toFixed(1)}`)
        .join(" ");
      if (!points) return;
      const step = T(18) * 1.5;
      markup += `<polyline points="${points}" fill="none" stroke="${seatOf(slot).color}" `
        + `stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
      // The label is paper over the seat's dot, not the seat colour as ink: the
      // chip hues measure 4.4-4.7:1 against the halo every label is painted on,
      // so `text` is the lifted variant and the dot carries the identity.
      markup += seatMark(left + 14, top + step * 0.62 + slot * step, slot, G(6))
        + text(frame.slots[slot]?.name ?? `Population ${slot + 1}`,
          left + 28 + G(6), top + step * 0.62 + slot * step + T(18) * 0.34,
          { size: T(18), weight: 600, fill: seatOf(slot).text, outline: 2.8 });
    });
    // The caption hugs the plot's OWN baseline rather than the foot of the panel,
    // which now belongs to the strip's time axis.
    if (!big) {
      markup += text("total wealth", left + plotW, top + plotH + T(18) + 6, axis);
    }
    return markup + raceTail(frame, plot);
  }

  /* A DIVERGING lead: slot 0's above the line, slot 1's below it. Owner call.
   *
   * This has been both ways. It was diverging, then it was changed to plot the
   * ABSOLUTE lead always upward, on the reasoning that a viewer applying the
   * near-universal "up is winning" would see a descending band contradict the
   * scoreboard. The owner's read is the other one, and it is the stronger one:
   * with both spells drawn upward, SIDE carries nothing and the whole question
   * of who is ahead rests on telling two hues apart. Diverging gives it a second,
   * redundant channel — position — which is exactly what a colour-blind viewer
   * or a compressed stream has left when hue fails. The old objection is answered
   * by naming the poles instead of leaving "up" to be inferred: each half of the
   * plot carries its population's dot and name, so up reads as "A", not as "good".
   *
   * The scale is SYMMETRIC, and deliberately, though on the shipped recording it
   * costs: A peaks at +4,254 and B at only 201, so B's spells are genuinely thin.
   * That is the episode being lopsided, not the axis lying about it, and the gold
   * lead-change rules still mark every crossing. Scaling each half to its own
   * maximum would draw a 201 lead the same height as a 4,254 one.
   *
   * The band is STACKED BY RESOURCE: the sugar part of the lead from the midline
   * out, the spice part on top of it, so the height is still the real lead but a
   * viewer can see what it is made of. They do not always agree — on 9.5% of the
   * recording's timesteps one resource favours each population — and when they
   * disagree the outer band folds back across the line, which is the fact rather
   * than a fault: ink on a side is that side's advantage, whichever band it is in. */
  const leadOf = (point, key) => (point[key]?.[0] ?? 0) - (point[key]?.[1] ?? 0);
  const peak = Math.max(
    12,
    ...visible.map((point) => Math.abs(leadOf(point, "scores"))),
  );
  const midY = top + plotH / 2;
  const halfH = plotH / 2;
  const baseY = top + plotH;
  const scaleY = (lead) => midY - (lead / peak) * halfH;

  for (const event of events) {
    if (event.kind !== "lead" || event.timestep > frame.timestep) continue;
    markup += `<line x1="${scaleX(event.timestep)}" y1="${top}" `
      + `x2="${scaleX(event.timestep)}" y2="${baseY}" `
      + `stroke="${C.gold}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".6"/>`;
  }

  /* Clipped at the midline rather than segmented at the crossings. A band that
   * changes hands between two timesteps crosses the line somewhere BETWEEN two
   * plotted points; hunting for that intersection by hand is arithmetic the
   * renderer can hand to the clip, which cuts it exactly and for free. Each band
   * is drawn twice, once into each half, so a spell that straddles the line comes
   * out red above and blue below with the seam in the right place. */
  // Fixed ids: the overlay is one document that is rebuilt whole on every frame,
  // and it carries exactly one lead plot, so there is nothing for these to collide
  // with. They must not be generated per frame either — a new id every tick would
  // leave the browser resolving a fresh clip path 15 times a second.
  const above = "lead-above";
  const below = "lead-below";
  markup += `<defs>`
    + `<clipPath id="${above}"><rect x="${left}" y="${top}" `
    + `width="${plotW}" height="${halfH}"/></clipPath>`
    + `<clipPath id="${below}"><rect x="${left}" y="${midY}" `
    + `width="${plotW}" height="${halfH}"/></clipPath>`
    + `</defs>`;

  const along = (key) => visible
    .map((point) => `${scaleX(point.timestep).toFixed(1)},${scaleY(
      leadOf(point, key),
    ).toFixed(1)}`);
  const spiceEdge = along("spice");
  const totalEdge = along("scores");
  const firstX = scaleX(visible[0].timestep).toFixed(1);
  const lastX = scaleX(visible.at(-1).timestep).toFixed(1);

  // SPICE from the midline out, then sugar stacked from there to the true lead.
  // Two opacities of the SAME seat colour: which population is the first read and
  // must stay in one channel; which resource is the second and rides on density.
  // The denser tone is the one against the line, so the band always fades outward
  // — that is a property of the STACK, not of a resource, so the key below reads
  // its shades off this order rather than asserting one of its own.
  const band = (points, opacity) => {
    for (const [clip, slot] of [[above, 0], [below, 1]]) {
      markup += `<polygon points="${points}" fill="${seatOf(slot).color}" `
        + `opacity="${opacity}" clip-path="url(#${clip})"/>`;
    }
  };
  band(`${firstX},${midY.toFixed(1)} ${spiceEdge.join(" ")} ${lastX},${midY.toFixed(1)}`, ".46");
  band(`${spiceEdge.join(" ")} ${[...totalEdge].reverse().join(" ")}`, ".24");

  // The lead itself, over both bands, cut at the line into each side's colour.
  for (const [clip, slot] of [[above, 0], [below, 1]]) {
    markup += `<polyline points="${totalEdge.join(" ")}" fill="none" `
      + `stroke="${seatOf(slot).color}" stroke-width="2.6" stroke-linejoin="round" `
      + `stroke-linecap="round" clip-path="url(#${clip})"/>`;
  }

  markup += `<line x1="${left}" y1="${midY}" x2="${left + plotW}" y2="${midY}" `
    + `stroke="${C.axis}" stroke-width="1.5"/>`;
  markup += text(`+${format(peak)}`, left - 10, top + T(18) * 0.7, axis);
  markup += text("level", left - 10, midY + T(18) * 0.28, axis);
  markup += text(`+${format(peak)}`, left - 10, baseY, axis);

  /* Name the poles, which is what lets "up" mean a population rather than a
   * verdict. Set hard against the left edge inside each half, where the band
   * starts from the line and so leaves the corners empty. */
  frame.slots.slice(0, 2).forEach((slot, index) => {
    const name = slot?.name ?? `Population ${index + 1}`;
    const label = big ? name.split(/\s+/).at(-1) : name;
    const y = index === 0 ? top + T(17) : baseY - T(17) * 0.5;
    markup += seatMark(left + 12, y - T(17) * 0.32, index, G(4))
      + text(label, left + 22 + G(4), y, {
        size: T(17), weight: 600, fill: seatOf(index).text, outline: 2.8, opacity: 0.82,
      });
  });

  // Who currently holds it, stated in words at the head of the band.
  const last = visible.at(-1);
  if (last) {
    const lead = (last.scores[0] ?? 0) - (last.scores[1] ?? 0);
    const leader = lead === 0 ? -1 : (lead > 0 ? 0 : 1);
    const headY = scaleY(lead);
    markup += `<circle cx="${scaleX(last.timestep)}" cy="${headY}" r="${G(6)}" `
      + `fill="${leader < 0 ? C.muted : seatOf(leader).color}" stroke="${C.ink}" stroke-width="1.8"/>`;
    // The lifted `text` variant, not the chip colour: measured against the ink
    // halo this label is painted on, the blue chip is 4.40:1 and fails AA.
    // Shortened at the dense ramp: the full name runs under the band's own peak,
    // and the scorebug two panels up has just said which population it is.
    const holder = frame.slots[leader]?.name ?? `Population ${leader + 1}`;
    /* Ride the head, rather than sit in the plot's top-left corner.
     *
     * The corner is where the POLES are named now, and the two labels are the
     * same words — a fixed "A ahead" printed directly over the permanent "A"
     * that explains the upper half. Following the head also puts the sentence
     * where the eye already is, and on a diverging plot the head is the one
     * point whose side is the answer. It trails the head so it sits over the
     * stretch of axis the episode has not reached, and flips ahead of it at the
     * end, the same rule the settler strip's figures follow.
     */
    const caption = leader < 0
      ? "level"
      : `${big ? holder.split(/\s+/).at(-1) : holder} ahead`;
    const size = T(19);
    const headX = scaleX(last.timestep);
    const after = left + plotW - headX > advance(caption, size) + G(18);
    /* BESIDE the head, and held inside the plot at both ends.
     *
     * Offsetting it vertically clear of the band put it OUTSIDE the plot the
     * moment the current lead was the running peak — the normal case for a lead
     * that grows, since `peak` is exactly that maximum — and at the embed floor
     * it printed straight through the panel's own heading: "LEAD, IN SUGAR +
     * SPICA ahead". Level with the head instead. The band ends AT the head, so
     * the axis beyond it is empty by construction and there is nothing to dodge;
     * the clamp then bites only at the two extremes, tucking the line just
     * inside the edge rather than letting it leave the plot. */
    const capY = Math.min(
      baseY - size * 0.25,
      Math.max(top + size * 0.8, headY + size * 0.34),
    );
    markup += text(caption, headX + (after ? G(12) : -G(12)), capY, {
      size, weight: 700, fill: leader < 0 ? C.muted : seatOf(leader).text, outline: 3,
      anchor: after ? "start" : "end",
    });
  }

  // The unit, on the lead plot's own baseline. It used to be centred at the foot
  // of the panel, which is the strip's row now — and down there, under a second
  // plot in a different unit, it would have labelled the wrong one. Set to the
  // RIGHT: the band fills from the baseline up, so the row under the baseline is
  // the one clear lane on the panel, and the left of it already carries "level"
  // above and the strip's own scale below.
  if (!big) {
    /* The unit, and — when there are two resources — a key for the two shades.
     *
     * The band is stacked, so "lead, in sugar + spice" names what the height
     * measures but not what the seam inside it divides. The swatches carry the
     * two band opacities in a NEUTRAL ink rather than in a seat colour: the same
     * pair of densities is used above the line and below it, and keying them in
     * red would say red-is-sugar to a viewer reading the blue half. Density is
     * the channel, so the key is drawn in the one thing both halves share. */
    let keyX = left + plotW;
    if (state.maxSpice > 0) {
      const size = T(18);
      const chipW = G(14);
      const chipH = G(10);
      const keyY = baseY + T(18) + 6;
      // Wider than tall, so each swatch is a sample OF THE BAND rather than a
      // bullet: the two densities are compared across an area, which is how they
      // appear on the plot, and a square this small made them near-identical.
      //
      // Laid out right to left, so the pair reads "spice sugar" — the order they
      // are stacked in, from the line outward. The shade travels with the
      // POSITION in the stack, so if the two are ever swapped again this list is
      // the one place that has to move with them.
      for (const [label, opacity] of [["sugar", ".24"], ["spice", ".46"]]) {
        markup += text(label, keyX, keyY, axis);
        keyX -= advance(label, size) + G(7);
        markup += `<rect x="${keyX - chipW}" y="${keyY - chipH * 0.86}" `
          + `width="${chipW}" height="${chipH}" fill="${C.paper}" opacity="${opacity}"/>`;
        keyX -= chipW + G(13);
      }
      markup += text("lead:", keyX, baseY + T(18) + 6, axis);
    } else {
      markup += text(`lead, in ${resourceName()}`, keyX, baseY + T(18) + 6, axis);
    }
  }
  return markup + raceTail(frame, plot);
}

/** Fold a run of older beats into ONE row that accounts for all of them.
 *
 *  This is what makes the panel a ledger rather than a window. Every beat the
 *  feed does not show individually is inside this row's totals, so adding the
 *  visible rows up gives the same loss the emergence panel prints two panels
 *  below — which it did not before, with nothing on screen to reconcile them. */
function summarise(list) {
  const bySlot = new Map();
  let count = 0;
  let cause = "lost";
  let leads = 0;
  for (const event of list) {
    if (event.kind === "lead") {
      leads += 1;
      continue;
    }
    count += event.count;
    cause = event.cause ?? cause;
    for (const [slot, tally] of event.bySlot) {
      bySlot.set(slot, (bySlot.get(slot) ?? 0) + tally);
    }
  }
  return {
    index: list[0].index,
    kind: "summary",
    timestep: list[0].timestep,
    since: list[0].timestep,
    until: list.at(-1).timestep,
    count,
    cause,
    leads,
    bySlot: [...bySlot.entries()],
  };
}

/** Choose the feed's rows: newest beats one to a row, everything older folded
 *  into ONE summary that accounts for it.
 *
 *  The old rule merged runs of small losses wherever they fell, which was
 *  exactly backwards — the longer and duller the die-off, the fewer rows it
 *  produced, so on the shipped config the panel sat almost empty at t36 with a
 *  single line in it, and what it did show did not add up to the loss printed
 *  two panels below. Newest-first, so the freshest beat is at the top. */
function feedRows(seen, slots) {
  if (seen.length === 0 || slots <= 0) return [];
  const keyOf = (event) => `${event.index}:${event.kind}`;
  const lastLead = [...seen].reverse().find((event) => event.kind === "lead");
  /* Reserve the summary's row FIRST, then fill what is left.
   *
   * This used to append the rescued lead change and only then slice to
   * `slots - 1` to make room for the summary — which removed the row it had just
   * rescued, every time, at both densities. The ledger still balanced, because
   * the summary counts the lead it swallowed, so the test stayed green while the
   * panel's declared priority was dead code.
   */
  const needsSummary = seen.length > slots;
  const room = needsSummary ? slots - 1 : slots;
  let rows = seen.slice(-room).reverse();
  // A lead change is the beat this match is about; guarantee the most recent one
  // a row even when routine starvation would push it out.
  if (lastLead && room > 0 && !rows.some((event) => event.kind === "lead")) {
    rows = [...rows.slice(0, room - 1), { ...lastLead }];
  }
  const shown = new Set(rows.map(keyOf));
  const rest = seen.filter((event) => !shown.has(keyOf(event)));
  if (rest.length > 0) rows.push(summarise(rest));
  return rows;
}

function eventFeed(frame, x, y, width, height) {
  const big = dense();
  let markup = panel(x, y, width, height);
  const headY = y + (big ? 46 : 26);
  markup += eyebrow("What just happened", x + 18, headY);
  if (!big) {
    // A hollow settler is a state a viewer can see and could not decode.
    markup += `<circle cx="${x + width - 232}" cy="${y + 20}" r="6" fill="none" `
      + `stroke="${C.muted}" stroke-width="2.2"/>`;
    markup += text("hollow = about to starve", x + width - 218, headY, {
      size: T(18), weight: 500, fill: C.dim, outline: 2.4,
    });
  }

  const seen = events.filter((event) => event.timestep <= frame.timestep);
  const limit = big ? 3 : 4;

  let rowY = y + (big ? 72 : 58);
  const rowStep = big ? 72 : 54;
  // The stamp column has to hold the WIDEST stamp, which is the summary row's
  // range - "t6-29" at the dense ramp is 95 units and ran straight into the
  // accent rule. And the rule itself sat 12 units clear of its row's text, four
  // CSS pixels at the embed floor, so the two read as one glyph.
  const indent = big ? 210 : 128;
  const barGap = big ? 40 : 16;
  const barW = big ? 6 : 4;

  // A live row, always. Without it the panel could sit on a beat from nine
  // timesteps ago under a heading that promises the present.
  // Only when the feed would otherwise sit on something genuinely old. It used
  // to fire every few timesteps and spend the top slot restating the scorebug.
  const quiet = seen.length === 0
    || frame.timestep - (seen.at(-1).until ?? seen.at(-1).timestep) > 8;
  let slots = limit;
  const stampY = big ? 34 : 15;
  if (quiet) {
    markup += text(`t${frame.timestep}`, x + 18, rowY + stampY, {
      size: T(19), weight: 600, family: F.mono, fill: C.gold,
    });
    markup += `<rect x="${x + indent - barGap}" y="${rowY - 2}" width="${barW}" height="${T(24)}" rx="2" `
      + `fill="${C.muted}"/>`;
    markup += text(
      // Not "the mountain": the shipped config seeds four peaks, two of sugar
      // and two of spice, so how many massifs a world has is a property of the
      // seed. The lattice is the thing every configuration has.
      big
        ? `${frame.agents.length} settlers foraging`
        : `${frame.agents.length} settlers still foraging the lattice`,
      x + indent, rowY + (big ? 36 : 16),
      { size: T(25), weight: 500, fill: C.paper },
    );
    rowY += rowStep;
    slots -= 1;
  }

  const recent = feedRows(seen, slots);

  if (recent.length === 0 && !quiet) {
    markup += text("The settlers spread out across the lattice.", x + 18, y + 62, {
      size: T(24), weight: 500, fill: C.muted,
    });
    return markup;
  }

  for (const event of recent) {
    const fresh = (event.until ?? event.timestep) === frame.timestep;
    const stamp = event.kind === "summary" && event.until > event.since
      ? `t${event.since}–${event.until}`
      : `t${event.timestep}`;
    markup += text(stamp, x + 18, rowY + stampY, {
      size: T(19), weight: 600, family: F.mono, fill: fresh ? C.gold : C.dim,
    });
    if (event.kind === "death" || event.kind === "summary") {
      markup += `<rect x="${x + indent - barGap}" y="${rowY - 2}" width="${barW}" height="${T(24)}" rx="2" fill="${C.dim}"/>`;
      // No flavour text: an earlier version asserted the losses were at the
      // mountain's edge, which nothing here computes and which the recording
      // does not actually support for the runs it was printed on.
      const shorten = (name) => (big ? name.split(/\s+/).at(-1) : name);
      const detail = event.bySlot
          .filter(([slot]) => slot >= 0)
          .map(([slot, count]) => `${count} ${shorten(frame.slots[slot]?.name ?? `slot ${slot}`)}`)
          .join(", ");
      const named = event.bySlot.filter(([slot]) => slot >= 0);
      // One population involved reads better as "3 Population A starved" than
      // as "3 starved - 3 Population A", which prints the count twice.
      const line = named.length === 1
        ? `${event.count} ${shorten(frame.slots[named[0][0]]?.name ?? "")} ${event.cause ?? "lost"}`
        : `${event.count} ${event.cause ?? "lost"}${detail ? ` — ${detail}` : ""}`;
      // The summary row says how many lead changes are inside it, so a viewer
      // can see the panel is accounting for beats it is not naming.
      const leadSuffix = `${event.leads} lead change${event.leads === 1 ? "" : "s"}`;
      const folded = event.kind === "summary" && event.leads > 0
        ? `${line}${event.count > 0 ? " · " : ""}${leadSuffix}`
        : line;
      /* A WIDTH BUDGET, for the same reason the board's key has one.
       *
       * This row accumulated its clauses and drew them with no measurement
       * against the panel it sits in, and the summary is the longest line the
       * feed ever prints: a count, a cause, a per-population breakdown and a
       * folded lead-change tally. At the 640 embed floor it ran off the right
       * edge — "164 starved — 93 B, 71 A · 2 lead c" — losing the very tally
       * the clause was added to disclose. The row cannot wrap (the feed's
       * geometry gives every event exactly one row), so it SHEDS: the folded
       * tally first, then the breakdown, and the count and cause always
       * survive. What is dropped was already a refinement of what is kept, so
       * a shorter line is never a different claim. The tally goes first
       * because it is the one clause that is ALSO printed elsewhere — the race
       * panel's header carries the same count — while which population is
       * losing its settlers is said here or nowhere. */
      const size = T(25);
      const budget = width - indent - T(28);
      const candidates = event.count === 0 && event.kind === "summary"
        ? [leadSuffix]
        : [folded, line, `${event.count} ${event.cause ?? "lost"}`];
      const fitted = candidates.find((option) => advance(option, size) <= budget)
        ?? candidates[candidates.length - 1];
      markup += text(
        fitted,
        x + indent, rowY + (big ? 36 : 16),
        { size, weight: 500, fill: fresh ? C.paper : C.muted },
      );
    } else {
      markup += `<rect x="${x + indent - barGap}" y="${rowY - 2}" width="${barW}" height="${T(24)}" rx="2" `
        + `fill="${seatOf(event.slot).color}"/>`;
      markup += text(
        `${event.name} takes the lead`,
        x + indent, rowY + (big ? 36 : 16),
        { size: T(25), weight: 700, fill: fresh ? C.paper : C.muted },
      );
    }
    rowY += rowStep;
  }

  return markup;
}

/** The readouts that make Sugarscape's famous emergent result legible: an
 *  inequality curve nobody programmed. (A carrying-capacity readout used to sit
 *  beside it and was removed - the engine's `carryingCapacity` is a lagging
 *  average of the headcount with a ceil() ratchet, so presenting it as a ceiling
 *  the world imposes was simply false.) */
/* WHAT v3 IS ACTUALLY PLAYING.
 *
 * This world is not a race. Each seat submits one declarative ruleset, the world
 * runs with no further input, and the seat is scored on how closely the
 * distribution it GREW matches a target distribution it was handed. So the rail
 * asks v3's own question, with v3's own readouts — the measured histogram
 * against the target, and the match score over the episode.
 *
 * The measured bars and the target line share one vertical scale, because the
 * whole claim is "these two shapes are/aren't the same" and two scales would let
 * a mismatch print as a match.
 */
/* Which target the histogram is read against.
 *
 * An episode is ASSIGNED one target, but the engine measures every variable in
 * the catalog each tick regardless, so any target can be asked of any run. That
 * is a genuinely different question from the one the episode was scored on —
 * "how close did this ruleset come to a target it was never given?" — so the
 * assigned one stays marked and stays the default. */
let targetChoice = null;

/** The chosen target as a seat-shaped record, or the assigned seat unchanged. */
function readingFor(frame) {
  const seat = frame.coworld?.seats?.[0];
  const choices = frame.coworld?.choices ?? [];
  if (!targetChoice) return seat;
  const pick = choices.find((choice) => choice.id === targetChoice);
  if (!pick) return seat;
  return {
    seat: seat?.seat ?? 0,
    name: seat?.name,
    targetId: pick.id,
    variable: pick.variable,
    bins: pick.bins,
    targetProbs: pick.targetProbs,
    measuredProbs: pick.measuredProbs,
    sampleCount: pick.sampleCount,
    measured: Boolean(pick.measuredProbs?.length),
    score: pick.score,
    assigned: pick.assigned,
  };
}

function targetHistogram(frame, x, y, width, height) {
  const big = dense();
  const seats = frame.coworld?.seats ?? [];
  let markup = panel(x, y, width, height);
  markup += eyebrow("Did the rules grow the target?", x + 18, y + (big ? 46 : 26));
  if (seats.length === 0) return markup;

  const seat = readingFor(frame);
  if (!seat) return markup;
  const headY = y + (big ? 46 : 26) + 34;
  const score = typeof seat.score === "number" ? seat.score : null;
  // The score is the headline, so it takes the figure treatment; the target it
  // is scored against is named right under it, never left as a bare number.
  markup += text(score === null ? "—" : score.toFixed(3), x + 18, headY + T(40), {
    size: T(40), weight: 600, family: F.mono, fill: score === null ? C.muted : C.gold,
  });
  markup += text("distribution match", x + 18, headY + T(40) + 22, {
    size: T(18), weight: 600, fill: C.muted, spacing: 1.4,
  });
  // Say plainly when the reading is NOT the one the episode was played for, so a
  // browsed score is never mistaken for the result.
  const offTarget = seat.assigned === false;
  markup += text(
    `${seat.variable ?? "wealth"} · ${seat.targetId ?? "target"}${offTarget ? " · not this episode's target" : ""}`,
    x + 18, headY + T(40) + 44,
    { size: T(17), weight: 500, family: F.mono, fill: offTarget ? C.gold : C.dim });

  const plotTop = headY + T(40) + 60;
  const plotH = Math.max(30, y + height - plotTop - 30);
  const plotX = x + 18;
  const plotW = width - 36;
  const target = seat.targetProbs ?? [];
  const measured = seat.measuredProbs ?? [];
  const buckets = Math.max(target.length, measured.length);
  if (buckets === 0 || plotH < 24) return markup;
  const ceiling = Math.max(0.0001, ...target, ...measured);
  const barW = plotW / buckets;
  const yFor = (p) => plotTop + plotH - (p / ceiling) * plotH;

  // Measured first, as filled bars: it is the thing that happened.
  for (let index = 0; index < buckets; index += 1) {
    const value = measured[index] ?? 0;
    if (value <= 0) continue;
    const top = yFor(value);
    markup += `<rect x="${(plotX + index * barW + 1).toFixed(1)}" y="${top.toFixed(1)}" `
      + `width="${Math.max(1, barW - 2).toFixed(1)}" height="${(plotTop + plotH - top).toFixed(1)}" `
      + `fill="${seatOf(seat.seat).color}" opacity="0.55"/>`;
  }
  // Target as a STEP line, not a smooth one: it is a histogram, and a curve
  // through bin centres would imply a continuity the bins do not have.
  if (target.length) {
    const steps = [];
    for (let index = 0; index < target.length; index += 1) {
      const top = yFor(target[index]);
      steps.push(`${(plotX + index * barW).toFixed(1)},${top.toFixed(1)}`);
      steps.push(`${(plotX + (index + 1) * barW).toFixed(1)},${top.toFixed(1)}`);
    }
    markup += `<polyline points="${steps.join(" ")}" fill="none" `
      + `stroke="${C.paper}" stroke-width="2" stroke-linejoin="round"/>`;
  }
  markup += `<line x1="${plotX}" y1="${plotTop + plotH}" x2="${plotX + plotW}" `
    + `y2="${plotTop + plotH}" stroke="${C.axis}" stroke-width="1"/>`;
  markup += text("measured", plotX, plotTop + plotH + 20,
    { size: T(17), weight: 600, family: F.mono, fill: seatOf(seat.seat).text });
  markup += text("target", plotX + plotW, plotTop + plotH + 20,
    { size: T(17), weight: 600, family: F.mono, fill: C.paper, anchor: "end" });
  return markup;
}

/* INEQUALITY OVER TIME — the Gini coefficient, tick by tick.
 *
 * This replaced a Lorenz square with a Gini figure beside it, which the owner
 * rejected as broken and unclear, and was both: it printed "53 of 30 settlers"
 * because the readout assumed a population can only shrink, and the curve was
 * unlabelled apart from "poorest → richest" with an unexplained diagonal, so it
 * asked the viewer to already know what a Lorenz curve is before it said
 * anything. A single number at one instant also hid the thing worth seeing —
 * inequality is INTERESTING because of how it moves. The famous Sugarscape
 * result is not that Gini is 0.37, it is that fair rules drive it upward.
 *
 * The trade footer rides here because exchange is the mechanism the wealth is
 * moving through. Volume and mean price are all the replay carries; DTL records
 * no partner pairs, so this cannot say WHO traded, only how much trading there
 * was, and it says exactly that.
 */
function inequalityOverTime(frame, x, y, width, height) {
  const big = dense();
  let markup = panel(x, y, width, height);
  markup += eyebrow("Inequality over time", x + 18, y + (big ? 46 : 26));

  const upto = currentIndex();
  const plotX = x + 52;
  const plotW = width - 70;
  const plotTop = y + (big ? 46 : 26) + 18;
  const plotH = Math.max(24, height - (plotTop - y) - 54);
  const span = Math.max(1, frames.length - 1);
  // Gini is a 0..1 quantity and the whole point is where it SITS on that scale,
  // so the axis is the scale. Autoscaling would make any run look dramatic.
  const xFor = (index) => plotX + (index / span) * plotW;
  const yFor = (value) => plotTop + plotH - Math.max(0, Math.min(1, value)) * plotH;
  const giniAt = (each) => Number(each?.stats?.giniCoefficient ?? 0);

  markup += `<line x1="${plotX}" y1="${plotTop + plotH}" x2="${plotX + plotW}" `
    + `y2="${plotTop + plotH}" stroke="${C.axis}" stroke-width="1"/>`;
  // A named landmark beats a bare axis: 0.4 is the conventional "high" line, and
  // the classic Sugarscape run settles around 0.5.
  markup += `<line x1="${plotX}" y1="${yFor(0.4).toFixed(1)}" x2="${plotX + plotW}" `
    + `y2="${yFor(0.4).toFixed(1)}" stroke="${C.guide}" stroke-width="1" stroke-dasharray="4 4"/>`;
  markup += text("0.4", plotX - 6, yFor(0.4) + 5,
    { size: T(16), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });
  markup += text("1", plotX - 6, plotTop + 10,
    { size: T(16), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });
  markup += text("0", plotX - 6, plotTop + plotH,
    { size: T(16), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });

  const points = [];
  for (let index = 0; index <= upto && index < frames.length; index += 1) {
    points.push(`${xFor(index).toFixed(1)},${yFor(giniAt(frames[index])).toFixed(1)}`);
  }
  if (points.length > 1) {
    markup += `<polyline points="${points.join(" ")}" fill="none" `
      + `stroke="${C.gold}" stroke-width="2.5" stroke-linejoin="round"/>`;
  }
  const now = giniAt(frame);
  const opened = giniAt(frames[0]);
  if (points.length) {
    markup += `<circle cx="${xFor(upto).toFixed(1)}" cy="${yFor(now).toFixed(1)}" r="4" fill="${C.gold}"/>`;
  }
  // Never a bare number: the value, which way it has moved since the start, and
  // what that means in words.
  /* ONE ROW, TWO READINGS, AND A MEASURED BUDGET BETWEEN THEM.
   *
   * The Gini figure sits left and the trade line right, on the same baseline, and
   * the first draft let both run at full length: "up 0.123 from 0.000" collided
   * with "30 trades this tick" and printed "from 0.0(30)trades". So the trade
   * line is measured first, because it is the shorter and more perishable fact,
   * and the drift clause is only drawn in the room that is actually left. */
  const drift = now - opened;
  const figure = now.toFixed(3);
  const figureEnd = plotX + advance(figure, T(22)) + 10;
  markup += text(figure, plotX, plotTop + plotH + 22,
    { size: T(22), weight: 600, family: F.mono, fill: C.paper });

  const stats = frame.stats ?? {};
  let tradeStart = plotX + plotW;
  if (stats.tradeVolume !== undefined) {
    const volume = Number(stats.tradeVolume) || 0;
    const price = Number(stats.meanTradePrice) || 0;
    // Zero is a real reading here, not a missing one.
    const line = volume === 0
      ? "no trades this tick"
      : `${volume} trade${volume === 1 ? "" : "s"} · mean price ${price.toFixed(2)}`;
    tradeStart = plotX + plotW - advance(line, T(17));
    markup += text(line, plotX + plotW, plotTop + plotH + 22,
      { size: T(17), weight: 500, family: F.mono, fill: C.muted, anchor: "end" });
  }
  const way = Math.abs(drift) < 0.005 ? "level with the start"
    : `${drift > 0 ? "up" : "down"} ${Math.abs(drift).toFixed(3)} from ${opened.toFixed(3)}`;
  if (figureEnd + advance(way, T(17)) + 12 < tradeStart) {
    markup += text(way, figureEnd, plotTop + plotH + 22,
      { size: T(17), weight: 500, family: F.mono, fill: C.dim });
  }
  return markup;
}

/* CULTURE — each tribe's share of the living population, over time.
 *
 * The other readout worth showing in any episode. Epstein and Axtell's cultural
 * tagging is live in the shipped world (three tribes, ten agents each at t0) and
 * `majority_tribe_share` is a target variable with two shipped targets pulling
 * opposite ways — `tribe.convergence` toward one culture swallowing the rest,
 * `tribe.diversity` toward pluralism holding. Which of those a run produced is
 * exactly what this plot shows, and nothing else on the stage said it.
 *
 * Shares, not counts, so convergence reads as a line climbing to the top while
 * the others fall away, independently of whether the population is growing or
 * dying. Drawn from the frames, so it works on any replay carrying tribes.
 */
/* Tribe inks, MEASURED against the two things they have to survive.
 *
 * Each clears 7:1 against PLATE_HEX, because that is the ground a settler
 * actually stands on: 99.2% of agent-frames sit on a cell the settler has
 * already stripped, so the body value carries the mark and the ink ring cannot
 * help there (ink is 1.09:1 against the plate).
 *
 * Two were wrong, and both were mine. #f0a63c was BYTE-IDENTICAL to SPICE_HEX,
 * so the first tribe's settlers were exactly the colour of the spice dots they
 * stand among — a 1.00:1 collision, worse than the 1.07:1 that put the ink ring
 * there in the first place. #d98cae measured 6.98:1 against the plate, under the
 * bar it was picked to clear. Now #ef8f7c (7.46:1 plate, 1.15:1 spice) and
 * #dd9ab8 (7.88:1 plate). Anything added here gets measured, not eyeballed.
 */
const TRIBE_INK = ["#ef8f7c", "#7fb3d5", "#c9d17a", "#dd9ab8", "#8fd1c0", "#e8c07d"];

function tribeShares(frame, x, y, width, height) {
  const big = dense();
  let markup = panel(x, y, width, height);
  markup += eyebrow("Culture", x + 18, y + (big ? 46 : 26));

  const sharesAt = (each) => {
    const counts = new Map();
    for (const agent of each.agents) {
      const tribe = agent.tribe;
      if (tribe === undefined || tribe === null || tribe < 0) continue;
      counts.set(tribe, (counts.get(tribe) ?? 0) + 1);
    }
    let total = 0;
    for (const value of counts.values()) total += value;
    return { counts, total };
  };

  const tribes = new Set();
  for (const each of frames) for (const tribe of sharesAt(each).counts.keys()) tribes.add(tribe);
  const order = [...tribes].sort((a, b) => a - b);
  const plotX = x + 44;
  const plotW = width - 62;
  const plotTop = y + (big ? 46 : 26) + 20;
  const plotH = Math.max(24, height - (plotTop - y) - 46);
  const span = Math.max(1, frames.length - 1);
  const xFor = (index) => plotX + (index / span) * plotW;
  const yFor = (share) => plotTop + plotH - Math.max(0, Math.min(1, share)) * plotH;

  markup += `<line x1="${plotX}" y1="${plotTop + plotH}" x2="${plotX + plotW}" `
    + `y2="${plotTop + plotH}" stroke="${C.axis}" stroke-width="1"/>`;
  markup += text("all", plotX - 6, plotTop + 12,
    { size: T(16), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });
  markup += text("0", plotX - 6, plotTop + plotH,
    { size: T(16), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });

  if (order.length === 0) {
    markup += text("this world has no tribes", plotX, plotTop + plotH / 2,
      { size: T(18), weight: 500, family: F.mono, fill: C.dim });
    return markup;
  }

  const upto = currentIndex();
  let leader = null;
  let leaderShare = 0;
  order.forEach((tribe, position) => {
    const points = [];
    for (let index = 0; index <= upto && index < frames.length; index += 1) {
      const { counts, total } = sharesAt(frames[index]);
      if (total <= 0) continue;
      points.push(`${xFor(index).toFixed(1)},${yFor((counts.get(tribe) ?? 0) / total).toFixed(1)}`);
    }
    if (points.length > 1) {
      markup += `<polyline points="${points.join(" ")}" fill="none" `
        + `stroke="${TRIBE_INK[position % TRIBE_INK.length]}" stroke-width="2.5" `
        + `stroke-linejoin="round"/>`;
    }
  });
  const { counts, total } = sharesAt(frame);
  for (const tribe of order) {
    const share = total > 0 ? (counts.get(tribe) ?? 0) / total : 0;
    if (share > leaderShare) { leaderShare = share; leader = tribe; }
  }
  // Never a bare number, and never a bare chart: say which way it went.
  const verdict = leaderShare >= 0.999 ? "one culture left"
    : leaderShare >= 0.6 ? "converging on one"
      : "holding apart";
  markup += text(`${order.length} tribes · ${verdict}`, plotX, plotTop + plotH + 20,
    { size: T(17), weight: 600, family: F.mono, fill: C.paper });
  if (leader !== null) {
    markup += text(`largest ${Math.round(leaderShare * 100)}%`, plotX + plotW, plotTop + plotH + 20,
      { size: T(17), weight: 500, family: F.mono, fill: C.dim, anchor: "end" });
  }
  return markup;
}

function emergence(frame, x, y, width, height) {
  const big = dense();
  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);
  const population = frame.agents.length;

  let markup = panel(x, y, width, height);
  markup += eyebrow("Nobody programmed this", x + 18, y + (big ? 46 : 26));

  // Lorenz curve — the signature Sugarscape chart, drawn from the live agents.
  const curveX = x + 18;
  const curveY = y + 44;
  // Leave room for the caption BELOW the square, inside the panel: it used to be
  // sized off the full panel height and punched through the bottom hairline.
  const size = Math.max(40, height - 44 - 40 - 18);
  // The Lorenz curve is the signature chart but the first thing to go at the
  // embed floor: unlabelled and 60px wide it carries nothing a viewer can read.
  const showCurve = !big;
  const wealth = frame.agents
    .map((agent) => Math.max(0, agent.sugar + agent.spice))
    .sort((first, second) => first - second);
  const total = wealth.reduce((sum, value) => sum + value, 0);
  if (showCurve) {
    markup += `<rect x="${curveX}" y="${curveY}" width="${size}" height="${size}" `
      + `fill="${C.wash}" stroke="${C.hairline}" stroke-width="1"/>`;
    markup += `<line x1="${curveX}" y1="${curveY + size}" x2="${curveX + size}" y2="${curveY}" `
      + `stroke="${C.guide}" stroke-width="1" stroke-dasharray="4 4"/>`;
  }
  if (showCurve && total > 0) {
    let cumulative = 0;
    const points = [`${curveX},${curveY + size}`];
    wealth.forEach((value, index) => {
      cumulative += value;
      points.push(
        `${(curveX + size * (index + 1) / wealth.length).toFixed(1)},`
        + `${(curveY + size * (1 - cumulative / total)).toFixed(1)}`,
      );
    });
    markup += `<polyline points="${points.join(" ")}" fill="none" stroke="${C.gold}" stroke-width="2.5"/>`;
  }
  if (showCurve) {
    markup += text("poorest → richest", curveX + size / 2, curveY + size + 24,
      { size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4 });
  }

  // Two readouts, not three: the live population is already on both scorebug
  // chips, so repeating it as "survivors" only crowded the panel.
  //
  // Dense stacks nothing: at 66 units a figure with a label above and a note
  // below is 150 units tall, and two of those do not fit a rail that has already
  // given its height to the race and the feed. The rail is 932 units WIDE, so
  // dense turns the readouts through ninety degrees and sets them side by side,
  // with notes short enough to hold a half-column.
  // Net change, not a death count - the engine can also add agents - so this
  // is deliberately labelled 'lost' rather than asserting a cause.
  const lost = Math.max(0, state.startingPopulation - population);
  // The engine SENTINELS this: giniCoefficient is 0 when nobody is alive and 1
  // when the living hold nothing (simulation.nim). Glossing 0 as "spread fairly
  // evenly" printed a contented sentence over an extinct world.
  const spread = population === 0 ? ["no settlers left", "none left"]
    : wealthTotal(frame) === 0 ? ["nobody holds anything", "nothing held"]
      : gini > 0.4 ? ["a few settlers hold almost all of it", "a few hold nearly all"]
        : gini > 0.28 ? ["the richest hold most of it", "the richest hold most"]
          : ["spread fairly evenly", "spread evenly"];
  const rows = [
    ["Inequality", population === 0 ? "\u2014" : gini.toFixed(3), spread[0], spread[1]],
    ["Settlers alive", `${population}`,
      state.sawStart
        ? (lost > 0 ? `of ${state.startingPopulation} · ${lost} lost` : `of ${state.startingPopulation}`)
        : "joined mid-episode",
      state.sawStart
        ? (lost > 0 ? `of ${state.startingPopulation} · ${lost} lost` : `of ${state.startingPopulation}`)
        : "joined mid-episode"],
  ];
  if (big) {
    const column = (width - 36) / rows.length;
    rows.forEach(([label, value, , shortNote], index) => {
      const readX = curveX + index * column;
      markup += text(label.toUpperCase(), readX, y + 88, {
        size: T(18), weight: 700, fill: C.muted, spacing: 1.8, outline: 2.6,
      });
      markup += text(value, readX, y + 142, {
        size: T(40), weight: 600, family: F.mono, fill: C.paper,
      });
      markup += text(shortNote, readX, y + 172, { size: T(19), weight: 500, fill: C.dim });
    });
    return markup;
  }
  const readX = curveX + size + 26;
  let readY = curveY + 26;
  for (const [label, value, note] of rows) {
    markup += text(label.toUpperCase(), readX, readY, {
      size: T(18), weight: 700, fill: C.muted, spacing: 1.8, outline: 2.6,
    });
    markup += text(value, readX, readY + T(38), {
      size: T(40), weight: 600, family: F.mono, fill: C.paper,
    });
    markup += text(note, readX, readY + T(62), {
      size: T(19), weight: 500, fill: C.dim,
    });
    readY += 96;
  }
  return markup;
}

/** A designed finish that HOLDS on the last frame: the winner, both scores, the
 *  margin, and a plain-language verdict a non-expert can read. */
function endCard(frame) {
  const rows = ranked(frame);
  const winner = rows[0];
  const runnerUp = rows[1];
  const margin = winner.score - (runnerUp?.score ?? 0);
  const tie = runnerUp && margin === 0;
  const survivors = frame.agents.length;
  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);

  // A match that changed hands and was won from behind is the most interesting
  // thing about it, and the card used to report only the result.
  const leadChanges = events.filter((event) => event.kind === "lead").length;
  const halfway = wealthSeries[Math.floor(wealthSeries.length / 2)];
  const trailedAtHalfway = halfway
    && (halfway.scores[winner.index] ?? 0) < Math.max(...halfway.scores);
  const arc = leadChanges === 0 ? ""
    : trailedAtHalfway
      ? ` Won from behind, after ${leadChanges} lead change${leadChanges === 1 ? "" : "s"}.`
      : ` ${leadChanges} lead change${leadChanges === 1 ? "" : "s"} along the way.`;
  /* THE FINAL SCORE IS THE DISTRIBUTION MATCH.
   *
   * On a v3 world the card used to close on accumulated wealth and a margin over
   * "the field" — with one seat that read "finishes 7,750 ahead of the field — a
   * 100.0% margin", which is a race result for a game that holds no race. The
   * score the episode is actually settled on is the match against the target,
   * and it is the same figure the histogram panel has been showing all along.
   * The actual value of the targeted variable goes beside it, because the match
   * says how close the SHAPE came and not what the world did. */
  const seatScore = frame.coworld?.seats?.find((entry) => entry.seat === winner.index);
  const matched = seatScore && typeof seatScore.score === "number";
  const actual = matched ? targetActual(frame, seatScore.variable) : null;
  const verdict = matched
    ? `${winner.name} scores ${seatScore.score.toFixed(3)} against `
      + `${seatScore.targetId ?? "its target"}`
      + `${actual ? ` — ${actual.label} ${actual.value}` : ""}.`
    : tie
      ? `${winner.name} and ${runnerUp.name} finish level on ${format(winner.score)}.${arc}`
      : (() => {
        const share = ((margin / Math.max(1, winner.score)) * 100).toFixed(1);
        return `${winner.name} finishes ${format(margin)} ahead of `
          + `${runnerUp?.name ?? "the field"} — ${article(share)} ${share}% margin.${arc}`;
      })();
  // Gated, not asserted: the same sentence used to print at any Gini.
  const spread = gini > 0.4
    ? ` A few of them ended up holding almost all the ${resourceName()}.`
    : gini > 0.28
      ? ` The richest of them ended up holding most of the ${resourceName()}.`
      : ` What they held ended up spread fairly evenly.`;
  // "51 of 30 settlers survived" — the old wording assumed a population can only
  // shrink, and this world breeds. Say "grew to" when it did.
  const context = !state.sawStart
    ? `${survivors} settlers still standing.${spread}`
    : survivors > state.startingPopulation
      ? `${survivors} settlers alive, up from ${state.startingPopulation}.${spread}`
      : `${survivors} of ${state.startingPopulation} settlers survived.${spread}`;

  /* The card is SIZED FROM ITS CONTENT.
   *
   * It used to be a fixed 580 units with every baseline hard-coded against that.
   * A two-line verdict — which is what a lively match produces — pushed the
   * second result row and the closing caption straight through the bottom edge,
   * and the dense ramp did it every time. So the wrap is measured first, the
   * plate is sized to hold it, and every baseline is a running cursor. */
  const big = dense();
  const pad = 56;
  const cardW = big ? 1560 : 1180;
  const inner = cardW - pad * 2;
  const nameSize = T(62);
  const verdictSize = T(27);
  const contextSize = T(22);
  const footSize = T(20);
  const verdictLines = wrap(verdict, inner, verdictSize);
  const contextLines = wrap(context, inner, contextSize);
  const rowH = big ? 84 : 66;
  const rowStep = rowH + 12;

  const eyebrowStep = big ? 52 : 40;
  const verdictH = verdictLines.length * verdictSize * 1.3;
  const contextH = contextLines.length * contextSize * 1.34;
  const rowsH = rows.length * rowStep;
  const cardH = Math.min(H - 56, Math.max(big ? 620 : 520,
    52 + eyebrowStep + nameSize * 0.92 + 22 + verdictH + 14 + contextH
    + 34 + rowsH + 34 + footSize * 0.8 + 34));
  const x = (W - cardW) / 2;
  const y = (H - cardH) / 2;

  let markup = `<g class="endcard">`;
  markup += `<rect x="0" y="0" width="${W}" height="${H}" fill="${C.cardScrim}"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" `
    + `fill="${C.card}"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" fill="none" `
    + `stroke="${C.gold}" stroke-width="2.5"/>`;

  let cursor = y + 52;
  markup += text("SUGARSCAPE", x + pad, cursor, {
    size: T(24), weight: 700, fill: C.paper, spacing: big ? 4.2 : 5.0,
  });
  cursor += eyebrowStep;
  markup += eyebrow(tie ? "Final — level" : "Final", x + pad, cursor);

  cursor += nameSize * 0.92;
  markup += seatMark(x + pad + G(12), cursor - nameSize * 0.22, winner.index, G(21));
  markup += text(winner.name, x + pad + G(48), cursor, {
    size: nameSize, weight: 700, fill: C.paper,
  });

  cursor += 22;
  for (const line of verdictLines) {
    cursor += verdictSize * 1.3;
    markup += text(line, x + pad, cursor, { size: verdictSize, weight: 500, fill: C.gold });
  }
  cursor += 14;
  for (const line of contextLines) {
    cursor += contextSize * 1.34;
    markup += text(line, x + pad, cursor, { size: contextSize, weight: 500, fill: C.muted });
  }

  // The rows sit under whatever the sentences needed, and are pushed to the foot
  // when a short verdict leaves the plate at its minimum height.
  const footY = y + cardH - footSize * 0.8 - 26;
  let rowY = Math.max(cursor + 34, footY - footSize - 34 - rowsH);
  for (const [rank, row] of rows.entries()) {
    const leader = rank === 0 && !tie;
    markup += `<rect x="${x + pad}" y="${rowY}" width="${inner}" height="${rowH}" rx="10" `
      + `fill="${C.rowBack}" stroke="${leader ? C.gold : C.border}" stroke-width="${leader ? 2 : 1.4}"/>`;
    markup += text(`${rank + 1}`, x + pad + 36, rowY + rowH * 0.66, {
      size: T(28), weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + pad + G(78), rowY + rowH * 0.5, row.index, G(12));
    markup += text(row.name, x + pad + G(106), rowY + rowH * 0.64, {
      size: T(28), weight: 700, fill: C.paper,
    });
    markup += text(`${row.population} alive`, x + cardW - pad - G(194), rowY + rowH * 0.64, {
      size: T(20), weight: 500, family: F.mono, fill: C.muted, anchor: "end",
    });
    // The result row states the SCORE, and on a v3 world the score is the match,
    // not the pile. Printing accumulated wealth here left the card leading with
    // 0.930 and closing with 7,750 — two different numbers both presented as
    // the result.
    const rowMatch = frame.coworld?.seats?.find((entry) => entry.seat === row.index);
    markup += text(
      rowMatch && typeof rowMatch.score === "number"
        ? rowMatch.score.toFixed(3)
        : format(row.score),
      x + cardW - pad - 36, rowY + rowH * 0.66, {
        size: T(34), weight: 700, family: F.mono, fill: leader ? C.gold : C.paper, anchor: "end",
      });
    rowY += rowStep;
  }
  const scoredCard = frame.coworld?.seats?.some((entry) => typeof entry.score === "number");
  markup += text(
    scoredCard
      ? "Score is how closely the measured distribution matches the target — 1.000 is exact."
      : big
        ? `Score is all the ${resourceName()} still held by living settlers.`
        : `Score is all the ${resourceName()} still held by a population's living settlers.`,
    x + pad, footY, { size: footSize, weight: 500, fill: C.muted });
  markup += `</g>`;
  return markup;
}

function defs() {
  return `<defs>
    <linearGradient id="bug-scrim" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${C.bugScrimTop}"/>
      <stop offset="1" stop-color="${C.bugScrimEnd}"/>
    </linearGradient>
  </defs>
  <style>
    .endcard { animation: endcard-in .55s ease both; }
    @keyframes endcard-in { from { opacity: 0; } to { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) {
      .endcard { animation: none !important; }
    }
  </style>`;
}

/* The overlay is split into two independently-updated layers.
 *
 * This is load-bearing, not an optimisation: replacing an element's markup
 * restarts every CSS animation inside it, so rebuilding the whole overlay on
 * each 33 ms tick pinned the end card at the first frame of its fade and it
 * never became visible. The standings layer changes at timestep boundaries; the
 * beat layer changes only at the end of the episode. Keeping them apart lets the
 * card animate for its full duration.
 *
 * The beat layer now holds ONLY the end card — no plate interrupts mid-episode;
 * see onFrameEntered. It stays its own layer because the split is what makes the
 * card's fade work at all. */
hud.innerHTML = `${defs()}<g id="hud-standings"></g><g id="hud-beats"></g>`;
const standingsLayer = hud.querySelector("#hud-standings");
const beatsLayer = hud.querySelector("#hud-beats");
let standingsSignature = "";
let beatsSignature = "";

function drawBeats(frame) {
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  const full = `${atEnd}|${currentIndex()}`;
  if (full === beatsSignature) return;
  beatsSignature = full;
  beatsLayer.innerHTML = atEnd ? endCard(frame) : "";
  // The scrubber was the only lit object outside the end card's scrim, which
  // read as playback continuing under a final result.
  controls.container.classList.toggle("dimmed", atEnd);
}

function drawHud(frame, index) {
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  const signature = `${index}|${atEnd}`;
  if (signature === standingsSignature) return;
  standingsSignature = signature;

  const railGap = 22;
  /* The rail's three panels, re-proportioned after the transport took its lane.
   *
   * These were tuned against a 936-unit rail; reserving TRANSPORT_H left 832 and
   * the emergence panel absorbed the whole difference, so its Lorenz square and
   * its readouts printed on top of each other. Dense still gives its extra
   * height to the two panels a first-time viewer reads — the race and the beats
   * — and turns the readouts sideways into the strip that is left.
   *
   * The race panel then took a second plot (the headcount, which used to be a
   * banner over the board) and 78 units with it. They come from the emergence
   * panel, whose Lorenz square is sized off its height: sparse still clears the
   * 235 units its two stacked readouts need. Dense cannot pay — at 194 it is
   * already exactly its own content — so there the strip is carved out of the
   * lead plot instead, and the panel keeps its height.
   */
  const raceH = dense() ? 320 : 358;
  const feedH = dense() ? 278 : 250;
  const emergenceH = RAIL.h - raceH - feedH - railGap * 2;
  /* Which world is this?
   *
   * A v3 replay carries a `coworld` block: a target distribution per seat, the
   * histogram the ruleset actually grew, and a running match score. That is the
   * whole of what v3 scores, and none of it is a race — so the rail asks its
   * question instead of the race's. A v1 replay has no such block and keeps the
   * race band and the Lorenz panel, which are the right readouts for THAT game.
   * The feed sits between them either way: "what just happened" is true of both.
   */
  const scored = Array.isArray(frame.coworld?.seats) && frame.coworld.seats.length > 0;
  /* Below the headline panel sit the two readouts that mean something in ANY
   * episode, rather than two that only mean something in this one.
   *
   * What it grew, how unequal it got, how it converged — and all three are
   * TIME SERIES on the same axis, so the rail reads as one episode rather than
   * as three unrelated instruments.
   *
   * What each replaced, and why: the event feed narrated what had just happened,
   * which is a broadcast job rather than a research one. The match-score plot
   * only meant anything in a targeted run and drew a flat line near the top
   * whenever the ruleset was already good. The Lorenz-and-Gini panel was
   * rejected outright — it printed "53 of 30 settlers" and asked the viewer to
   * already know what a Lorenz curve is; inequality over time says the thing
   * that panel was reaching for and says it plainly.
   */
  let markup = scored
    ? targetHistogram(frame, RAIL.x, RAIL.y, RAIL.w, raceH)
    : raceChart(frame, RAIL.x, RAIL.y, RAIL.w, raceH);
  markup += inequalityOverTime(frame, RAIL.x, RAIL.y + raceH + railGap, RAIL.w, feedH);
  markup += tribeShares(frame, RAIL.x, RAIL.y + raceH + feedH + railGap * 2, RAIL.w, emergenceH);
  markup += scorebug(frame);
  markup += boardKey(frame);
  standingsLayer.innerHTML = markup;
  if (fillTargetPicker(frame)) placeTargetPicker();
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

let lastTick = 0;

/* THE TARGET PICKER.
 *
 * Populated once per replay from the catalog the converter embedded, and placed
 * over the histogram panel by transforming the panel's own stage coordinates
 * through the SVG's screen matrix. Percentages would drift the moment the stage
 * stopped being exactly 16:9; the matrix is what the SVG is actually using.
 */
const targetPick = document.getElementById("target-pick");
const targetSelect = document.getElementById("target-select");
const stageEl = document.getElementById("stage");
let targetOptionsKey = "";

function fillTargetPicker(frame) {
  const choices = frame.coworld?.choices ?? [];
  if (choices.length === 0) {
    targetPick.hidden = true;
    return false;
  }
  const key = choices.map((choice) => choice.id).join("|");
  if (key !== targetOptionsKey) {
    targetOptionsKey = key;
    targetSelect.innerHTML = choices.map((choice) => {
      const label = choice.assigned ? `${choice.id} (assigned)` : choice.id;
      // A target measured on a variable this episode never sampled cannot be
      // scored, and is offered disabled rather than silently absent.
      const dead = choice.score === null || choice.score === undefined;
      return `<option value="${choice.id}"${choice.assigned ? " selected" : ""}`
        + `${dead ? " disabled" : ""}>${label}${dead ? " — not measured" : ""}</option>`;
    }).join("");
    if (!targetChoice) {
      const assigned = choices.find((choice) => choice.assigned);
      targetChoice = assigned ? assigned.id : choices[0].id;
    }
    targetSelect.value = targetChoice;
  }
  targetPick.hidden = false;
  return true;
}

function placeTargetPicker() {
  if (targetPick.hidden) return;
  const matrix = hud.getScreenCTM();
  const stageBox = stageEl.getBoundingClientRect();
  if (!matrix) return;
  const at = (x, y) => ({
    left: matrix.a * x + matrix.c * y + matrix.e - stageBox.left,
    top: matrix.b * x + matrix.d * y + matrix.f - stageBox.top,
  });
  // BELOW the heading, not on it. The panel's title is a long left-aligned
  // question and the picker is right-aligned, so sharing that row printed the
  // menu straight through "DID THE RULES GROW THE TARGET?". The row under it is
  // clear on the right — the score and its labels are all left-aligned.
  const corner = at(RAIL.x + RAIL.w - 18, RAIL.y + (dense() ? 58 : 40));
  targetPick.style.right = `${Math.round(stageBox.width - corner.left)}px`;
  targetPick.style.top = `${Math.round(corner.top)}px`;
  targetPick.style.left = "auto";
}

targetSelect.addEventListener("change", () => {
  targetChoice = targetSelect.value;
  // The rail is signature-cached, so force the redraw rather than waiting for a
  // timestep boundary that may never come while paused.
  standingsSignature = "";
  const frame = frames[currentIndex()];
  if (frame) drawHud(frame, currentIndex());
});

const commentary = document.getElementById("commentary");
const verdictLine = document.getElementById("verdict");
let spokenKey = "";
let spokenVerdict = false;
let spokenLegend = false;
let markedLeads = -1;

/** Say what the picture shows, at a pace a screen reader can actually consume.
 *
 *  Announcing the full standing on every timestep - one every 770ms at 1x, and
 *  forever, because the replay loops - queues minutes behind and clips
 *  continuously. So this speaks on BEATS: when a settler dies, when the lead
 *  changes, at the quarter marks, and at the finish. The picture is hidden from
 *  assistive technology, so this text is the whole broadcast and it has to carry
 *  everything the panels do, not a subset of it. */
function speak(frame) {
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  /* A stream that stopped short is the loudest thing on the picture and used to
   * be SILENT here. The scorebug prints CUT SHORT in the loss colour and a
   * second line saying why; speak() had no branch for it, and because a
   * truncated stream never sets `finished`, the assertive verdict never fired
   * either. An assistive-technology user got an ordinary running commentary
   * that simply stopped. */
  if (state.truncated && currentIndex() >= frames.length - 1) {
    if (spokenVerdict) return;
    spokenVerdict = true;
    commentary.textContent = "";
    verdictLine.textContent =
      `This episode was cut short at timestep ${frames.at(-1).timestep} of `
      + `${state.maxTimestep || frames.at(-1).timestep}. There is no result. `
      + `${standingSentence(frame)}`;
    return;
  }
  if (atEnd) {
    if (spokenVerdict) return;
    spokenVerdict = true;
    commentary.textContent = "";
    const rows = ranked(frame);
    const margin = rows[0].score - (rows[1]?.score ?? 0);
    const changes = events.filter((event) => event.kind === "lead").length;
    const share = ((margin / Math.max(1, rows[0].score)) * 100).toFixed(1);
    const stats = frame.stats ?? {};
    const gini = Number(stats.giniCoefficient ?? 0);
    // Carry what the CARD carries: the margin as a share, the arc, and the
    // plain-language spread — the card's whole point is that a Gini is not a
    // sentence, and speaking the bare coefficient threw that away.
    verdictLine.textContent = (margin === 0
      ? `Final. ${rows.map((row) => row.name).join(" and ")} finish level on `
        + `${format(rows[0].score)} ${resourceName()}.`
      : `Final. ${rows[0].name} wins with ${format(rows[0].score)} ${resourceName()}, `
        + `${format(margin)} ahead of ${rows[1]?.name ?? "the field"} — `
        + `${article(share)} ${share} percent margin.`)
      + (state.sawStart
      ? ` ${frame.agents.length} of ${state.startingPopulation} settlers survived,`
      : ` ${frame.agents.length} settlers still standing,`)
      + ` after ${changes} lead change${changes === 1 ? "" : "s"}.`
      + ` ${spreadSentence(frame, gini)}`
      + ` Score is all the ${resourceName()} still held by a population's living settlers.`;
    return;
  }
  spokenVerdict = false;
  verdictLine.textContent = "";

  const beat = [...events].reverse().find((event) => event.timestep <= frame.timestep);
  const beatKey = beat ? `${beat.index}:${beat.kind}` : "none";
  const quarter = Math.floor((frame.timestep / Math.max(1, state.maxTimestep)) * 4);
  const key = `${beatKey}|${quarter}`;
  if (key === spokenKey) return;
  spokenKey = key;

  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);
  const standing = standingSentence(frame).replace(/\.$/, "");
  const beatText = !beat ? ""
    : beat.kind === "lead" ? ` At timestep ${beat.timestep}, ${beat.name} took the lead.`
      : ` At timestep ${beat.timestep}, ${beat.count} settler`
        + `${beat.count === 1 ? "" : "s"} ${beat.cause ?? "lost"}.`;
  const changes = events.filter((event) => event.timestep <= frame.timestep
    && event.kind === "lead").length;
  const lost = state.startingPopulation - frame.agents.length;
  commentary.textContent = `Timestep ${frame.timestep} of ${state.maxTimestep || frame.timestep}.`
    + ` ${standing}.${beatText}`
    + ` ${changes} lead change${changes === 1 ? "" : "s"} so far.`
    + (state.sawStart
      ? ` ${frame.agents.length} settlers alive of ${state.startingPopulation}, ${lost} lost.`
      : ` ${frame.agents.length} settlers alive.`)
    + (joinedLate()
      ? ` This stream was joined at timestep ${frames[0].timestep};`
        + " earlier timesteps were not delivered."
      : "")
    + ` Inequality, as a Gini coefficient, ${gini.toFixed(3)}: `
    + `${spreadSentence(frame, gini).replace(/^./, (c) => c.toLowerCase())}`
    // Said ONCE, on the first announcement. It was appended to every one of
    // them, so a screen-reader user heard the same static sentence after every
    // beat for the length of the episode, and again on every loop.
    + (spokenLegend ? "" : (spokenLegend = true,
      " A hollow settler has less than one timestep of food left."));
}

/** The standing, as a sentence. One source, so the running commentary and the
 *  cut-short notice cannot describe the same frame differently. */
function standingSentence(frame) {
  return ranked(frame)
    .map((row, rank) => `${rank + 1}. ${row.name}, ${format(row.score)} ${resourceName()},`
      + ` ${row.population} settler${row.population === 1 ? "" : "s"}`)
    .join(". ") + ".";
}

/** The inequality reading in words rather than as a coefficient — the whole
 *  point of the panel, and it was being spoken as a bare number. */
function spreadSentence(frame, gini) {
  if (frame.agents.length === 0) return "No settlers are left.";
  if (wealthTotal(frame) === 0) return "None of them hold anything.";
  if (gini > 0.4) return `A few of them hold almost all the ${resourceName()}.`;
  if (gini > 0.28) return `The richest of them hold most of the ${resourceName()}.`;
  return "What they hold is spread fairly evenly.";
}

function currentIndex() {
  return Math.max(0, Math.min(frames.length - 1, Math.floor(state.cursor)));
}

/* The transport speaks in TIMESTEPS, not frame indices.
 *
 * The range used to carry indices while its aria-valuetext announced timesteps,
 * so anything that fell back to valuenow/valuemax - and plenty does - read a
 * different number from the one being spoken, on a control whose whole job is to
 * say where you are. The two axes are not interchangeable either: a recording
 * that skips, or a live spectator who joined at t40, has frame 0 at a timestep
 * that is not zero. So the range's own min/max/value are timesteps and the
 * played track is measured on the same axis. */
function syncScrub() {
  if (frames.length === 0) return;
  controls.scrub.min = String(frames[0].timestep);
  controls.scrub.max = String(frames.at(-1).timestep);
}

function played(index) {
  const first = frames[0]?.timestep ?? 0;
  const last = frames.at(-1)?.timestep ?? first;
  const span = Math.max(1, last - first);
  return Math.min(1, Math.max(0, ((frames[index]?.timestep ?? first) - first) / span));
}

/** The nearest recorded frame to a timestep. Nearest, not exact: a recording is
 *  allowed to skip, and the range steps by one. */
function indexOfTimestep(timestep) {
  const exact = frameIndexByTimestep.get(timestep);
  if (exact !== undefined) return exact;
  let best = 0;
  let bestGap = Infinity;
  for (let index = 0; index < frames.length; index += 1) {
    const gap = Math.abs(frames[index].timestep - timestep);
    if (gap < bestGap) {
      bestGap = gap;
      best = index;
    }
  }
  return best;
}

function onFrameEntered(index, now) {
  const frame = frames[index];
  if (!frame) return;

  const cell = BOARD.w / frame.width;
  for (const event of events) {
    if (event.index !== index) continue;
    if (event.kind === "death" && !reducedMotion) {
      for (const agent of event.agents) {
        const position = cellPosition(frame, agent.cell);
        motes.push({
          px: BOARD.x + (position.x + 0.5) * cell,
          py: BOARD.y + (position.y + 0.5) * cell,
          born: now,
        });
      }
    }
    /* NOTHING interrupts the board any more.
     *
     * A die-off went first: it earned a plate over the middle of the lattice
     * once three settlers went at once, which on the shipped config is most
     * timesteps, so the banner was up more often than it was down. The lead
     * change outlived it and then failed the same test — owner call, on a plate
     * covering roughly a third of the board.
     *
     * Neither reading is lost, because neither plate was ever the only place it
     * was said. A lead change is a marked step in the lead band, a row in the
     * feed ("takes the lead"), the running count over the race panel, and a
     * clause on the end card; a die-off is the settler strip, the death rings
     * and its own feed row. The plates were the fourth telling, and the only
     * one that charged the board for it. */
  }
}

function tick() {
  const now = performance.now();
  const elapsed = Math.min(200, now - lastTick);
  lastTick = now;
  if (frames.length === 0) return;

  if (state.playing) {
    if (state.live) {
      state.cursor = frames.length - 1;
    } else {
      state.cursor += elapsed / frameDwellMs(state.speed);
      if (state.cursor >= frames.length - 1) {
        state.cursor = frames.length - 1;
        if (state.finished) {
          // Hold the end card, then loop — the replay contract expects looping.
          if (!state.holdUntil) state.holdUntil = now + 5200;
          else if (now > state.holdUntil) { state.holdUntil = 0; state.cursor = 0; }
        }
      }
    }
  }

  measureDensity();

  const index = currentIndex();
  if (index !== state.lastDrawnIndex) {
    state.lastDrawnIndex = index;
    onFrameEntered(index, now);
    controls.scrub.value = String(frames[index].timestep);
    controls.scrub.style.setProperty("--played", `${played(index) * 100}%`);
    // Mark the lead changes on the timeline itself, so the shape of the match is
    // visible from the transport and not only from the chart.
    if (markedLeads !== events.length) {
      markedLeads = events.length;
      const marks = events
        .filter((event) => event.kind === "lead")
        .map((event) => played(event.index) * 100);
      controls.scrub.style.setProperty("--marks", marks.length === 0
        ? "none"
        // INK, not gold. The marks were stacked over the gold played fill in the
        // same gold, so every lead change went invisible at the instant the
        // cursor passed it - the only ones you could see were the ones that had
        // not happened yet. Ink reads on the gold fill AND on the track bed.
        : marks.map((at) => `linear-gradient(${C.ink}, ${C.ink}) ${at}% 0 / 3px 100% no-repeat`)
          .join(", "));
    }
    // A bare "62" tells a screen-reader user nothing; name the unit and the end.
    // The range's OWN min/max/value are timesteps too (see syncScrub) — they used
    // to be frame indices, so any assistive technology that fell back to
    // valuenow read a different number from the one valuetext announced.
    controls.scrub.setAttribute(
      "aria-valuetext",
      `timestep ${frames[index].timestep} of `
      + `${state.maxTimestep || frames.at(-1).timestep}`,
    );
  }

  const frame = frames[index];
  const previous = index > 0 ? frames[index - 1] : null;
  const fraction = Math.max(0, Math.min(1, state.cursor - index));

  // The engine moves an agent and THEN lets it collect, so the cell it emptied
  // must not empty until it arrives. Painting frame N's terrain while the
  // settlers were still walking in from N-1 made sugar vanish from cells nobody
  // was standing on yet, a full beat ahead of the cause.
  // "Settled" means the settlers have arrived, so the lattice, the standings and
  // the commentary all describe the same instant. A cursor at rest - paused,
  // scrubbed, or held on the final frame - is always settled; only a walk in
  // progress shows the state they are leaving.
  const settled = !previous || reducedMotion || !state.playing
    || fraction >= 0.88 || index >= frames.length - 1;
  const terrainFrame = settled ? frame : previous;
  if (terrainFrame !== terrainShown) {
    // Dissolve only while the replay is running. A scrub, a step, a pause or a
    // reduced-motion viewer wants the state it asked for, at once, not a plate
    // caught between two timesteps; and the first plate of a stream has nothing
    // to dissolve from.
    showTerrain(terrainFrame, terrainShown !== null && state.playing && !reducedMotion, now);
  } else if (terrainFrom || driftAt(now) !== terrainPainted) {
    // Between timesteps the plate still moves — the sand goes on blowing whether
    // or not the replay is running — and a dissolve in flight still has slices to
    // let go of. With the wind off, driftAt is a constant and neither fires.
    paintTerrain(now);
  }
  // Interpolate from the PREVIOUS frame into this one, so the settler arrives
  // exactly as its recorded state lands rather than leaving it early.
  drawBoard(frame, previous, previous && !reducedMotion ? fraction : 1, now);
  // The HUD reads the same frame the board is showing. Rendering frame N's
  // scores while the settlers were still walking in from N-1 put the clock, the
  // harvested lattice and the scoreboard a full timestep ahead of the bodies.
  drawHud(terrainFrame, settled ? index : index - 1);
  drawBeats(frame);
  speak(terrainFrame);
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

function setPlaying(playing) {
  state.playing = playing;
  controls.glyph.textContent = playing ? "❚❚" : "▶";
  controls.play.setAttribute("aria-label", playing ? "Pause" : "Play");
}

function seek(index) {
  setPlaying(false);
  state.live = false;
  state.holdUntil = 0;
  state.cursor = Math.max(0, Math.min(frames.length - 1, index));
}

controls.play.addEventListener("click", () => {
  if (!state.playing && state.cursor >= frames.length - 1 && state.finished) state.cursor = 0;
  state.holdUntil = 0;
  setPlaying(!state.playing);
});
controls.back.addEventListener("click", () => seek(Math.floor(state.cursor) - 1));
controls.forward.addEventListener("click", () => seek(Math.floor(state.cursor) + 1));
controls.scrub.addEventListener("input", () => seek(indexOfTimestep(Number(controls.scrub.value))));
controls.text.addEventListener("click", () => setLargeText(!state.largeText));
controls.speed.addEventListener("click", () => {
  state.speed = SPEEDS[(SPEEDS.indexOf(state.speed) + 1) % SPEEDS.length];
  controls.speed.innerHTML = `${state.speed}&times;`;
  // The label has to carry the VALUE: an aria-label overrides the visible "2x",
  // so a static one would leave the current speed unannounced.
  controls.speed.setAttribute("aria-label", `Playback speed, ${state.speed}×`);
});

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

/** Show a failure, and take the transport away with it: leaving a pause glyph
 *  and a filled scrubber on screen told the viewer a replay was playing while
 *  the message said none had loaded. */
function fail(message, detail = "") {
  const shown = detail.length > 96 ? `${detail.slice(0, 93)}…` : detail;
  notice.innerHTML = escapeText(message)
    + (shown ? ` <code>${escapeText(shown)}</code>` : "")
    + '<span class="hint">Reload to try again.</span>';
  // KEEP the transport if there is anything to play.
  //
  // It used to be hidden unconditionally, and only ready() restores it - which
  // fires once, on the first frame. So a server that bumped its format at frame
  // 50 of 100 left the board auto-playing behind the notice with no play, no
  // scrub, no step and no way back: fifty good frames still on screen and no
  // longer watchable. A failure with frames in hand is a failure of the STREAM,
  // not of the recording.
  if (frames.length > 0) return;
  // Nothing to play. Take the transport away and MOVE THE FOCUS with it. A
  // keyboard user standing on the play button when the stream died was left
  // focused on an element that had just been hidden: the focus ring vanished,
  // tabbing restarted from the top of the document, and the message that had
  // replaced the controls was never reached. role="alert" announces it; this
  // makes it findable.
  const hadFocus = controls.container.contains(document.activeElement);
  controls.container.hidden = true;
  if (hadFocus || document.activeElement === document.body) notice.focus();
}

function ready() {
  notice.textContent = "";
  controls.container.hidden = false;
}

/** Derive the spectator socket from the page's OWN path. The Observatory serves
 *  this document at `<prefix>/client/replay` through the k8s proxy, where the
 *  sibling socket is `<prefix>/replay` — an absolute `/replay` would resolve off
 *  the prefix and black-screen the embed. */
function socketUrl() {
  const path = location.pathname.replace(/\/+$/, "");
  const match = /^(.*)\/clients?\/(replay|global)$/.exec(path);
  // Falling back to an absolute "/global" would resolve off the proxy prefix -
  // the exact black screen this function exists to prevent - so an unrecognised
  // path resolves the sibling RELATIVE to wherever the document actually is.
  const suffix = match
    ? `${match[1]}/${match[2]}`
    : new URL("global", new URL(".", location.href)).pathname;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}${suffix}`;
}

function connect() {
  let socket;
  try {
    socket = new WebSocket(socketUrl());
  } catch (error) {
    fail("Could not open the spectator socket for this episode.");
    return;
  }
  let idleTimer = 0;
  /** An episode is over when the stream has reached the timestep the RULES
   *  schedule - never merely because it went quiet, and never merely because
   *  the socket closed. A live match spends seconds per timestep waiting on
   *  policy decisions (6.4s on the shipped config), so a silence heuristic
   *  declared FINAL after frame zero and reset the cursor forever. And a
   *  stream cut short mid-delivery would name whoever happened to be ahead as
   *  the winner - on the reference replay, cutting at frame 50 crowned the
   *  population that actually loses by 81. */
  // The server stamps `final` on the last frame it will ever send, which is the
  // only way to know an episode ended by EXTINCTION: that stops the run loop
  // early, writes the results, and then just goes quiet, so a viewer waiting for
  // maxTimestep sat pinned in live mode forever with a progress percentage on a
  // match that was over. maxTimestep stays as the fallback for a server too old
  // to stamp it.
  const complete = () => frames.length > 0
    && (frames.at(-1).final === true
      || (state.maxTimestep > 0 && frames.at(-1).timestep >= state.maxTimestep));
  // A socket can open and never speak - an episode with no recorded frames does
  // exactly that. Without this the canvas is never touched and the embed is the
  // ground colour, forever, with nothing said.
  const silence = setTimeout(() => {
    if (frames.length === 0) {
      fail("This episode is not sending any frames to replay.");
    }
  }, 12000);
  const markFinished = () => {
    if (frames.length === 0) return;
    state.live = false;
    if (complete()) {
      state.finished = true;
      state.truncated = false;
      return;
    }
    // Everything that arrived stays watchable; only the verdict is withheld.
    state.truncated = true;
    state.finished = false;
  };
  // Not on open: a socket that connects and then fails to deliver anything
  // would show a lit play button and a scrubber over an empty board.
  socket.addEventListener("open", () => { notice.textContent = ""; });
  socket.addEventListener("message", (event) => {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch (error) {
      fail("The episode stream sent a frame this viewer could not read.");
      return;
    }
    // Clear the silence timer for a REJECTED frame too. It only cleared on the
    // accepted path, so twelve seconds after telling an operator exactly which
    // format it could not read, the viewer replaced that with "not sending any
    // frames" - while five a second were arriving and being discarded. The
    // comment on isRenderableFrame claims this was fixed; it was not, only
    // delayed.
    clearTimeout(silence);
    if (!isRenderableFrame(frame)) return;
    if (frames.length === 0) { state.live = true; ready(); }
    recordFrame(frame);
    // The server streams recorded frames back to back and then goes quiet; a
    // pause means the episode is over and playback should own the timeline.
    clearTimeout(idleTimer);
    // Only a stream that has reached the scheduled end can settle into
    // playback; a quiet live match is still a live match.
    idleTimer = setTimeout(() => {
      if (!complete()) return;
      markFinished();
      state.cursor = 0;
      setPlaying(!reducedMotion);
    }, 1200);
  });
  socket.addEventListener("close", () => {
    clearTimeout(idleTimer);
    clearTimeout(silence);
    if (frames.length === 0) {
      fail("The episode stream closed before sending any frames.");
      return;
    }
    markFinished();
  });
  socket.addEventListener("error", () => {
    if (frames.length === 0) {
      fail("Could not reach the episode stream for this replay.");
    }
  });
}

/** Load a `sugarscape.replay.v1` artifact named by `?replay=`. Nothing in the
 *  viewer needs the game container on this path. */
/* A v3 RECORDING, TURNED INTO FRAMES, IN THE BROWSER.
 *
 * This viewer renders whole frames: every cell and every settler, per timestep.
 * A v3 recording is deltas against an initial state, plus a header. The two are
 * far closer than that makes them sound, which is why this is a conversion and
 * not a second renderer:
 *
 *   - both index cells `x * height + y`, so the lattice maps across untransposed;
 *   - v3's cell row [sugar, spice, pollution, maxSugar, maxSpice] is a SUPERSET
 *     of the [sugar, spice, pollution] this viewer reads — a prefix, not a
 *     translation;
 *   - v3 embeds the same DTL simulation, so each frame's runtimeStats already
 *     carries the exact keys this viewer wants (giniCoefficient, the four death
 *     counters, tradeVolume, meanTradePrice, largestTribeSize).
 *
 * The one thing that does NOT survive is per-agent stock: v3 records wealth in
 * WEALTH_QUANTUM-sized presentation buckets. Every frame says so, and the
 * viewer's "about to starve" test stands down rather than comparing a 50-unit
 * bucket against a metabolism of 1-4 (see `quantised`).
 */
const V3_WEALTH_QUANTUM = 50;

/* THE WHOLE TARGET CATALOG, SCORED IN THE BROWSER.
 *
 * An episode is assigned one target, but the engine measures every variable in
 * the catalog each tick regardless, and records them all (see `measured` on the
 * frames). So any target can be asked of any run — a genuinely different
 * question from the one the episode was scored on, and the reason the selector
 * exists.
 *
 * Scoring therefore has to happen here, which is a fidelity hazard: a viewer
 * that computes a score slightly differently from the engine would quietly
 * disagree with the number the episode was actually judged on. So this is a
 * faithful port of coworld/scoring.py — `1 - normalized_W1`, the Wasserstein-1
 * distance between the two cumulative histograms, weighted by bin width and
 * divided by the support width — and tools/test_replay_viewer.py pins it against
 * scores the ENGINE produced, not against itself.
 */
const TARGET_CATALOG = JSON.parse("{{TARGETS_JSON}}" || "[]");

function scoreAgainst(target, measured) {
  if (!measured || !measured.probs || measured.probs.length === 0) return null;
  const bins = target.bins ?? [];
  if (bins.length !== (measured.bins ?? []).length) return null;
  for (let i = 0; i < bins.length; i += 1) if (bins[i] !== measured.bins[i]) return null;
  const probs = target.probs ?? [];
  let carried = 0;
  let distance = 0;
  for (let i = 0; i < probs.length; i += 1) {
    carried += (measured.probs[i] ?? 0) - probs[i];
    distance += Math.abs(carried) * (bins[i + 1] - bins[i]);
  }
  const support = bins[bins.length - 1] - bins[0];
  if (!(support > 0)) return null;
  return Math.max(0, Math.min(1, 1 - distance / support));
}

function targetChoices(header, measuredNow) {
  const assigned = new Set((header.targets ?? []).map((target) => target.id));
  return TARGET_CATALOG.map((target) => {
    const measured = measuredNow.get(target.variable);
    return {
      id: target.id,
      variable: target.variable,
      assigned: assigned.has(target.id),
      bins: target.bins ?? [],
      targetProbs: target.probs ?? [],
      measuredProbs: measured?.probs ?? [],
      sampleCount: measured?.sample_count ?? 0,
      score: scoreAgainst(target, measured),
    };
  });
}

function v3ToReplay(document_) {
  const header = document_.header;
  const grid = header.initial_grid;
  const width = grid.width;
  const height = grid.height;
  const cells = grid.cells.map((cell) => cell.slice(0, 3));
  let maxSugar = 0;
  let maxSpice = 0;
  for (const cell of grid.cells) {
    maxSugar = Math.max(maxSugar, cell[3] ?? 0);
    maxSpice = Math.max(maxSpice, cell[4] ?? 0);
  }
  // roster: [id, seat, born, sex01, vision, movement, mSugar, mSpice, maxAge]
  const roster = new Map(header.roster.map((row) => [row[0], row]));
  // live:   [id, x, y, sugarBucket, spiceBucket, tribe, diseases]
  const live = new Map(header.initial_agents.map((row) => [row[0], row.slice()]));
  const players = header.config?.players ?? [];
  const seatCount = Math.max(1, (header.targets ?? []).length);
  const slots = [];
  for (let seat = 0; seat < seatCount; seat += 1) {
    slots.push({ name: players[seat]?.name || `Seat ${seat + 1}`, decisionModels: [] });
  }
  const scheduled = Number(header.config?.timesteps ?? document_.frames.length);
  const startingAgents = header.initial_agents.length;

  const latest = new Map();      // seat -> newest running score
  const measuredNow = new Map(); // variable -> newest measured histogram

  const coworld = () => {
    const seats = (header.targets ?? []).map((target, seat) => {
      const reading = latest.get(seat) ?? {};
      const histogram = reading.histogram ?? {};
      return {
        seat,
        name: slots[seat % slots.length].name,
        targetId: target.id,
        variable: target.variable,
        bins: target.bins ?? [],
        targetProbs: target.probs ?? [],
        measuredProbs: histogram.probs ?? [],
        sampleCount: histogram.sample_count ?? 0,
        measured: Boolean(histogram.probs),
        score: reading.score,
        assigned: true,
      };
    });
    return { seats, choices: targetChoices(header, measuredNow), finalScores: header.scores ?? [] };
  };

  const materialise = (timestep, stats, final) => {
    const agents = [];
    for (const id of [...live.keys()].sort((a, b) => a - b)) {
      const dynamic = live.get(id);
      const stat = roster.get(id) ?? [id, 0, 0, 0, 0, 0, 0, 0, -1];
      agents.push({
        id,
        cell: dynamic[1] * height + dynamic[2],
        slot: stat[1],
        decisionModel: slots[stat[1] % slots.length].name,
        age: Math.max(0, timestep - stat[2]),
        sugar: dynamic[3],
        spice: dynamic[4],
        sugarMetabolism: stat[6],
        spiceMetabolism: stat[7],
        vision: stat[4],
        movement: stat[5],
        depressed: false,
        sick: Boolean(dynamic[6]),
        tribe: dynamic[5],
      });
    }
    return {
      format: "sugarscape.frame.v1",
      timestep,
      maxTimestep: scheduled,
      environmentMaxSugar: maxSugar,
      environmentMaxSpice: maxSpice,
      startingAgents,
      wealthQuantum: V3_WEALTH_QUANTUM,
      width,
      height,
      cells: cells.map((cell) => cell.slice()),
      agents,
      links: [],
      slots,
      stats,
      final,
      coworld: coworld(),
    };
  };

  const statsFrom = (runtime, timestep) => {
    const out = Object.assign({ timestep, population: live.size }, runtime || {});
    for (const key of ["giniCoefficient", "agentStarvationDeaths", "agentAgingDeaths",
      "agentCombatDeaths", "agentDiseaseDeaths"]) {
      if (out[key] === undefined) out[key] = 0;
    }
    return out;
  };

  const frames = [materialise(0, statsFrom({}, 0), false)];
  document_.frames.forEach((frame, position) => {
    for (const [index, sugar, spice, pollution] of frame.cell_deltas) {
      cells[index] = [sugar, spice, pollution];
    }
    const deltas = frame.agent_deltas;
    for (const row of deltas.births) roster.set(row[0], row);
    for (const row of deltas.upsert) live.set(row[0], row.slice());
    for (const id of deltas.remove) live.delete(id);
    for (const reading of frame.running ?? []) latest.set(reading.seat, reading);
    for (const [variable, histogram] of Object.entries(frame.measured ?? {})) {
      measuredNow.set(variable, histogram);
    }
    frames.push(materialise(
      frame.timestep,
      statsFrom(frame.runtimeStats, frame.timestep),
      position === document_.frames.length - 1,
    ));
  });

  return { format: "sugarscape.replay.v1", config: header.config, frames };
}

/** Inflate a deflate-compressed recording. v3 writes them compressed; the
 *  Observatory hands the same bytes over postMessage. */
async function inflateReplay(bytes) {
  if (!("DecompressionStream" in window)) {
    throw new Error("This browser cannot decompress replays (DecompressionStream).");
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Bytes in, playable replay out, whichever generation recorded them. */
async function replayFromBytes(bytes) {
  let text;
  try {
    text = new TextDecoder().decode(await inflateReplay(bytes));
  } catch (error) {
    // Not compressed: a v1 recording is plain JSON on disk.
    text = new TextDecoder().decode(bytes);
  }
  const parsed = JSON.parse(text);
  if (parsed.format === "sugarscape.replay.v3") {
    if (parsed.version !== 2) {
      throw new Error(
        `This replay was recorded in format version ${parsed.version}; this viewer plays version 2.`,
      );
    }
    return v3ToReplay(parsed);
  }
  return parsed;
}

/** The Observatory embeds this in a sandboxed iframe and posts the bytes in
 *  rather than serving them, so the same path has to accept both. */
async function loadReplayBytes(bytes) {
  let payload;
  try {
    payload = await replayFromBytes(bytes);
  } catch (error) {
    fail(error.message || "Could not read this replay.");
    return;
  }
  await adoptReplay(payload, "postMessage");
}

async function loadArtifact(url) {
  let payload;
  try {
    const response = await fetch(url, { mode: "cors" });
    if (!response.ok) throw new Error(String(response.status));
    payload = await replayFromBytes(new Uint8Array(await response.arrayBuffer()));
  } catch (error) {
    fail("Could not load this replay.", url);
    return;
  }
  await adoptReplay(payload, url);
}

/** Take a validated replay and put it on the stage. Split out of loadArtifact so
 *  the fetch path and the postMessage path cannot drift in their validation —
 *  the socket path's guards were once missing from the artifact path entirely. */
async function adoptReplay(payload, url) {
  if (!payload || payload.format !== "sugarscape.replay.v1" || !Array.isArray(payload.frames)) {
    fail("That file is not a Sugarscape recording this viewer can read.", url);
    return;
  }
  if (payload.frames.length === 0) {
    fail("This replay recorded no frames.");
    return;
  }
  const scheduled = Number(payload.config?.timesteps ?? 0);
  if (scheduled > 0) state.maxTimestep = scheduled;
  // The config carries the world's true scale, so the ramp does not depend on
  // which frames happen to be in hand.
  const configuredSugar = Number(payload.config?.environmentMaxSugar ?? 0);
  const configuredSpice = Number(payload.config?.environmentMaxSpice ?? 0);
  if (configuredSugar > 0) state.maxSugar = configuredSugar;
  if (configuredSpice > 0) state.maxSpice = configuredSpice;
  const configuredAgents = Number(payload.config?.startingAgents ?? 0);
  if (configuredAgents > 0) {
    state.startingPopulation = configuredAgents;
    state.sawStart = true;
  }
  // VALIDATE EVERY FRAME. This path used to check the envelope and then hand the
  // frames straight to recordFrame, so the socket path's entire guard was simply
  // absent from the documented alternative: one malformed frame gave a
  // ground-coloured stage, no message, no controls, and a TypeError every 16 ms
  // for the life of the tab. isRenderableFrame says which way it was unusable.
  const usable = [];
  for (const frame of payload.frames) {
    if (!isRenderableFrame(frame)) break;
    usable.push(frame);
  }
  if (usable.length === 0) {
    // isRenderableFrame has already put the specific reason on screen.
    if (!rejectedFormat && !rejectedShape) fail("This replay has no frames this viewer can read.", url);
    return;
  }
  for (const frame of usable) recordFrame(frame);
  ready();
  // A recording that goes bad partway is still watchable up to that point, and
  // saying so is better than throwing the whole thing away — but it must not be
  // crowned, for the same reason a truncated stream is not.
  if (usable.length < payload.frames.length) {
    state.truncated = true;
    state.finished = false;
  } else {
    state.finished = true;
  }
  state.live = false;
  state.cursor = 0;
  setPlaying(!reducedMotion);
}

async function boot() {
  setPlaying(!reducedMotion);
  let remembered = false;
  try {
    remembered = sessionStorage.getItem(LARGE_TEXT) === "1";
  } catch (error) {
    // Storage denied by the embed's sandbox; start from the default.
  }
  setLargeText(remembered);
  // Before anything draws: BOARD and RAIL are computed, not constant, and the
  // first frame must not be laid out against zeroes.
  measureDensity();
  lastTick = performance.now();
  // A timer, not requestAnimationFrame: a backgrounded or headless tab throttles
  // rAF to a few frames a second and starves the interpolation. 16ms rather
  // than 33 because settlers jump several cells per timestep, and at 30fps that
  // motion reads as stepping rather than moving; the terrain is cached now, so
  // the extra draws are cheap.
  setInterval(tick, 16);

  const params = new URLSearchParams(location.search);
  // The Observatory embeds this behind a proxy and strips its own chrome.
  if (params.get("chrome") === "off") document.body.classList.add("chrome-off");
  // Bytes may be POSTED in rather than served, when the embedder already holds
  // them and the iframe cannot reach the artifact store.
  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "coworld-replay") return;
    const value = event.data.bytes;
    let bytes;
    if (value instanceof ArrayBuffer) bytes = new Uint8Array(value);
    else if (ArrayBuffer.isView(value)) bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    else { fail("postMessage replay bytes must be an ArrayBuffer or typed array."); return; }
    loadReplayBytes(bytes).catch(() => fail("Could not read the posted replay."));
  });
  const replay = params.get("replay");
  if (replay) await loadArtifact(replay);
  else if (typeof connect === "function" && socketUrl()) connect();
  if (frames.length > 0) ready();
}

// Never let boot reject into the void. It was called bare, so anything that
// escaped it became an unhandled rejection: the console got a stack and the
// viewer got a silent ground-coloured stage, which is the one outcome this
// whole file is built to prevent.
boot().catch((error) => {
  fail("This viewer could not start.", String(error && error.message ? error.message : error));
});
