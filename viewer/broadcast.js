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
  stingerBack: "rgba(16,12,6,.93)",
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
};

// The original assigns palette colours to decision models in order
// (reference/dtl-python/gui.py: palette[0] red, palette[1] blue), so the two
// populations are red and blue exactly as in the model everyone recognises.
// Each hue is lifted slightly from the source so the same colour is legible
// BOTH as a dot on the white plate and as a chip on the dark broadcast panels,
// and each carries a redundant shape so the read never depends on hue alone.
//
// `text` is the second value, for the places a seat colour carries INK rather
// than filling a shape — the chart's pole label and the stinger's headline,
// which sit on the lead band itself where the chip hues measure 3.3-3.6:1. The
// chips themselves are used only as fills, where they are not text at all.
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
const TOP_INSET = BUG_H + 22;
const KEY_H = 34;
/* The transport gets its OWN LANE.
 *
 * The floating pill is laid out in CSS percentages of the stage; the board is
 * laid out here in stage units; the two were never reconciled, so the pill sat
 * ON the board — two lattice rows at 1280, and THREE at 640, where its pixel
 * floors bite while the board scales down. The compact variant occluded more of
 * the primary read surface than the full-size one.
 *
 * 104 units is what the pill needs at the embed floor: a 24px minimum target
 * plus padding and border is ~34 CSS px, and 34/360 of a 1080-unit stage is 102.
 * Reserving it costs the board 11% of its height everywhere and buys back every
 * row of the lattice. The CSS lane below is derived from the same constant.
 */
const TRANSPORT_H = 104;
const BOARD_SIZE = H - TOP_INSET - KEY_H - MARGIN - TRANSPORT_H;
const BOARD = { x: MARGIN, y: TOP_INSET + KEY_H, w: BOARD_SIZE, h: BOARD_SIZE };
const RAIL = { x: BOARD.x + BOARD.w + 26, y: TOP_INSET, w: W - (BOARD.x + BOARD.w + 26) - MARGIN };
RAIL.h = H - TOP_INSET - MARGIN - TRANSPORT_H;

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
const STINGER_MS = 2100;
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
  stingerUntil: 0,
  stinger: null,
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
 * So compact does not scale — it SWITCHES RAMPS. Four steps, chosen so the
 * smallest lands at 11.3 CSS px at the floor and the hierarchy between them
 * survives, with everything below the caption step collapsing INTO it. The
 * panels pay for that in content, not in overflow: compact drops the Lorenz
 * curve, the chart's axis annotations, the crown, a feed row, and the scorebug's
 * secondary line, and shortens population names to their last word.
 *
 *   caption 34u = 11.3px · label 40u = 13.3px · body 52u = 17.3px · figure 76u = 25.3px
 */
const COMPACT_RAMP = [
  [18, 34],        // caption   11.3px
  [22, 40],        // label     13.3px
  [30, 52],        // body      17.3px
  [44, 66],        // figure    22.0px
  [Infinity, 92],  // hero      30.7px
];

/** Map a type size onto the current density's ramp. */
function T(size) {
  if (!dense()) return size;
  for (const [limit, mapped] of COMPACT_RAMP) if (size <= limit) return mapped;
  return size;
}

/** Geometry that must stay proportional to the stage — a swatch, a dot radius, a
 *  rule's width. These do NOT take the type ramp: floored to 34 units a 6-unit
 *  dot becomes a blob that eats the label beside it. */
function G(size) {
  return dense() ? size * 1.34 : size;
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
  if (compact === state.compact) return;
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
    population: 0,
  }));
  for (const agent of frame.agents) {
    const row = rows[slotOf(agent)];
    if (!row) continue;
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
  state.stinger = null;
  state.stingerUntil = 0;
  state.holdUntil = 0;
  terrainShown = null;
  pendingBeat = null;
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
let pendingBeat = null;
/* TWO plates, not one: the one being shown and the one being left.
 *
 * A harvest is instantaneous in the model and used to be instantaneous on the
 * board — four units of sugar were simply gone on the tick a settler landed,
 * and one unit came back, whole, on each of the four ticks after it. Across the
 * ~250 cells that change every timestep on the shipped 32x32 board that reads as
 * a flicker rather than as eating. The outgoing plate is kept and the incoming
 * one dissolved over it, so grains drain and fill instead of blinking. */
let terrain = document.createElement("canvas");
let terrainOut = document.createElement("canvas");
let terrainContext = terrain.getContext("2d");
let terrainSettledAt = 0;             // when the current plate began fading in; 0 = shown whole
let terrainStir = -1;                 // which frame of the grain loop it is painted at

/* How long the sand takes to settle after a timestep lands.
 *
 * Scaled by animFactor with everything else, and deliberately shorter than the
 * gap between two harvests (a dwell, 770ms at 1x) so a fade always finishes
 * before the next one starts — a swap mid-dissolve would throw away the
 * half-blended plate and put back the cut this removes. */
const SETTLE_MS = 380;

/** How much of the current plate to show over the one it replaced. */
function terrainBlend(now) {
  if (!terrainSettledAt) return 1;
  const age = (now - terrainSettledAt) / (SETTLE_MS * animFactor(state.speed));
  if (age >= 1) return 1;
  return age * age * (3 - 2 * age);   // smoothstep; a linear dissolve pops at both ends
}

/** Swap the plates and paint `frame` into the fresh one. `fade` carries the
 *  dissolve; a scrub, a pause, a reset or reduced motion cuts straight over. */
function showTerrain(frame, fade, now) {
  const outgoing = terrain;
  terrain = terrainOut;
  terrainOut = outgoing;
  terrainContext = terrain.getContext("2d");
  terrainShown = frame;
  buildTerrain(frame, stirAt(now));
  terrainSettledAt = fade && terrainOut.width > 0 ? now : 0;
}

/** Repaint the plate one frame further round the grain loop. No swap: the sand
 *  stirs many times between timesteps, and swapping would cross-fade the plate
 *  with itself and cancel the dissolve a real harvest is owed. The plate being
 *  LEFT is not restirred — it is on its way out inside 380ms, and repainting a
 *  layer that is fading to nothing costs a second pass to move nothing. */
function stirTerrain(now) {
  if (terrainShown) buildTerrain(terrainShown, stirAt(now));
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
const PARTICLES_PER_UNIT = 26;
/* Eight, not three, because the cloud is now NESTED (see grainCloud).
 *
 * Amount no longer varies the arrangement, so the only thing standing between
 * the eye and a visible repeat is the variant count. Three was already thin
 * inside a massif, where every cell holds the same amount and so drew from the
 * same three tiles. */
const TILE_VARIANTS = 8;

/* AND THE SAND IS NEVER STILL.
 *
 * A cloud that never moves is a halftone print OF a cloud. The thing this plate
 * is meant to look like — spice blown across a dune — is defined by the fact
 * that it drifts, and holding it still read as printing rather than as weather.
 *
 * So every grain travels a small closed loop around a fixed home. A LOOP, and a
 * home it never leaves, because the picture is a per-cell quantity: a grain that
 * wandered into the next square would be a lie about the data, and a grain whose
 * home moved between timesteps is the flicker grainCloud exists to remove. The
 * loop is contained by INSET rather than by clipping — a grain cut off at the
 * tile edge prints a seam along every cell boundary that pulses once per loop.
 *
 * The loop is baked, not computed per frame: a strip holds GRAIN_PHASES frames of
 * the same cloud side by side, so a repaint still costs one blit per resource per
 * cell and the phase only picks a different column of the strip.
 *
 * Cross-fading two phases was the first attempt and it is wrong. Two half-alpha
 * copies of a grain do not average to one grain — they land at 1-f+f² of one, so
 * every filled cell dimmed to three quarters at mid-step and recovered at the
 * boundary, and the whole plate breathed at the step rate. There is no alpha here
 * at all now; there are simply enough phases that one step moves a grain about a
 * third of a pixel, which is below what the eye can resolve as a jump. Twenty-four
 * of them costs ~10 MB of sheet and one build per board size.
 *
 * The phase a cell shows is offset by where that cell stands on the lattice, so
 * the stir crosses the plate as a slow ripple rather than the whole field
 * twitching in lockstep — a crest every dozen cells on the diagonal, taking about
 * eight seconds to cross the shipped board.
 *
 * NOT scaled by animFactor, unlike every other motion on this stage: this is the
 * wind, not the clock. It keeps its own time while the replay is paused, sped up
 * or held on the end card, and it stops dead for a viewer who asked for reduced
 * motion. */
const GRAIN_PHASES = 24;
const GRAIN_PERIOD_MS = 1600;         // one full loop
const GRAIN_WAVELENGTH = 12;          // cells between ripple crests, on the diagonal
const GRAIN_RIPPLE = Math.max(1, Math.round(GRAIN_PHASES / GRAIN_WAVELENGTH));
const grainSheet = { key: "", strips: [[], []], size: 0 };

/** Which frame of the loop the sand stands at. Its own clock: see above. */
function stirAt(now) {
  return reducedMotion ? 0 : Math.floor(now / (GRAIN_PERIOD_MS / GRAIN_PHASES));
}

/** `value` brought into [0, span) — the cell wraps, so a grain that orbits off
 *  one edge comes back on the other rather than being clipped away. */
function wrapInto(value, span) {
  return ((value % span) + span) % span;
}

/** Which frame of the loop the cell at (x, y) shows. Offset by where the cell
 *  STANDS, so the stir crosses the plate as a ripple rather than every cell
 *  turning over on the same beat. Crests lie along x - y and travel down and to
 *  the left, which is the way the haze in the surround blows: one wind. */
function grainColumn(stir, x, y) {
  return wrapInto(stir + (x - y) * GRAIN_RIPPLE, GRAIN_PHASES);
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
function grainCloud(stream, count) {
  const cloud = [];
  for (let index = 0; index < count; index += 1) {
    cloud.push([
      grainOffset(stream, index, 0),
      grainOffset(stream, index, 1),
      // Grains vary in size. A single particle size reads as television static;
      // sand does not have one grade, and the variation is what makes the mass
      // look blown rather than generated.
      0.65 + grainOffset(stream, index, 2) * 0.95,
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

/** The strip holding `units` of `resource` in a given variant, or undefined. */
function grainStrip(resource, units, variant) {
  return grainSheet.strips[resource][(units - 1) * TILE_VARIANTS + variant];
}

function buildGrainSheet(cellPx) {
  const ceiling = grainCeiling();
  const key = `${cellPx}:${ceiling[0]}:${ceiling[1]}`;
  if (grainSheet.key === key) return;
  grainSheet.key = key;
  grainSheet.strips = [[], []];
  const size = Math.max(2, Math.ceil(cellPx));
  grainSheet.size = size;
  const particle = Math.max(1, size * 0.075);
  // How far a grain may wander from home. Under half a particle: the mass has to
  // read as stirred, not as scattered, and its density IS the quantity.
  const drift = Math.max(0.4, particle * 0.55);
  for (const [resource, colour] of [[0, SUGAR_HEX], [1, SPICE_HEX]]) {
    for (let units = 1; units <= ceiling[resource]; units += 1) {
      for (let variant = 0; variant < TILE_VARIANTS; variant += 1) {
        const strip = document.createElement("canvas");
        strip.width = size * GRAIN_PHASES;
        strip.height = size;
        const stripContext = strip.getContext("2d");
        stripContext.fillStyle = colour;
        const stream = grainStream(variant, resource);
        const cloud = grainCloud(stream, units * PARTICLES_PER_UNIT);
        for (let phase = 0; phase < GRAIN_PHASES; phase += 1) {
          stripContext.save();
          stripContext.beginPath();
          stripContext.rect(phase * size, 0, size, size);
          stripContext.clip();
          stripContext.translate(phase * size, 0);
          for (let index = 0; index < cloud.length; index += 1) {
            const [x, y, scale] = cloud[index];
            const grade = particle * scale;
            // Grains standing near each other lean together: the loop's starting
            // angle runs with the grain's own x, so a cell stirs as a wave passing
            // through it. Independent phases per grain fizz like static instead.
            const lean = x * 0.8 + grainOffset(stream, index, 3) * 0.2;
            const radius = drift * (0.45 + grainOffset(stream, index, 4) * 0.55);
            const angle = (lean + phase / GRAIN_PHASES) * Math.PI * 2;
            const px = wrapInto(x * size + Math.cos(angle) * radius, size);
            // Flatter than it is wide. Wind runs ACROSS a dune field, and a round
            // orbit reads as boiling where a flat one reads as blown.
            const py = wrapInto(y * size + Math.sin(angle) * radius * 0.4, size);
            stripContext.fillRect(px, py, grade, grade);
            // The cell is a TORUS, not a box with margins. Inseting the homes so
            // no orbit could reach an edge was the first fix and it printed a
            // gutter at every cell boundary — a two-pixel dark rule around all
            // 1,024 of them, which is the woven-mesh artefact this whole cloud
            // exists to avoid. A grain leaving one edge re-enters at the opposite
            // one instead, so the density stays flat right across the boundary.
            const overX = px + grade > size;
            const overY = py + grade > size;
            if (overX) stripContext.fillRect(px - size, py, grade, grade);
            if (overY) stripContext.fillRect(px, py - size, grade, grade);
            if (overX && overY) stripContext.fillRect(px - size, py - size, grade, grade);
          }
          stripContext.restore();
        }
        grainSheet.strips[resource][(units - 1) * TILE_VARIANTS + variant] = strip;
      }
    }
  }
}

function buildTerrain(frame, stir) {
  const size = Math.round(BOARD.w * RENDER_SCALE);
  if (terrain.width !== size) terrain.width = terrain.height = size;
  const cell = size / Math.max(frame.width, frame.height);
  terrainContext.setTransform(1, 0, 0, 1, 0, 0);
  terrainContext.clearRect(0, 0, terrain.width, terrain.height);
  terrainContext.fillStyle = PLATE_HEX;
  terrainContext.fillRect(0, 0, cell * frame.width, cell * frame.height);

  buildGrainSheet(cell);
  terrainStir = stir;
  const tile = grainSheet.size;
  const ceiling = grainCeiling();
  for (let index = 0; index < frame.cells.length; index += 1) {
    const [sugar, spice] = frame.cells[index];
    if (sugar <= 0 && spice <= 0) continue;
    // cellId = x * height + y (column-major).
    const x = Math.floor(index / frame.height);
    const y = index % frame.height;
    // The variant is chosen per CELL, so the same amount does not print the same
    // arrangement across a whole massif...
    const variant = Math.floor(grainOffset(index, 7, 11) * TILE_VARIANTS);
    const column = grainColumn(stir, x, y);
    const left = Math.round(x * cell);
    const top = Math.round(y * cell);
    for (const [resource, amount] of [[0, sugar], [1, spice]]) {
      const units = Math.min(ceiling[resource], Math.max(0, Math.round(amount)));
      if (units <= 0) continue;
      const strip = grainStrip(resource, units, variant);
      if (!strip) continue;
      terrainContext.drawImage(strip, column * tile, 0, tile, tile, left, top, tile, tile);
    }
  }
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
      starving: agent.sugar <= agent.sugarMetabolism
        || (agent.spiceMetabolism > 0 && agent.spice <= agent.spiceMetabolism),
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
  // The plate the settlers are leaving, with the one they have just made
  // dissolving over it. Both carry the same opaque field colour, so only the
  // grains that actually changed hands are in motion: the ones a settler ate
  // drain away and the ones that regrew fill in.
  const settle = terrainBlend(now);
  if (settle < 1) context.drawImage(terrainOut, BOARD.x, BOARD.y, BOARD.w, BOARD.h);
  context.globalAlpha = settle;
  context.drawImage(terrain, BOARD.x, BOARD.y, BOARD.w, BOARD.h);
  context.globalAlpha = 1;

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
  const radius = cell * 0.31;
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
  for (const body of bodies) {
    const seat = seatOf(body.slot);
    const size = radius * (0.82 + 0.36 * Math.min(1, Math.log10(1 + body.wealth) / 2.4));
    context.beginPath();
    context.arc(body.px, body.py, size, 0, Math.PI * 2);
    if (body.starving) {
      // Hollow means EMPTY, so it has to be the plate showing through. Filling
      // it with paper was right on a white field and is the brightest blob on
      // screen on a dark one — the exact opposite of the meaning.
      context.fillStyle = PLATE_HEX;
      context.fill();
      context.lineWidth = Math.max(1.2, cell * 0.12);
      context.strokeStyle = seat.color;
      context.stroke();
    } else {
      // seat.color, not seat.board: the board variants were darkened to sit on a
      // white field and disappear into this one.
      context.fillStyle = seat.color;
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
function wealthTotal(frame) {
  let total = 0;
  for (const agent of frame.agents) total += agent.sugar + agent.spice;
  return total;
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
  const y = TOP_INSET + KEY_H - 12;
  let x = BOARD.x + 2;
  let markup = "";
  const size = T(18);
  const dot = G(6);
  const gap = G(20);
  const swatchW = G(13);
  const style = { size, weight: 600, fill: C.muted, outline: 2.6 };
  // One ramp per resource the world actually carries. The shipped config seeds
  // BOTH sugar and spice peaks, so most of the plate is the rust of spice while
  // the key taught only the yellow of sugar — the dominant colour on the board
  // was the one thing the legend did not explain.
  // The key has to teach what the board actually encodes. It used to show a
  // colour ramp because the board WAS a colour ramp; the board is grain density
  // now, so the swatches count grains — none, one, two, three, four.
  const ramps = [["sugar", SUGAR_HEX, state.maxSugar]];
  if (state.maxSpice > 0) ramps.push(["spice", SPICE_HEX, state.maxSpice]);
  for (const [label, grainColour, peak] of ramps) {
    const steps = Math.max(1, Math.min(4, Math.round(peak)));
    for (let step = 0; step <= steps; step += 1) {
      const cellX = x + step * (swatchW + 2);
      markup += `<rect x="${cellX}" y="${y - swatchW + 2}" `
        + `width="${swatchW}" height="${swatchW}" fill="${PLATE_HEX}" `
        + `stroke="${GRID_HEX}" stroke-width="0.8"/>`;
      // The same cloud the board draws, at the same relative density, so the key
      // teaches the encoding rather than a different notation for it.
      const particle = Math.max(0.7, swatchW * 0.11);
      const count = Math.round(step * 9);
      for (let index = 0; index < count; index += 1) {
        markup += `<rect x="${cellX + 1 + grainOffset(step, index, 0) * (swatchW - particle - 2)}" `
          + `y="${y - swatchW + 3 + grainOffset(step, index, 1) * (swatchW - particle - 2)}" `
          + `width="${particle}" height="${particle}" fill="${grainColour}"/>`;
      }
    }
    x += (steps + 1) * (swatchW + 2) + 8;
    markup += text(label, x, y, style);
    // Advance by the REAL type size. A fixed per-character step was tuned
    // against one ramp and overlapped every label the moment the other was in
    // force. The trailing gap is proportional too, or the key reads as one run
    // of words the moment the ramp grows.
    x += advance(label, size) + gap;
  }
  // A WIDTH BUDGET. This accumulated x with no measurement against the plate, so
  // it terminated 16 units inside the board's right edge with the shipped names
  // and ran clean off it with anything longer — and the names come from the
  // manifest, not from here. Shorten until the run fits.
  const rightEdge = BOARD.x + BOARD.w;
  const tailWidth = dot + G(7) + advance("about to starve", size) + gap;
  const budget = (rightEdge - x - tailWidth) / Math.max(1, frame.slots.length);
  frame.slots.forEach((slot, index) => {
    markup += `<circle cx="${x}" cy="${y - dot}" r="${dot}" fill="${seatOf(index).color}"/>`;
    const full = slot.name || `Population ${index + 1}`;
    let label = dense() ? full.split(/\s+/).at(-1) : full;
    if (advance(label, size) + dot + G(7) + gap > budget) {
      label = full.split(/\s+/).at(-1);
    }
    while (label.length > 1 && advance(label, size) + dot + G(7) + gap > budget) {
      label = `${label.slice(0, -2)}…`;
    }
    markup += text(label, x + dot + G(7), y, style);
    x += dot + G(7) + advance(label, size) + gap;
  });
  markup += `<circle cx="${x}" cy="${y - dot}" r="${dot}" fill="none" `
    + `stroke="${C.muted}" stroke-width="${G(2.2)}"/>`;
  markup += text("about to starve", x + dot + G(7), y, style);
  return markup;
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
    big
      ? `most ${resourceName()} wins`
      : `${frame.slots.length} populations, one lattice · most ${resourceName()} wins`,
    MARGIN + 2, big ? 88 : 66, { size: T(18), weight: 500, fill: C.muted });

  // Clock — counts to the SCHEDULED end of the match, so an early extinction
  // freezes short of the buzzer instead of always landing on the last tick.
  //
  // The band is 92 units tall and the dense ramp sets the figure at 66, which
  // leaves no room to stack an eyebrow above it or run a progress bar beside it.
  // So dense states the fraction on one line and lets the transport's own played
  // track carry the bar — it already did, at both densities.
  const clockX = big ? MARGIN + 400 : MARGIN + 476;
  const clockW = big ? 490 : 320;
  markup += panel(clockX, 14, clockW, BUG_H);
  if (big) {
    markup += text(`${frame.timestep} / ${scheduled}`, clockX + 20, 72, {
      size: T(40), weight: 600, family: F.mono, fill: C.paper,
    });
    if (stateLabel) {
      markup += text(stateLabel, clockX + clockW - 20, 72, {
        size: T(18), weight: 700, family: F.mono, anchor: "end",
        fill: stateFill, spacing: 1.4,
      });
    }
  } else {
    markup += eyebrow("Timestep", clockX + 18, 46);
    markup += text(`${frame.timestep}`, clockX + 18, 84, {
      size: 40, weight: 600, family: F.mono, fill: C.paper,
    });
    // Mono advances at ~0.6em, so the fraction's offset is read off the size
    // rather than off a constant tuned for one of them.
    markup += text(` / ${scheduled}`,
      clockX + 18 + String(frame.timestep).length * 40 * 0.6, 84, {
        size: T(24), weight: 500, family: F.mono, fill: C.muted,
      });
    const barX = clockX + 178;
    const barW = clockW - 196;
    markup += `<rect x="${barX}" y="60" width="${barW}" height="9" rx="4.5" fill="${C.trackBed}"/>`;
    markup += `<rect x="${barX}" y="60" width="${Math.max(3, barW * progress)}" `
      + `height="9" rx="4.5" fill="${C.gold}"/>`;
    if (stateLabel) {
      markup += text(stateLabel, barX + barW, 46, {
        size: T(18), weight: 700, family: F.mono, anchor: "end",
        fill: stateFill, spacing: 1.4,
      });
    }
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
    // White at the same size out-punches gold, so the LOSING number was winning
    // the eye. The leader is gold and bright; everyone else steps back.
    markup += text(format(row.score), x + chipW - 20, big ? 58 : 62, {
      size: T(40), weight: 700, family: F.mono, anchor: "end",
      fill: leader ? C.gold : C.muted,
    });
    markup += text(
      margin === 0 ? "level" : margin > 0 ? `+${format(margin)}` : `\u2212${format(-margin)}`,
      x + chipW - 20, big ? 96 : 84,
      {
        size: big ? T(18) : T(20), weight: 700, family: F.mono, anchor: "end",
        fill: margin > 0 ? C.gold : C.muted,
      },
    );
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
function raceChart(frame, x, y, width, height) {
  const big = dense();
  const scheduled = state.maxTimestep || 1;
  const top = y + (big ? 62 : 46);
  const plotH = height - (big ? 84 : 76);
  // The gutter has to hold the axis figure, which is set on the ramp: at 34
  // units "+2,334" is 122 units wide and a 62-unit gutter pushed it clean off
  // the panel's left edge.
  const left = x + (big ? 138 : 62);
  const plotW = width - left + x - 18;
  const scaleX = (timestep) => left + (timestep / scheduled) * plotW;
  const visible = wealthSeries.filter((point) => point.timestep <= frame.timestep);
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
    markup += text("total wealth", left + plotW / 2, top + plotH + T(18) + 8,
      { ...axis, anchor: "middle" });
    return markup;
  }

  /* The size of the lead, always upward, coloured by who holds it.
   *
   * This was a signed diverging plot: slot 0 above the midline, slot 1 below.
   * It was quantitatively correct and it read BACKWARDS - the leader's line
   * descended, so a viewer applying the near-universal "up is winning" saw the
   * chart contradict the scoreboard on the one question that matters. Plotting
   * the ABSOLUTE lead removes the ambiguity: higher is a bigger lead, the colour
   * says whose, and a lead change is the band touching zero and changing colour. */
  const peak = Math.max(
    12,
    ...visible.map((point) => Math.abs((point.scores[0] ?? 0) - (point.scores[1] ?? 0))),
  );
  const baseY = top + plotH;
  const scaleY = (lead) => baseY - (Math.abs(lead) / peak) * plotH;

  for (const event of events) {
    if (event.kind !== "lead" || event.timestep > frame.timestep) continue;
    markup += `<line x1="${scaleX(event.timestep)}" y1="${top}" `
      + `x2="${scaleX(event.timestep)}" y2="${baseY}" `
      + `stroke="${C.gold}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".6"/>`;
  }

  // One filled band per unbroken spell of leadership, so the colour changes
  // exactly where the lead does.
  let spell = [];
  let spellLeader = -1;
  const flush = () => {
    if (spell.length === 0 || spellLeader < 0) return;
    const path = spell.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    markup += `<polygon points="${spell[0].x.toFixed(1)},${baseY} ${path} `
      + `${spell.at(-1).x.toFixed(1)},${baseY}" fill="${seatOf(spellLeader).color}" opacity=".42"/>`;
    markup += `<polyline points="${path}" fill="none" stroke="${seatOf(spellLeader).color}" `
      + `stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`;
  };
  for (const point of visible) {
    const lead = (point.scores[0] ?? 0) - (point.scores[1] ?? 0);
    const leader = lead === 0 ? spellLeader : (lead > 0 ? 0 : 1);
    const at = { x: scaleX(point.timestep), y: scaleY(lead) };
    if (leader !== spellLeader && spell.length > 0) {
      spell.push({ x: at.x, y: baseY });
      flush();
      spell = [{ x: at.x, y: baseY }];
    }
    spellLeader = leader;
    spell.push(at);
  }
  flush();

  markup += `<line x1="${left}" y1="${baseY}" x2="${left + plotW}" y2="${baseY}" `
    + `stroke="${C.axis}" stroke-width="1.5"/>`;
  markup += text(`+${format(peak)}`, left - 10, top + T(18) * 0.7, axis);
  markup += text("level", left - 10, baseY + T(18) * 0.28, axis);

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
    /* Put the label where the band ISN'T.
     *
     * It was pinned to the plot's top-left, and `peak` is the running maximum,
     * so whenever the current lead IS the maximum - the normal case for a lead
     * that grows - the band head reaches exactly `top` and the label sat on its
     * own fill at 3.32:1, with the head dot landing inside the glyphs. The band
     * always starts at the baseline on the left, so when the head is close, drop
     * to the foot of the plot, which is empty by construction.
     */
    const caption = leader < 0
      ? "level"
      : `${big ? holder.split(/\s+/).at(-1) : holder} ahead`;
    const size = T(19);
    const clash = scaleX(last.timestep) < left + 14 + advance(caption, size) + 24
      && headY < top + size * 1.6;
    markup += text(caption, left + 14, clash ? baseY - 14 : top + size, {
      size, weight: 700, fill: leader < 0 ? C.muted : seatOf(leader).text, outline: 3,
    });
  }

  // At the embed floor these land under 7px, so the chart keeps its shape and
  // its headline count and drops the annotations rather than printing a smear.
  if (!big) {
    markup += text("t0", left, y + height - 16, { ...axis, anchor: "start" });
    markup += text(`t${scheduled}`, left + plotW, y + height - 16, axis);
    markup += text(`lead, in ${resourceName()}`, left + plotW / 2, y + height - 16,
      { ...axis, anchor: "middle" });
  }
  return markup;
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
      const folded = event.kind === "summary" && event.leads > 0
        ? `${line}${event.count > 0 ? " · " : ""}`
          + `${event.leads} lead change${event.leads === 1 ? "" : "s"}`
        : line;
      markup += text(
        event.count === 0 && event.kind === "summary"
          ? `${event.leads} lead change${event.leads === 1 ? "" : "s"}`
          : folded,
        x + indent, rowY + (big ? 36 : 16),
        { size: T(25), weight: 500, fill: fresh ? C.paper : C.muted },
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

function stinger() {
  const event = state.stinger;
  const width = Math.min(BOARD.w - 24, dense() ? 860 : 720);
  const x = BOARD.x + (BOARD.w - width) / 2;
  const y = BOARD.y + BOARD.h * 0.36;
  // The rule and the border take the CHIP colour; the headline takes the lifted
  // `text` variant, which is the one measured against the card behind it.
  const rule = event.kind === "lead" ? seatOf(event.slot).color : C.loss;
  const ink = event.kind === "lead" ? seatOf(event.slot).text : C.loss;
  const headline = event.kind === "lead" ? "LEAD CHANGE" : "DIE-OFF";
  // The cause the ENGINE reported, and the right plural. This said "starved" for
  // every die-off - which deathCause()'s own docstring calls out as wrong the
  // moment aging, combat or disease is enabled - and printed "1 settlers".
  const detail = event.kind === "lead"
    ? `${event.name} moves ahead by ${format(event.margin)}`
    : `${event.count} settler${event.count === 1 ? "" : "s"} `
      + `${event.cause ?? "lost"} this timestep`;
  // The one element whose whole job is to INTERRUPT, and it was the only draw
  // function with no density branch: raw 30 and 24 units, which is 10.0 and 8.0
  // CSS px at the embed floor - the smallest type in the product, on the
  // callout. It takes the ramp like everything else now, and the plate is sized
  // from the type rather than pinned at 118 units.
  const headSize = T(30);
  const detailSize = T(24);
  const height = headSize + detailSize + 54;
  return `<g class="stinger">`
    + `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="12" fill="${C.stingerBack}" `
    + `stroke="${rule}" stroke-width="2.5"/>`
    + `<rect x="${x}" y="${y}" width="7" height="${height}" rx="3.5" fill="${rule}"/>`
    + text(headline, x + 34, y + headSize + 16, {
      size: headSize, weight: 700, fill: ink, spacing: 3.2,
    })
    + text(detail, x + 34, y + headSize + detailSize + 30, {
      size: detailSize, weight: 500, fill: C.paper,
    })
    + `</g>`;
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
  const verdict = tie
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
  const context = state.sawStart
    ? `${survivors} of ${state.startingPopulation} settlers survived.${spread}`
    : `${survivors} settlers still standing.${spread}`;

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
    markup += text(format(row.score), x + cardW - pad - 36, rowY + rowH * 0.66, {
      size: T(34), weight: 700, family: F.mono, fill: leader ? C.gold : C.paper, anchor: "end",
    });
    rowY += rowStep;
  }
  markup += text(
    big
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
    .stinger { animation: stinger-in .34s cubic-bezier(.2,.9,.3,1.25) both; }
    @keyframes stinger-in {
      from { opacity: 0; transform: translateY(16px) scale(.97); }
      to   { opacity: 1; transform: none; }
    }
    .endcard { animation: endcard-in .55s ease both; }
    @keyframes endcard-in { from { opacity: 0; } to { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) {
      .stinger, .endcard { animation: none !important; }
    }
  </style>`;
}

/* The overlay is split into two independently-updated layers.
 *
 * This is load-bearing, not an optimisation: replacing an element's markup
 * restarts every CSS animation inside it, so rebuilding the whole overlay on
 * each 33 ms tick pinned the end card and the stingers at the first frame of
 * their fade and neither ever became visible. The standings layer changes at
 * timestep boundaries; the beat layer changes only when a beat starts or ends.
 * Keeping them apart lets each animate for its full duration. */
hud.innerHTML = `${defs()}<g id="hud-standings"></g><g id="hud-beats"></g>`;
const standingsLayer = hud.querySelector("#hud-standings");
const beatsLayer = hud.querySelector("#hud-beats");
let standingsSignature = "";
let beatsSignature = "";

function drawBeats(frame, now) {
  const live = Boolean(state.stinger) && now <= state.stingerUntil;
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  const signature = live ? `stinger:${state.stinger.index}:${state.stinger.kind}` : "";
  const full = `${signature}|${atEnd}|${currentIndex()}`;
  if (full === beatsSignature) return;
  beatsSignature = full;
  beatsLayer.innerHTML = (live ? stinger() : "") + (atEnd ? endCard(frame) : "");
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
   */
  const raceH = dense() ? 320 : 280;
  const feedH = dense() ? 278 : 250;
  const emergenceH = RAIL.h - raceH - feedH - railGap * 2;
  let markup = raceChart(frame, RAIL.x, RAIL.y, RAIL.w, raceH);
  markup += eventFeed(frame, RAIL.x, RAIL.y + raceH + railGap, RAIL.w, feedH);
  markup += emergence(frame, RAIL.x, RAIL.y + raceH + feedH + railGap * 2, RAIL.w, emergenceH);
  markup += scorebug(frame);
  markup += boardKey(frame);
  standingsLayer.innerHTML = markup;
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

let lastTick = 0;

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
    // A lead change is the loudest beat in this match; a die-off only earns the
    // stinger when it is big enough to matter. Queued, not fired: the beat has
    // to wait for the settlers to arrive, or it announces "Beta moves ahead"
    // over a scorebug that still crowns Alpha.
    if (event.kind === "lead" || (event.kind === "death" && event.count >= 3)) {
      if (!pendingBeat || event.kind === "lead") pendingBeat = event;
    }
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
  } else if (stirAt(now) !== terrainStir) {
    // Between timesteps the plate still moves: the sand goes on blowing whether
    // or not the replay is running.
    stirTerrain(now);
  }
  // Interpolate from the PREVIOUS frame into this one, so the settler arrives
  // exactly as its recorded state lands rather than leaving it early.
  drawBoard(frame, previous, previous && !reducedMotion ? fraction : 1, now);
  // The HUD reads the same frame the board is showing. Rendering frame N's
  // scores while the settlers were still walking in from N-1 put the clock, the
  // harvested lattice and the scoreboard a full timestep ahead of the bodies.
  // Release the queued beat only once the board and the standings have caught
  // up to the frame it describes.
  if (pendingBeat && settled) {
    state.stinger = pendingBeat;
    state.stingerUntil = now + STINGER_MS * animFactor(state.speed);
    pendingBeat = null;
  }
  drawHud(terrainFrame, settled ? index : index - 1);
  drawBeats(frame, now);
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
async function loadArtifact(url) {
  let payload;
  try {
    const response = await fetch(url, { mode: "cors" });
    if (!response.ok) throw new Error(String(response.status));
    payload = await response.json();
  } catch (error) {
    fail("Could not load this replay.", url);
    return;
  }
  if (!payload || payload.format !== "sugarscape.replay.v1" || !Array.isArray(payload.frames)) {
    fail("That file is not a sugarscape.replay.v1 recording.", url);
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
  lastTick = performance.now();
  // A timer, not requestAnimationFrame: a backgrounded or headless tab throttles
  // rAF to a few frames a second and starves the interpolation. 16ms rather
  // than 33 because settlers jump several cells per timestep, and at 30fps that
  // motion reads as stepping rather than moving; the terrain is cached now, so
  // the extra draws are cheap.
  setInterval(tick, 16);

  const replay = new URLSearchParams(location.search).get("replay");
  if (replay) await loadArtifact(replay);
  else connect();
  if (frames.length > 0) ready();
}

// Never let boot reject into the void. It was called bare, so anything that
// escaped it became an unhandled rejection: the console got a stack and the
// viewer got a silent ground-coloured stage, which is the one outcome this
// whole file is built to prevent.
boot().catch((error) => {
  fail("This viewer could not start.", String(error && error.message ? error.message : error));
});
