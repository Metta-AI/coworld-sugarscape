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
  dim: "#8a7a62",   // lifted from #6f6250, which measured 3.3:1 on the panel
  border: "#4a3620",
  panel: "rgba(20,15,8,.86)",
  gold: "#e8a838",         // sugar — the world's own accent
  peak: "#ffd97a",
  live: "#7bd88f",
  loss: "#e2703a",
};

// The original assigns palette colours to decision models in order
// (reference/dtl-python/gui.py: palette[0] red, palette[1] blue), so the two
// populations are red and blue exactly as in the model everyone recognises.
// Each hue is lifted slightly from the source so the same colour is legible
// BOTH as a dot on the white plate and as a chip on the dark broadcast panels,
// and each carries a redundant shape so the read never depends on hue alone.
const SEATS = [
  { color: "#f5504a" },   // gui.py palette[0] #FA3232
  { color: "#5a7cff" },   // gui.py palette[1] #3232FA
  { color: "#3aae5a" },   // palette[2] #32FA32
  { color: "#3ec6d8" },   // palette[3] #32FAFA
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
const BOARD = { x: MARGIN, y: TOP_INSET, w: H - TOP_INSET - MARGIN, h: H - TOP_INSET - MARGIN };
const RAIL = { x: BOARD.x + BOARD.w + 26, y: TOP_INSET, w: W - (BOARD.x + BOARD.w + 26) - MARGIN };
RAIL.h = H - TOP_INSET - MARGIN;

// ---------------------------------------------------------------------------
// Tempo — two independent levers (the Agricogla model).
//   animFactor  caps motion so it never plays faster than ANIM_MAX x real time.
//   frameDwellMs floors the auto-advance so speed collapses DEAD TIME between
//   timesteps, never the walk itself.
// ---------------------------------------------------------------------------

const ANIM_MAX = 2;
const BASE_FRAME_MS = 620;
const READ_PAUSE = 150;
const MOTE_MS = 1500;
const STINGER_MS = 2100;
const SPEEDS = [0.5, 1, 2, 4];

function animFactor(speed) {
  return Math.max(1 / Math.max(speed, 0.05), 1 / ANIM_MAX);
}

function frameDwellMs(speed) {
  // The walk between two timesteps is the beat; it must always play in full.
  const walk = BASE_FRAME_MS * animFactor(speed);
  return Math.max(BASE_FRAME_MS / speed, walk + READ_PAUSE);
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const board = document.getElementById("board");
const context = board.getContext("2d");
const hud = document.getElementById("hud");
const notice = document.getElementById("notice");
const controls = {
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
  // Per-cell sugar CAPACITY, accumulated as the running maximum ever observed.
  // The frames carry only what a cell holds right now, but the landform has to
  // persist: without it, the middle of the mountain - which is exactly where
  // the settlers have eaten everything - renders as a dark crater instead of as
  // a harvested peak, and the board looks static once the world reaches its
  // carrying capacity even though cells are being stripped and regrowing.
  capacity: null,
  maxCapacity: 1,
  maxWealth: 1,
  startingPopulation: 0,
  lastDrawnIndex: -1,
  stingerUntil: 0,
  stinger: null,
  hoverCell: -1,
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

function slotOf(agent) {
  return agent.slot >= 0 && agent.slot < SEATS.length ? agent.slot : -1;
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
      bySlot: [...bySlot.entries()],
      agents: lost,
    });
  }

  const before = ranked(previous);
  const after = ranked(frame);
  const tied = after.length > 1 && after[0].score === after[1].score;
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

  const existing = frameIndexByTimestep.get(frame.timestep);
  if (existing !== undefined) {
    frames[existing] = frame;
    return;
  }

  frameIndexByTimestep.set(frame.timestep, frames.length);
  frames.push(frame);
  const index = frames.length - 1;

  if (index === 0) {
    state.startingPopulation = frame.agents.length;
    for (const cell of frame.cells) {
      state.maxSugar = Math.max(state.maxSugar, cell[0]);
      state.maxSpice = Math.max(state.maxSpice, cell[1]);
    }
  }
  if (!state.capacity || state.capacity.length !== frame.cells.length) {
    state.capacity = new Float32Array(frame.cells.length);
  }
  for (let cell = 0; cell < frame.cells.length; cell += 1) {
    const sugar = frame.cells[cell][0];
    if (sugar > state.capacity[cell]) state.capacity[cell] = sugar;
    if (sugar > state.maxCapacity) state.maxCapacity = sugar;
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
  state.finished = false;
  state.lastDrawnIndex = -1;
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
const GRID_HEX = "#c0c0c0";           // gui.py cell outline

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
  terrainContext.fillStyle = `rgb(${EMPTY_HEX.join(",")})`;
  terrainContext.fillRect(0, 0, size, size);

  for (let index = 0; index < frame.cells.length; index += 1) {
    const [sugar, spice] = frame.cells[index];
    if (sugar <= 0 && spice <= 0) continue;
    // cellId = x * height + y (column-major).
    const x = Math.floor(index / frame.height) * cell;
    const y = (index % frame.height) * cell;
    terrainContext.fillStyle = cellColor(sugar, spice);
    terrainContext.fillRect(x, y, Math.ceil(cell), Math.ceil(cell));
  }

  terrainContext.strokeStyle = GRID_HEX;
  terrainContext.lineWidth = Math.max(1, cell * 0.03);
  terrainContext.beginPath();
  for (let line = 1; line < frame.width; line += 1) {
    const at = Math.round(line * cell) + 0.5;
    terrainContext.moveTo(at, 0);
    terrainContext.lineTo(at, size);
  }
  for (let line = 1; line < frame.height; line += 1) {
    const at = Math.round(line * cell) + 0.5;
    terrainContext.moveTo(0, at);
    terrainContext.lineTo(size, at);
  }
  terrainContext.stroke();
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
      // An agent with less than two timesteps of food left is visibly failing.
      starving: agent.sugar < agent.sugarMetabolism * 2
        || (agent.spiceMetabolism > 0 && agent.spice < agent.spiceMetabolism * 2),
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
    context.strokeStyle = C.loss;
    context.lineWidth = Math.max(1.2, cell * 0.20 * (1 - age));
    context.beginPath();
    context.arc(mote.px, mote.py, cell * (0.32 + age * 1.05), 0, Math.PI * 2);
    context.stroke();
  }
  context.globalAlpha = 1;

  /* Settlers are plain filled circles, as in the original renderer
   * (reference/dtl-python/gui.py draws create_oval with outline=""). Sized by
   * wealth, and drawn hollow when a settler is within two timesteps of
   * starving so the die-off is visible before it happens. */
  const bodies = interpolate(previous, frame, t);
  const radius = cell * 0.31;
  for (const body of bodies) {
    const seat = SEATS[body.slot] ?? SEATS[0];
    const size = radius * (0.82 + 0.36 * Math.min(1, Math.log10(1 + body.wealth) / 2.4));
    context.beginPath();
    context.arc(body.px, body.py, size, 0, Math.PI * 2);
    if (body.starving) {
      context.fillStyle = "rgba(251,248,240,.72)";
      context.fill();
      context.lineWidth = Math.max(1, cell * 0.10);
      context.strokeStyle = seat.color;
      context.stroke();
    } else {
      context.fillStyle = seat.color;
      context.fill();
    }
  }

  if (state.hoverCell >= 0 && state.hoverCell < frame.cells.length) {
    const position = cellPosition(frame, state.hoverCell);
    context.strokeStyle = C.peak;
    context.lineWidth = 2;
    context.strokeRect(
      BOARD.x + position.x * cell,
      BOARD.y + position.y * cell,
      cell,
      cell,
    );
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

/** Every label gets a fat warm-ink outline so it survives scaling to the 360px
 *  embed floor over busy terrain. */
function text(content, x, y, options = {}) {
  const {
    size = 20, weight = 500, fill = C.paper, family = F.display,
    anchor = "start", spacing = 0, outline = 3.4, opacity = 1,
  } = options;
  return `<text x="${x}" y="${y}" font-family="${family}" font-size="${size}" `
    + `font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" `
    + `letter-spacing="${spacing}" opacity="${opacity}" `
    + `paint-order="stroke" stroke="${C.ink}" stroke-width="${outline}" `
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
  const seat = SEATS[slot] ?? SEATS[0];
  return `<circle cx="${x}" cy="${y}" r="${radius}" fill="${seat.color}" `
    + `stroke="${C.ink}" stroke-width="1.6"/>`;
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
  markup += text("two policies farm one sugar mountain · most sugar wins",
    MARGIN + 2, 66, { size: 16, weight: 500, fill: C.muted });

  // Clock — counts to the SCHEDULED end of the match, so an early extinction
  // freezes short of the buzzer instead of always landing on the last tick.
  markup += panel(MARGIN + 476, 14, clockW, BUG_H);
  markup += eyebrow("Timestep", MARGIN + 494, 46);
  markup += text(`${frame.timestep}`, MARGIN + 494, 84, {
    size: 40, weight: 600, family: F.mono, fill: C.paper,
  });
  markup += text(` / ${scheduled}`, MARGIN + 494 + String(frame.timestep).length * 25, 84, {
    size: 24, weight: 500, family: F.mono, fill: C.muted,
  });
  const barX = MARGIN + 654;
  const barW = clockW - 196;
  markup += `<rect x="${barX}" y="60" width="${barW}" height="9" rx="4.5" fill="rgba(246,234,210,.14)"/>`;
  markup += `<rect x="${barX}" y="60" width="${Math.max(3, barW * progress)}" height="9" rx="4.5" fill="${C.gold}"/>`;
  // FINAL belongs to where the CURSOR is, not to whether the stream has ended:
  // scrubbing back into the middle of a finished episode is mid-match again.
  const atEnd = state.finished && Math.round(state.cursor) >= frames.length - 1;
  markup += text(atEnd ? "FINAL" : `${Math.round(progress * 100)}%`, barX + barW, 46, {
    size: 16, weight: 700, family: F.mono, anchor: "end",
    fill: atEnd ? C.gold : C.muted, spacing: 1.4,
  });

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
    markup += `<rect x="${x}" y="14" width="${chipW}" height="${BUG_H}" rx="10" `
      + `fill="${C.panel}" stroke="${leader ? C.gold : SEATS[row.index].color}" `
      + `stroke-width="${leader ? 2.5 : 1.5}"/>`;
    markup += text(`${rank + 1}`, x + 26, 70, {
      size: 30, weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + 62, 60, row.index, 11);
    if (leader) {
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
    markup += text(`${row.population} settler${row.population === 1 ? "" : "s"}`, x + 84, 78, {
      size: 20, weight: 500, family: F.mono, fill: C.muted,
    });
    markup += text(format(row.score), x + chipW - 20, 62, {
      size: 40, weight: 700, family: F.mono, anchor: "end",
      fill: leader ? C.gold : C.paper,
    });
    markup += text(
      margin === 0 ? "level" : margin > 0 ? `+${format(margin)}` : `${format(margin)}`,
      x + chipW - 20, 84,
      {
        size: 16, weight: 600, family: F.mono, anchor: "end",
        fill: margin > 0 ? C.live : C.muted,
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
  markup += eyebrow("The race", x + 18, y + 26);
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
      markup += `<polyline points="${points}" fill="none" stroke="${SEATS[slot].color}" `
        + `stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
    });
    markup += text("total wealth", left + plotW / 2, top + plotH + 26, {
      size: T(18), weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
    });
    return markup;
  }

  // Diverging lead margin. The axis is the largest gap the whole episode ever
  // reaches, so the curve never rescales under the viewer as it plays.
  const peak = Math.max(
    12,
    ...wealthSeries.map((point) => Math.abs((point.scores[0] ?? 0) - (point.scores[1] ?? 0))),
  );
  const zeroY = top + plotH / 2;
  const scaleY = (margin) => zeroY - (margin / peak) * (plotH / 2);

  markup += `<rect x="${left}" y="${top}" width="${plotW}" height="${plotH / 2}" `
    + `fill="${SEATS[0].color}" opacity=".05"/>`;
  markup += `<rect x="${left}" y="${zeroY}" width="${plotW}" height="${plotH / 2}" `
    + `fill="${SEATS[1].color}" opacity=".05"/>`;

  for (const event of events) {
    if (event.kind !== "lead" || event.timestep > frame.timestep) continue;
    markup += `<line x1="${scaleX(event.timestep)}" y1="${top}" `
      + `x2="${scaleX(event.timestep)}" y2="${top + plotH}" `
      + `stroke="${C.gold}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".6"/>`;
  }

  const points = visible.map((point) => ({
    x: scaleX(point.timestep),
    y: scaleY((point.scores[0] ?? 0) - (point.scores[1] ?? 0)),
  }));
  if (points.length > 0) {
    const path = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    // Fill toward the zero line so the shaded side names the leader at a glance.
    markup += `<clipPath id="race-above"><rect x="${left}" y="${top}" width="${plotW}" height="${plotH / 2}"/></clipPath>`;
    markup += `<clipPath id="race-below"><rect x="${left}" y="${zeroY}" width="${plotW}" height="${plotH / 2}"/></clipPath>`;
    const area = `${points[0].x.toFixed(1)},${zeroY} ${path} ${points.at(-1).x.toFixed(1)},${zeroY}`;
    markup += `<polygon points="${area}" fill="${SEATS[0].color}" opacity=".34" clip-path="url(#race-above)"/>`;
    markup += `<polygon points="${area}" fill="${SEATS[1].color}" opacity=".34" clip-path="url(#race-below)"/>`;
    markup += `<polyline points="${path}" fill="none" stroke="${C.paper}" stroke-width="2.4" `
      + `stroke-linejoin="round" stroke-linecap="round"/>`;
    const last = points.at(-1);
    markup += `<circle cx="${last.x}" cy="${last.y}" r="6" fill="${C.paper}" `
      + `stroke="${C.ink}" stroke-width="1.8"/>`;
  }

  markup += `<line x1="${left}" y1="${zeroY}" x2="${left + plotW}" y2="${zeroY}" `
    + `stroke="rgba(246,234,210,.42)" stroke-width="1.5"/>`;
  // Each end of the axis names WHOSE lead it measures. A bare "+120" printed at
  // both ends made the scale unreadable, and a floating "Population A ahead"
  // inside the plot read as a claim about the present rather than a label for
  // that half - so it contradicted the scorebug whenever A was behind.
  const axisEnd = (slot, baseline) => seatMark(left + 12, baseline - 5, slot, 6)
    + text(`+${format(peak)}`, left + 26, baseline, {
      size: T(17), weight: 600, family: F.mono, fill: SEATS[slot].color, outline: 2.8,
    });
  markup += axisEnd(0, top + 18);
  markup += axisEnd(1, top + plotH - 8);
  if (!state.compact) {
    markup += text("level", left - 10, zeroY + 5, {
      size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
    });
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
    markup += text("lead, in sugar", left + plotW / 2, y + height - 16, {
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
      continue;
    }
    rows.push(mergeable
      ? { ...event, merged: true, since: event.timestep, until: event.timestep }
      : { ...event });
  }
  return rows;
}

function eventFeed(frame, x, y, width, height) {
  let markup = panel(x, y, width, height);
  markup += eyebrow("What just happened", x + 18, y + 26);

  const seen = events.filter((event) => event.timestep <= frame.timestep);
  const limit = state.compact ? 3 : 4;
  // Keep the most recent lead change even when routine starvation would push it
  // out: a lead change is the beat this match is actually about.
  const lastLead = [...seen].reverse().find((event) => event.kind === "lead");
  let recent = coalesce(seen).slice(-limit).reverse();
  if (lastLead && !recent.some((event) => event.kind === "lead")) {
    recent = [...recent.slice(0, limit - 1), { ...lastLead }];
  }

  let rowY = y + 58;
  const rowStep = state.compact ? 64 : 54;
  const indent = state.compact ? 124 : 128;

  // A live row, always. Without it the panel could sit on a beat from nine
  // timesteps ago under a heading that promises the present.
  const rows = ranked(frame);
  const margin = rows[0].score - (rows[1]?.score ?? 0);
  const quiet = seen.length === 0
    || frame.timestep - (seen.at(-1).until ?? seen.at(-1).timestep) > 2;
  if (quiet) {
    markup += text(`t${frame.timestep}`, x + 18, rowY + 15, {
      size: T(19), weight: 600, family: F.mono, fill: C.gold,
    });
    markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" `
      + `fill="${C.muted}"/>`;
    markup += text(
      margin === 0
        ? (state.compact
          ? `level · ${frame.agents.length} alive`
          : `level at ${format(rows[0].score)} — ${frame.agents.length} settlers foraging`)
        : (state.compact
          ? `${rows[0].name} +${format(margin)} · ${frame.agents.length} alive`
          : `${rows[0].name} leads by ${format(margin)} — ${frame.agents.length} settlers foraging`),
      x + indent, rowY + 16,
      { size: T(25), weight: 500, fill: C.paper },
    );
    rowY += rowStep;
    recent = recent.slice(0, limit - 1);
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
      markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" fill="${C.loss}"/>`;
      const detail = state.compact
        ? ""
        : event.merged
          ? "the mountain thins the edges"
          : event.bySlot
            .filter(([slot]) => slot >= 0)
            .map(([slot, count]) => `${count} ${frame.slots[slot]?.name ?? `slot ${slot}`}`)
            .join(", ");
      markup += text(
        `${event.count} starved${detail ? ` — ${detail}` : ""}`,
        x + indent, rowY + 16,
        { size: T(25), weight: 500, fill: fresh ? C.paper : C.muted },
      );
    } else {
      markup += `<rect x="${x + indent - 16}" y="${rowY - 2}" width="4" height="${T(24)}" rx="2" `
        + `fill="${SEATS[event.slot].color}"/>`;
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

/** The readouts that make Sugarscape's famous emergent results legible: an
 *  inequality curve nobody programmed, and a carrying capacity the world
 *  imposes on its own population. */
function emergence(frame, x, y, width, height) {
  const stats = frame.stats ?? {};
  const gini = Number(stats.giniCoefficient ?? 0);
  const capacity = Number(stats.carryingCapacity ?? 0);
  const population = frame.agents.length;

  let markup = panel(x, y, width, height);
  markup += eyebrow("Emergence", x + 18, y + 26);

  // Lorenz curve — the signature Sugarscape chart, drawn from the live agents.
  const size = height - 60;
  const curveX = x + 18;
  const curveY = y + 42;
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
    markup += text("poorest → richest", curveX + size / 2, curveY + size + 20,
      { size: 17, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4 });
  }

  // Two readouts, not three: the live population is already on both scorebug
  // chips, so repeating it as "survivors" only crowded the panel. Pairing it
  // with the capacity instead is the reading that means something - the world
  // deciding how many settlers it will carry. The capacity is phrased rather
  // than printed bare, because "57" beside "38 alive of 64" read as a
  // contradiction rather than as a ceiling.
  const readX = state.compact ? curveX : curveX + size + 26;
  const rows = [
    ["Gini", gini.toFixed(3),
      gini > 0.4 ? "sharply unequal" : gini > 0.28 ? "unequal" : "fairly even"],
    ["Carrying capacity", format(capacity),
      `settlers the world will carry · ${population} alive`],
  ];
  let readY = curveY + (state.compact ? 6 : 26);
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
    readY += state.compact ? 132 : 96;
  }
  return markup;
}

function stinger() {
  const event = state.stinger;
  const width = 720;
  const x = BOARD.x + (BOARD.w - width) / 2;
  const y = BOARD.y + BOARD.h * 0.36;
  const color = event.kind === "lead" ? SEATS[event.slot].color : C.loss;
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

  const verdict = tie
    ? `${winner.name} and ${runnerUp.name} finish level on ${format(winner.score)}.`
    : `${winner.name} finishes ${format(margin)} ahead of ${runnerUp?.name ?? "the field"}`
      + ` — a ${((margin / Math.max(1, winner.score)) * 100).toFixed(1)}% margin.`;
  const context = `${survivors} of ${state.startingPopulation} settlers survived the mountain;`
    + ` wealth ended at a Gini of ${gini.toFixed(2)}.`;

  const cardW = state.compact ? 1500 : 1180;
  const cardH = 580;
  const x = (W - cardW) / 2;
  const y = (H - cardH) / 2;

  let markup = `<g class="endcard">`;
  markup += `<rect x="0" y="0" width="${W}" height="${H}" fill="rgba(10,7,4,.90)"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" `
    + `fill="rgba(16,12,6,.97)"/>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" fill="none" `
    + `stroke="${C.gold}" stroke-width="2.5"/>`;

  markup += text("SUGARSCAPE", x + 56, y + 54, {
    size: T(21), weight: 700, fill: C.muted, spacing: 4.4,
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
  markup += text("Score is the final living population's total sugar plus spice.",
    x + 56, y + cardH - 26, { size: T(20), weight: 500, fill: C.dim });
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
  const atEnd = state.finished && Math.round(state.cursor) >= frames.length - 1;
  const signature = live ? `stinger:${state.stinger.index}:${state.stinger.kind}` : "";
  const full = `${signature}|${atEnd}`;
  if (full === beatsSignature) return;
  beatsSignature = full;
  beatsLayer.innerHTML = (live ? stinger() : "") + (atEnd ? endCard(frame) : "");
}

function drawHud(frame, index) {
  const atEnd = state.finished && Math.round(state.cursor) >= frames.length - 1;
  const signature = `${index}|${atEnd}|${state.speed}`;
  if (signature === standingsSignature) return;
  standingsSignature = signature;

  const railGap = 22;
  const raceH = 330;
  const feedH = 300;
  const emergenceH = RAIL.h - raceH - feedH - railGap * 2;
  let markup = raceChart(frame, RAIL.x, RAIL.y, RAIL.w, raceH);
  markup += eventFeed(frame, RAIL.x, RAIL.y + raceH + railGap, RAIL.w, feedH);
  markup += emergence(frame, RAIL.x, RAIL.y + raceH + feedH + railGap * 2, RAIL.w, emergenceH);
  markup += scorebug(frame);
  standingsLayer.innerHTML = markup;
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

let lastTick = 0;

function currentIndex() {
  return Math.max(0, Math.min(frames.length - 1, Math.floor(state.cursor)));
}

function onFrameEntered(index, now) {
  const frame = frames[index];
  if (!frame) return;
  buildTerrain(frame);

  const cell = BOARD.w / frame.width;
  for (const event of events) {
    if (event.index !== index) continue;
    if (event.kind === "death") {
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
    // stinger when it is big enough to matter.
    if (event.kind === "lead" || (event.kind === "death" && event.count >= 3)) {
      if (!state.stinger || event.kind === "lead") {
        state.stinger = event;
        state.stingerUntil = now + STINGER_MS * animFactor(state.speed);
      }
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
    // A bare "62" tells a screen-reader user nothing; name the unit and the end.
    controls.scrub.setAttribute(
      "aria-valuetext",
      `timestep ${frames[index].timestep} of ${state.maxTimestep || frames.length - 1}`,
    );
  }

  const frame = frames[index];
  const previous = index > 0 ? frames[index - 1] : null;
  const fraction = Math.max(0, Math.min(1, state.cursor - index));
  // Interpolate from the PREVIOUS frame into this one, so the settler arrives
  // exactly as its recorded state lands rather than leaving it early.
  drawBoard(frame, previous, previous ? fraction : 1, now);
  drawHud(frame, index);
  drawBeats(frame, now);
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

board.addEventListener("mousemove", (event) => {
  const frame = frames[currentIndex()];
  if (!frame) return;
  const bounds = board.getBoundingClientRect();
  const x = ((event.clientX - bounds.left) / bounds.width) * W;
  const y = ((event.clientY - bounds.top) / bounds.height) * H;
  const cell = BOARD.w / frame.width;
  const column = Math.floor((x - BOARD.x) / cell);
  const row = Math.floor((y - BOARD.y) / cell);
  state.hoverCell = column >= 0 && column < frame.width && row >= 0 && row < frame.height
    ? column * frame.height + row
    : -1;
});
board.addEventListener("mouseleave", () => { state.hoverCell = -1; });

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

function fail(message) {
  notice.textContent = message;
}

/** Derive the spectator socket from the page's OWN path. The Observatory serves
 *  this document at `<prefix>/client/replay` through the k8s proxy, where the
 *  sibling socket is `<prefix>/replay` — an absolute `/replay` would resolve off
 *  the prefix and black-screen the embed. */
function socketUrl() {
  const path = location.pathname.replace(/\/+$/, "");
  const match = /^(.*)\/clients?\/(replay|global)$/.exec(path);
  const suffix = match ? `${match[1]}/${match[2]}` : "/global";
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
  const markFinished = () => {
    if (frames.length === 0) return;
    state.live = false;
    state.finished = true;
  };
  socket.addEventListener("open", () => { notice.textContent = ""; });
  socket.addEventListener("message", (event) => {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch (error) {
      fail("The episode stream sent a frame this viewer could not read.");
      return;
    }
    if (!frame || !Array.isArray(frame.cells) || !Array.isArray(frame.agents)) return;
    if (frames.length === 0) state.live = true;
    recordFrame(frame);
    // The server streams recorded frames back to back and then goes quiet; a
    // pause means the episode is over and playback should own the timeline.
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      markFinished();
      state.cursor = 0;
      setPlaying(true);
    }, 1200);
  });
  socket.addEventListener("close", () => {
    clearTimeout(idleTimer);
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
    fail(`Could not load the replay at ${url}.`);
    return;
  }
  if (!payload || payload.format !== "sugarscape.replay.v1" || !Array.isArray(payload.frames)) {
    fail("That file is not a sugarscape.replay.v1 recording.");
    return;
  }
  if (payload.frames.length === 0) {
    fail("This replay recorded no frames.");
    return;
  }
  const scheduled = Number(payload.config?.timesteps ?? 0);
  if (scheduled > 0) state.maxTimestep = scheduled;
  for (const frame of payload.frames) recordFrame(frame);
  state.finished = true;
  state.live = false;
  state.cursor = 0;
  setPlaying(true);
}

async function boot() {
  setPlaying(true);
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
}

boot();
