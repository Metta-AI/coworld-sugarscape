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
// Theme — the Phase-0c art-direction lock, as tokens. No inline hex below.
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
};

// The original assigns palette colours to decision models in order
// (reference/dtl-python/gui.py: palette[0] red, palette[1] blue), so the two
// populations are red and blue exactly as in the model everyone recognises.
// Each hue is lifted slightly from the source so the same colour is legible
// BOTH as a dot on the white plate and as a chip on the dark broadcast panels,
// and each carries a redundant shape so the read never depends on hue alone.
const SEATS = [
  { color: "#f5504a", board: "#c22318" },   // gui.py palette[0] #FA3232
  { color: "#5a7cff", board: "#2340c4" },   // gui.py palette[1] #3232FA
  { color: "#6bd47f", board: "#1c7038" },   // palette[2] #32FA32
  { color: "#52d6e8", board: "#0d6f7e" },   // palette[3] #32FAFA
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
const BOARD = { x: MARGIN, y: TOP_INSET + KEY_H, w: H - TOP_INSET - KEY_H - MARGIN,
  h: H - TOP_INSET - KEY_H - MARGIN };
const RAIL = { x: BOARD.x + BOARD.w + 26, y: TOP_INSET, w: W - (BOARD.x + BOARD.w + 26) - MARGIN };
RAIL.h = H - TOP_INSET - MARGIN;

// ---------------------------------------------------------------------------
// Tempo — two independent levers (the Agricogla model).
//   animFactor  caps motion so it never plays faster than ANIM_MAX x real time.
//   frameDwellMs floors the auto-advance so speed collapses DEAD TIME between
//   timesteps, never the walk itself.
// ---------------------------------------------------------------------------

// The board's motion IS the product, so reduced motion does not disable it -
// it stops the replay auto-advancing, snaps between timesteps instead of
// interpolating, and drops the death rings. The viewer can still step and scrub.
const reducedMotion = typeof matchMedia === "function"
  && matchMedia("(prefers-reduced-motion: reduce)").matches;

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
};

/** Scale a type size for the current density. Compact mode pairs this with
 *  DROPPING content — sizing up alone would just overflow the panels. */
function T(size) {
  return state.compact ? Math.round(size * 1.28) : size;
}

function measureDensity() {
  const width = document.getElementById("stage").getBoundingClientRect().width;
  const compact = width > 0 && width < 900;
  if (compact === state.compact) return;
  state.compact = compact;
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

  const before = ranked(previous);
  const after = ranked(frame);
  // ranked() breaks ties by slot index, so a momentary tie would otherwise
  // "change" the leader twice against a leader who never actually lost it.
  const tied = (after.length > 1 && after[0].score === after[1].score)
    || (before.length > 1 && before[0].score === before[1].score);
  if (!tied && before[0] && after[0] && before[0].index !== after[0].index) {
    events.push({
      index,
      timestep: frame.timestep,
      kind: "lead",
      slot: after[0].index,
      name: after[0].name,
      margin: after[0].score - (after[1]?.score ?? 0),
    });
  }
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

  // Take the running maximum rather than frame zero's: a spectator joining a
  // live episode past the server's backlog cap never sees frame zero, and would
  // otherwise normalise the whole colour ramp against a partly-eaten world.
  // The artifact path overrides both from config, which is authoritative.
  if (frame.timestep === 0) state.sawStart = true;
  // Only frame zero, or the config on the artifact path, can say how many
  // settlers the episode began with. A spectator joining past the server's live
  // backlog cap has neither, and taking the largest population seen would print
  // "32 of 36 survived" for an episode that started with 64.
  state.startingPopulation = Math.max(state.startingPopulation, frame.agents.length);
  for (const cell of frame.cells) {
    if (cell[0] > state.maxSugar) state.maxSugar = cell[0];
    if (cell[1] > state.maxSpice) state.maxSpice = cell[1];
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
  controls.scrub.max = String(Math.max(0, frames.length - 1));
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

const SUGAR_HEX = [242, 250, 0];      // #F2FA00, from gui.py
const SPICE_HEX = [155, 71, 34];      // #9B4722, from gui.py
const EMPTY_HEX = [251, 248, 240];    // the original's white, warmed a touch
const GRID_HEX = "#c6c4bd";           // gui.py cell outline #c0c0c0, warmed a shade

let terrainShown = null;
let pendingBeat = null;
const terrain = document.createElement("canvas");
const terrainContext = terrain.getContext("2d");

function mix(from, to, factor) {
  return [
    from[0] + (to[0] - from[0]) * factor,
    from[1] + (to[1] - from[1]) * factor,
    from[2] + (to[2] - from[2]) * factor,
  ];
}

/** The original's two-axis cell colour (gui.py findSugarAndSpiceColors). With
 *  spice disabled - as in the shipping variant - this collapses to a straight
 *  white-to-yellow ramp on sugar, which is the familiar image. */
function cellColor(sugar, spice) {
  const sugarFactor = state.maxSugar > 0 ? Math.min(1, sugar / state.maxSugar) : 0;
  const spiceFactor = state.maxSpice > 0 ? Math.min(1, spice / state.maxSpice) : 0;
  const blend = mix(SUGAR_HEX, SPICE_HEX, 0.5);
  const top = mix(EMPTY_HEX, SPICE_HEX, spiceFactor);
  const bottom = mix(SUGAR_HEX, blend, spiceFactor);
  const final = mix(top, bottom, sugarFactor);
  return `rgb(${Math.round(final[0])},${Math.round(final[1])},${Math.round(final[2])})`;
}

function buildTerrain(frame) {
  const size = Math.round(BOARD.w * RENDER_SCALE);
  if (terrain.width !== size) terrain.width = terrain.height = size;
  const cell = size / frame.width;
  terrainContext.setTransform(1, 0, 0, 1, 0, 0);

  // The lattice is drawn as the GAPS between cells, not as a separate stroke
  // pass. Stroking one line per column at Math.round(i * cell) + 0.5 put the
  // lines at fractional positions, so their weight swung with subpixel phase and
  // the board moired into a plaid at the embed floor. Filling the field with the
  // lattice colour and insetting each cell by a fixed hairline gives a perfectly
  // even grid at any scale.
  // At the embed floor a cell is under 10 CSS px, so a hairline lands on a
  // fraction of a device pixel: a third of the lines drop out and the survivors
  // carry three different weights, which is the plaid. Below that size the
  // lattice is simply not drawn - the flat cell blocks already read as a grid,
  // and a grid you cannot render evenly is worse than none.
  const hairline = state.compact ? 0 : Math.max(1, Math.round(cell * 0.05));
  terrainContext.fillStyle = hairline > 0 ? GRID_HEX : `rgb(${EMPTY_HEX.join(",")})`;
  terrainContext.fillRect(0, 0, size, size);

  for (let index = 0; index < frame.cells.length; index += 1) {
    const [sugar, spice] = frame.cells[index];
    // cellId = x * height + y (column-major).
    const x = Math.round(Math.floor(index / frame.height) * cell);
    const y = Math.round((index % frame.height) * cell);
    const right = Math.round((Math.floor(index / frame.height) + 1) * cell);
    const bottom = Math.round((index % frame.height + 1) * cell);
    terrainContext.fillStyle = cellColor(sugar, spice);
    terrainContext.fillRect(x, y, right - x - hairline, bottom - y - hairline);
  }
}

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

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
  const cell = BOARD.w / frame.width;

  context.setTransform(RENDER_SCALE, 0, 0, RENDER_SCALE, 0, 0);
  context.clearRect(0, 0, W, H);
  context.fillStyle = C.ground;
  context.fillRect(0, 0, W, H);

  // A bright plate seated on the dark broadcast surround by a thin warm mat.
  context.save();
  context.shadowColor = "rgba(0,0,0,.5)";
  context.shadowBlur = 22;
  context.shadowOffsetY = 5;
  context.fillStyle = C.ink;
  context.fillRect(BOARD.x - 5, BOARD.y - 5, BOARD.w + 10, BOARD.h + 10);
  context.restore();
  context.drawImage(terrain, BOARD.x, BOARD.y, BOARD.w, BOARD.h);

  // A settler starving leaves an expanding ring where it stood.
  for (let index = motes.length - 1; index >= 0; index -= 1) {
    const mote = motes[index];
    const age = (now - mote.born) / (MOTE_MS * animFactor(state.speed));
    if (age >= 1) { motes.splice(index, 1); continue; }
    context.globalAlpha = (1 - age) * 0.85;
    context.strokeStyle = "#a8321a";   // the loss hue, dark enough for the plate
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
  for (const body of bodies) {
    const seat = seatOf(body.slot);
    const size = radius * (0.82 + 0.36 * Math.min(1, Math.log10(1 + body.wealth) / 2.4));
    context.beginPath();
    context.arc(body.px, body.py, size, 0, Math.PI * 2);
    if (body.starving) {
      context.fillStyle = "rgba(251,248,240,.9)";
      context.fill();
      context.lineWidth = Math.max(1.2, cell * 0.12);
      context.strokeStyle = seat.board;
      context.stroke();
    } else {
      context.fillStyle = seat.board;
      context.fill();
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
  const swatchW = T(13);
  for (let step = 0; step <= 4; step += 1) {
    markup += `<rect x="${x + step * (swatchW + 2)}" y="${y - swatchW + 2}" `
      + `width="${swatchW}" height="${swatchW}" fill="${cellColor(step / 4 * state.maxSugar, 0)}" `
      + `stroke="${GRID_HEX}" stroke-width="0.8"/>`;
  }
  x += 5 * (swatchW + 2) + 8;
  markup += text("sugar", x, y, { size: T(17), weight: 600, fill: C.muted, outline: 2.6 });
  x += T(17) * 3.4 + 14;
  frame.slots.forEach((slot, index) => {
    markup += `<circle cx="${x}" cy="${y - T(6)}" r="${T(6)}" fill="${seatOf(index).color}"/>`;
    const label = slot.name || `Population ${index + 1}`;
    markup += text(label, x + T(10), y, { size: T(17), weight: 600, fill: C.muted, outline: 2.6 });
    x += T(10) + label.length * T(8.6) + 16;
  });
  markup += `<circle cx="${x}" cy="${y - T(6)}" r="${T(6)}" fill="none" `
    + `stroke="${C.muted}" stroke-width="${T(2.2)}"/>`;
  markup += text("about to starve", x + T(10), y, {
    size: T(17), weight: 600, fill: C.muted, outline: 2.6,
  });
  return markup;
}

function scorebug(frame) {
  const rows = ranked(frame);
  const scheduled = state.maxTimestep || frame.timestep;
  const progress = scheduled > 0 ? Math.min(1, frame.timestep / scheduled) : 0;
  const clockW = 320;
  let markup = `<rect x="0" y="0" width="${W}" height="${BUG_H + 18}" fill="url(#bug-scrim)"/>`;

  // Name the broadcast. Without it a first-time viewer can see two populations
  // and a number going up, but never learns what they are competing FOR.
  markup += text("SUGARSCAPE", MARGIN + 2, 38, {
    size: 27, weight: 700, fill: C.paper, spacing: 5.2,
  });
  markup += text(
    // Not "one mountain": configuration.nim re-seats an out-of-range peak to a
    // RANDOM in-range coordinate, so how many massifs a world has is a property
    // of the seed, not of the config. Do not assert what the board can show.
    state.compact
      ? `${frame.slots.length} populations · most ${resourceName()} wins`
      : `${frame.slots.length} populations forage one lattice · most ${resourceName()} wins`,
    MARGIN + 2, 66, { size: T(16), weight: 500, fill: C.muted });

  // Clock — counts to the SCHEDULED end of the match, so an early extinction
  // freezes short of the buzzer instead of always landing on the last tick.
  markup += panel(MARGIN + 476, 14, clockW, BUG_H);
  markup += eyebrow("Timestep", MARGIN + 494, 46);
  markup += text(`${frame.timestep}`, MARGIN + 494, 84, {
    size: 40, weight: 600, family: F.mono, fill: C.paper,
  });
  markup += text(` / ${scheduled}`, MARGIN + 494 + String(frame.timestep).length * 25, 84, {
    size: T(24), weight: 500, family: F.mono, fill: C.muted,
  });
  const barX = MARGIN + 654;
  const barW = clockW - 196;
  markup += `<rect x="${barX}" y="60" width="${barW}" height="9" rx="4.5" fill="rgba(246,234,210,.14)"/>`;
  markup += `<rect x="${barX}" y="60" width="${Math.max(3, barW * progress)}" height="9" rx="4.5" fill="${C.gold}"/>`;
  // FINAL belongs to where the CURSOR is, not to whether the stream has ended:
  // scrubbing back into the middle of a finished episode is mid-match again.
  const atEnd = state.finished && currentIndex() >= frames.length - 1;
  markup += text(
    state.truncated ? "CUT SHORT" : atEnd ? "FINAL" : `${Math.round(progress * 100)}%`,
    barX + barW, 46,
    {
      size: T(16), weight: 700, family: F.mono, anchor: "end",
      fill: state.truncated ? C.loss : atEnd ? C.gold : C.muted, spacing: 1.4,
    },
  );
  if (state.truncated) {
    markup += text(
      `stream ended at t${frames.at(-1).timestep} of ${scheduled} — no result`,
      MARGIN + 2, 92,
      { size: T(16), weight: 600, fill: C.loss },
    );
  }

  // Standing — the score axis is total living wealth; population rides along as
  // the secondary figure because the visible race and the win metric differ.
  const chipW = 470;
  const gap = 14;
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
    markup += text(`${rank + 1}`, x + 26, 70, {
      size: T(30), weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + 62, 60, row.index, 11);
    // The crown is a 3px smudge at the embed floor; the gold border and the rank
    // numeral already say the same thing there.
    if (leader && !state.compact) {
      markup += `<path d="M ${x + 52} 32 l 5 -10 l 5 6.5 l 5 -11 l 5 11 l 5 -6.5 l 5 10 z" `
        + `fill="${C.gold}" stroke="${C.ink}" stroke-width="1.4" stroke-linejoin="round"/>`;
    }
    markup += `<clipPath id="chip-${row.index}"><rect x="${x + 84}" y="14" `
      + `width="${chipW - 250}" height="${BUG_H}"/></clipPath>`;
    markup += `<g clip-path="url(#chip-${row.index})">`
      + text(row.name, x + 84, 52, {
        size: 25, weight: 700, fill: leader ? C.paper : C.paper, spacing: 0.3,
      })
      + `</g>`;
    markup += text(
      `${row.population} settler${row.population === 1 ? "" : "s"} · ${resourceName()}`,
      x + 84, 78,
      { size: T(20), weight: 500, family: F.mono, fill: C.muted },
    );
    // White at the same size out-punches gold, so the LOSING number was winning
    // the eye. The leader is gold and bright; everyone else steps back.
    markup += text(format(row.score), x + chipW - 20, 62, {
      size: T(40), weight: 700, family: F.mono, anchor: "end",
      fill: leader ? C.gold : C.muted,
    });
    markup += text(
      margin === 0 ? "level" : margin > 0 ? `+${format(margin)}` : `\u2212${format(-margin)}`,
      x + chipW - 20, 84,
      {
        size: T(16) + 4, weight: 700, family: F.mono, anchor: "end",
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
  const scheduled = state.maxTimestep || 1;
  const top = y + 46;
  const plotH = height - 76;
  const left = x + 62;
  const plotW = width - left + x - 18;
  const scaleX = (timestep) => left + (timestep / scheduled) * plotW;
  const visible = wealthSeries.filter((point) => point.timestep <= frame.timestep);
  const leadCount = events.filter((event) => event.kind === "lead"
    && event.timestep <= frame.timestep).length;

  let markup = panel(x, y, width, height);
  markup += eyebrow(state.compact ? `Lead, in ${resourceName()}` : "The race", x + 18, y + 26);
  markup += text(
    leadCount === 0 ? "no lead change yet"
      : `${leadCount} lead change${leadCount === 1 ? "" : "s"}`,
    x + width - 18, y + 26,
    { size: T(15), weight: 600, family: F.mono, fill: C.gold, anchor: "end", spacing: 1 },
  );

  if (frame.slots.length !== 2) {
    // Absolute wealth lines — the general case.
    const scaleY = (score) => top + plotH - (score / state.maxWealth) * plotH;
    markup += `<line x1="${left}" y1="${top + plotH}" x2="${left + plotW}" y2="${top + plotH}" `
      + `stroke="rgba(246,234,210,.16)" stroke-width="1"/>`;
    markup += text(format(state.maxWealth), left - 10, top + 6, {
      size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
    });
    frame.slots.forEach((_, slot) => {
      const points = visible
        .map((point) => `${scaleX(point.timestep).toFixed(1)},${scaleY(point.scores[slot] ?? 0).toFixed(1)}`)
        .join(" ");
      if (!points) return;
      markup += `<polyline points="${points}" fill="none" stroke="${seatOf(slot).color}" `
        + `stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
      markup += seatMark(left + 14, top + 16 + slot * 26, slot, 6)
        + text(frame.slots[slot]?.name ?? `Population ${slot + 1}`, left + 28, top + 21 + slot * 26,
          { size: T(17), weight: 600, fill: seatOf(slot).color, outline: 2.8 });
    });
    markup += text("total wealth", left + plotW / 2, top + plotH + 26, {
      size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
    });
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
    + `stroke="rgba(246,234,210,.42)" stroke-width="1.5"/>`;
  markup += text(`+${format(peak)}`, left - 10, top + 12, {
    size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  });
  markup += text("level", left - 10, baseY + 5, {
    size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  });

  // Who currently holds it, stated in words at the head of the band.
  const last = visible.at(-1);
  if (last) {
    const lead = (last.scores[0] ?? 0) - (last.scores[1] ?? 0);
    const leader = lead === 0 ? -1 : (lead > 0 ? 0 : 1);
    const headY = scaleY(lead);
    markup += `<circle cx="${scaleX(last.timestep)}" cy="${headY}" r="6" `
      + `fill="${leader < 0 ? C.muted : seatOf(leader).color}" stroke="${C.ink}" stroke-width="1.8"/>`;
    markup += text(
      leader < 0 ? "level" : `${frame.slots[leader]?.name ?? `Population ${leader + 1}`} ahead`,
      left + 14, top + 20,
      { size: T(19), weight: 700, fill: leader < 0 ? C.muted : seatOf(leader).color, outline: 3 },
    );
  }

  // At the embed floor these land under 7px, so the chart keeps its shape and
  // its headline count and drops the annotations rather than printing a smear.
  if (!state.compact) {
    markup += text("t0", left, y + height - 16, {
      size: 18, weight: 500, family: F.mono, fill: C.dim, outline: 2.4,
    });
    markup += text(`t${scheduled}`, left + plotW, y + height - 16, {
      size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
    });
    markup += text(`lead, in ${resourceName()}`, left + plotW / 2, y + height - 16, {
      size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
    });
  }
  return markup;
}

/** Once the die-off settles, deaths arrive one at a time and a raw feed becomes
 *  five identical rows. Runs of small losses are merged into one line that
 *  carries the whole stretch, so every row in the feed earns its space; a lead
 *  change or a real mass starvation always stands on its own. */
function coalesce(list) {
  const rows = [];
  for (const event of list) {
    const previous = rows.at(-1);
    const mergeable = event.kind === "death" && event.count < 3;
    if (mergeable && previous && previous.kind === "death" && previous.merged) {
      previous.count += event.count;
      previous.until = event.timestep;
      const tally = new Map(previous.bySlot);
      for (const [slot, count] of event.bySlot) {
        tally.set(slot, (tally.get(slot) ?? 0) + count);
      }
      previous.bySlot = [...tally.entries()];
      continue;
    }
    rows.push(mergeable
      ? { ...event, bySlot: [...event.bySlot], merged: true,
          since: event.timestep, until: event.timestep }
      : { ...event });
  }
  return rows;
}

function eventFeed(frame, x, y, width, height) {
  let markup = panel(x, y, width, height);
  markup += eyebrow("What just happened", x + 18, y + 26);
  if (!state.compact) {
    // A hollow settler is a state a viewer can see and could not decode.
    markup += `<circle cx="${x + width - 232}" cy="${y + 20}" r="6" fill="none" `
      + `stroke="${C.muted}" stroke-width="2.2"/>`;
    markup += text("hollow = about to starve", x + width - 218, y + 26, {
      size: 17, weight: 500, fill: C.dim, outline: 2.4,
    });
  }

  const seen = events.filter((event) => event.timestep <= frame.timestep);
  const limit = state.compact ? 3 : 4;
  // Keep the most recent lead change even when routine starvation would push it
  // out: a lead change is the beat this match is actually about.
  const lastLead = [...seen].reverse().find((event) => event.kind === "lead");

  let rowY = y + 58;
  const rowStep = state.compact ? 64 : 54;
  const indent = state.compact ? 124 : 128;

  // A live row, always. Without it the panel could sit on a beat from nine
  // timesteps ago under a heading that promises the present.
  // Only when the feed would otherwise sit on something genuinely old. It used
  // to fire every few timesteps and spend the top slot restating the scorebug.
  const quiet = seen.length === 0
    || frame.timestep - (seen.at(-1).until ?? seen.at(-1).timestep) > 8;
  let slots = limit;
  if (quiet) {
    markup += text(`t${frame.timestep}`, x + 18, rowY + 15, {
      size: T(19), weight: 600, family: F.mono, fill: C.gold,
    });
    markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" `
      + `fill="${C.muted}"/>`;
    markup += text(
      state.compact
        ? `${frame.agents.length} settlers foraging`
        : `${frame.agents.length} settlers still foraging the mountain`,
      x + indent, rowY + 16,
      { size: T(25), weight: 500, fill: C.paper },
    );
    rowY += rowStep;
    slots -= 1;
  }

  // Take the newest beats, then guarantee the most recent lead change a slot —
  // rescuing it and THEN trimming the list sliced off the row just rescued,
  // exactly when the feed was quiet and it was the only thing worth showing.
  let recent = coalesce(seen).slice(-slots).reverse();
  if (lastLead && !recent.some((event) => event.kind === "lead")) {
    recent = [...recent.slice(0, Math.max(0, slots - 1)), { ...lastLead }];
  }

  if (recent.length === 0 && !quiet) {
    markup += text("The settlers spread out across the lattice.", x + 18, y + 62, {
      size: T(24), weight: 500, fill: C.muted,
    });
    return markup;
  }

  for (const event of recent) {
    const fresh = (event.until ?? event.timestep) === frame.timestep;
    const stamp = event.merged && event.until > event.since
      ? `t${event.since}–${event.until}`
      : `t${event.timestep}`;
    markup += text(stamp, x + 18, rowY + 15, {
      size: T(19), weight: 600, family: F.mono, fill: fresh ? C.gold : C.dim,
    });
    if (event.kind === "death") {
      markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" fill="${C.dim}"/>`;
      // No flavour text: an earlier version asserted the losses were at the
      // mountain's edge, which nothing here computes and which the recording
      // does not actually support for the runs it was printed on.
      const shorten = (name) => (state.compact ? name.split(/\s+/).at(-1) : name);
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
      markup += text(
        line,
        x + indent, rowY + 16,
        { size: T(25), weight: 500, fill: fresh ? C.paper : C.muted },
      );
    } else {
      markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" `
        + `fill="${seatOf(event.slot).color}"/>`;
      markup += text(
        `${event.name} takes the lead`,
        x + indent, rowY + 16,
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
  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);
  const population = frame.agents.length;

  let markup = panel(x, y, width, height);
  markup += eyebrow("Nobody programmed this", x + 18, y + 26);

  // Lorenz curve — the signature Sugarscape chart, drawn from the live agents.
  const curveX = x + 18;
  const curveY = y + 44;
  // Leave room for the caption BELOW the square, inside the panel: it used to be
  // sized off the full panel height and punched through the bottom hairline.
  const size = Math.max(40, height - 44 - 40 - 18);
  // The Lorenz curve is the signature chart but the first thing to go at the
  // embed floor: unlabelled and 60px wide it carries nothing a viewer can read.
  const showCurve = !state.compact;
  const wealth = frame.agents
    .map((agent) => Math.max(0, agent.sugar + agent.spice))
    .sort((first, second) => first - second);
  const total = wealth.reduce((sum, value) => sum + value, 0);
  if (showCurve) {
    markup += `<rect x="${curveX}" y="${curveY}" width="${size}" height="${size}" `
      + `fill="rgba(246,234,210,.04)" stroke="rgba(246,234,210,.12)" stroke-width="1"/>`;
    markup += `<line x1="${curveX}" y1="${curveY + size}" x2="${curveX + size}" y2="${curveY}" `
      + `stroke="rgba(246,234,210,.22)" stroke-width="1" stroke-dasharray="4 4"/>`;
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
      { size: 17, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4 });
  }

  // Two readouts, not three: the live population is already on both scorebug
  // chips, so repeating it as "survivors" only crowded the panel. Pairing it
  // with the capacity instead is the reading that means something - the world
  // deciding how many settlers it will carry. The capacity is phrased rather
  // than printed bare, because "57" beside "38 alive of 64" read as a
  // contradiction rather than as a ceiling.
  const readX = state.compact ? curveX : curveX + size + 26;
  // Net change, not a death count - the engine can also add agents - so this
  // is deliberately labelled 'lost' rather than asserting a cause.
  const lost = Math.max(0, state.startingPopulation - population);
  const rows = [
    ["Inequality", gini.toFixed(3),
      gini > 0.4 ? "a few settlers hold almost all of it"
        : gini > 0.28 ? "the richest hold most of it"
          : "spread fairly evenly"],
    ["Settlers alive", `${population}`,
      state.sawStart
        ? (lost > 0 ? `of ${state.startingPopulation} · ${lost} lost` : `of ${state.startingPopulation}`)
        : "joined mid-episode"],
  ];
  let readY = curveY + (state.compact ? 22 : 26);
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
    readY += state.compact ? 124 : 96;
  }
  return markup;
}

function stinger() {
  const event = state.stinger;
  const width = 720;
  const x = BOARD.x + (BOARD.w - width) / 2;
  const y = BOARD.y + BOARD.h * 0.36;
  const color = event.kind === "lead" ? seatOf(event.slot).color : C.loss;
  const headline = event.kind === "lead" ? "LEAD CHANGE" : "DIE-OFF";
  const detail = event.kind === "lead"
    ? `${event.name} moves ahead by ${format(event.margin)}`
    : `${event.count} settlers starved this timestep`;
  return `<g class="stinger">`
    + `<rect x="${x}" y="${y}" width="${width}" height="118" rx="12" fill="rgba(16,12,6,.93)" `
    + `stroke="${color}" stroke-width="2.5"/>`
    + `<rect x="${x}" y="${y}" width="7" height="118" rx="3.5" fill="${color}"/>`
    + text(headline, x + 34, y + 50, { size: 30, weight: 700, fill: color, spacing: 3.2 })
    + text(detail, x + 34, y + 90, { size: 24, weight: 500, fill: C.paper })
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
    : `${winner.name} finishes ${format(margin)} ahead of ${runnerUp?.name ?? "the field"}`
      + ` — a ${((margin / Math.max(1, winner.score)) * 100).toFixed(1)}% margin.${arc}`;
  // Gated, not asserted: the same sentence used to print at any Gini.
  const spread = gini > 0.4
    ? ` A few of them ended up holding almost all the ${resourceName()}.`
    : gini > 0.28
      ? ` The richest of them ended up holding most of the ${resourceName()}.`
      : ` What they held ended up spread fairly evenly.`;
  const context = state.sawStart
    ? `${survivors} of ${state.startingPopulation} settlers survived.${spread}`
    : `${survivors} settlers still standing.${spread}`;

  const cardW = state.compact ? 1500 : 1180;
  const cardH = 580;
  const x = (W - cardW) / 2;
  const y = (H - cardH) / 2;

  let markup = `<g class="endcard">`;
  markup += `<rect x="0" y="0" width="${W}" height="${H}" fill="rgba(10,7,4,.965)"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" `
    + `fill="rgba(31,24,14,.985)"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" fill="none" `
    + `stroke="${C.gold}" stroke-width="2.5"/>`;

  markup += text("SUGARSCAPE", x + 56, y + 54, {
    size: T(24), weight: 700, fill: C.paper, spacing: 5.0,
  });
  markup += eyebrow(tie ? "Final — level" : "Final", x + 56, y + 84);
  markup += seatMark(x + 68, y + 140, winner.index, 21);
  markup += text(winner.name, x + 104, y + 154, { size: T(62), weight: 700, fill: C.paper });
  markup += text(verdict, x + 56, y + 212, { size: T(27), weight: 500, fill: C.gold });
  markup += text(context, x + 56, y + 250, { size: T(22), weight: 500, fill: C.muted });

  let rowY = y + 306;
  for (const [rank, row] of rows.entries()) {
    const leader = rank === 0 && !tie;
    markup += `<rect x="${x + 56}" y="${rowY}" width="${cardW - 112}" height="66" rx="10" `
      + `fill="rgba(20,15,8,.72)" stroke="${leader ? C.gold : C.border}" stroke-width="${leader ? 2 : 1.4}"/>`;
    markup += text(`${rank + 1}`, x + 92, rowY + 44, {
      size: 28, weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + 134, rowY + 33, row.index, 12);
    markup += text(row.name, x + 162, rowY + 42, { size: T(28), weight: 700, fill: C.paper });
    markup += text(`${row.population} alive`, x + cardW - 250, rowY + 42, {
      size: 20, weight: 500, family: F.mono, fill: C.muted, anchor: "end",
    });
    markup += text(format(row.score), x + cardW - 92, rowY + 44, {
      size: T(34), weight: 700, family: F.mono, fill: leader ? C.gold : C.paper, anchor: "end",
    });
    rowY += 78;
  }
  markup += text(
    `Score is all the ${resourceName()} still held by a population's living settlers.`,
    x + 56, y + cardH - 26, { size: T(20), weight: 500, fill: C.muted });
  markup += `</g>`;
  return markup;
}

function defs() {
  return `<defs>
    <linearGradient id="bug-scrim" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="rgba(12,9,5,.92)"/>
      <stop offset="1" stop-color="rgba(12,9,5,0)"/>
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
  const raceH = state.compact ? 288 : 330;
  const feedH = state.compact ? 300 : 300;
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
  if (atEnd) {
    if (spokenVerdict) return;
    spokenVerdict = true;
    commentary.textContent = "";
    const rows = ranked(frame);
    const margin = rows[0].score - (rows[1]?.score ?? 0);
    const changes = events.filter((event) => event.kind === "lead").length;
    verdictLine.textContent = (margin === 0
      ? `Final. ${rows.map((row) => row.name).join(" and ")} finish level on `
        + `${format(rows[0].score)} ${resourceName()}.`
      : `Final. ${rows[0].name} wins with ${format(rows[0].score)} ${resourceName()}, `
        + `${format(margin)} ahead of ${rows[1]?.name ?? "the field"}.`)
      + (state.sawStart
      ? ` ${frame.agents.length} of ${state.startingPopulation} settlers survived,`
      : ` ${frame.agents.length} settlers still standing,`)
      + ` after ${changes} lead change${changes === 1 ? "" : "s"}.`;
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

  const rows = ranked(frame);
  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);
  const standing = rows
    .map((row, rank) => `${rank + 1}. ${row.name}, ${format(row.score)} ${resourceName()},`
      + ` ${row.population} settler${row.population === 1 ? "" : "s"}`)
    .join(". ");
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
    + ` Inequality, as a Gini coefficient, ${gini.toFixed(3)}.`
    + " A hollow settler on the board has less than one timestep of food left.";
}

function currentIndex() {
  return Math.max(0, Math.min(frames.length - 1, Math.floor(state.cursor)));
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
    controls.scrub.value = String(index);
    const span = Math.max(1, frames.length - 1);
    controls.scrub.style.setProperty("--played", `${(index / span) * 100}%`);
    // Mark the lead changes on the timeline itself, so the shape of the match is
    // visible from the transport and not only from the chart.
    if (markedLeads !== events.length) {
      markedLeads = events.length;
      const marks = events
        .filter((event) => event.kind === "lead")
        .map((event) => (event.index / span) * 100);
      controls.scrub.style.setProperty("--marks", marks.length === 0
        ? "none"
        : marks.map((at) => `linear-gradient(${C.gold}, ${C.gold}) ${at}% 0 / 2px 100% no-repeat`)
          .join(", "));
    }
    // A bare "62" tells a screen-reader user nothing; name the unit and the end.
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
    terrainShown = terrainFrame;
    buildTerrain(terrainFrame);
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
controls.scrub.addEventListener("input", () => seek(Number(controls.scrub.value)));
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
  controls.container.hidden = true;
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
  const complete = () => frames.length > 0 && state.maxTimestep > 0
    && frames.at(-1).timestep >= state.maxTimestep;
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
    if (!isRenderableFrame(frame)) return;
    clearTimeout(silence);
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
  for (const frame of payload.frames) recordFrame(frame);
  ready();
  state.finished = true;
  state.live = false;
  state.cursor = 0;
  setPlaying(!reducedMotion);
}

async function boot() {
  setPlaying(!reducedMotion);
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

boot();
