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
  dim: "#6f6250",
  border: "#4a3620",
  panel: "rgba(20,15,8,.86)",
  gold: "#e8a838",         // sugar — the world's own accent
  peak: "#ffd97a",
  live: "#7bd88f",
  loss: "#e2703a",
};

// The terrain owns the warm half of the wheel, so the competitors take the cool
// half. Each also carries a redundant shape so the read never depends on hue.
const SEATS = [
  { color: "#3fc1d8", shape: "circle" },
  { color: "#f0568a", shape: "square" },
  { color: "#b6e36b", shape: "triangle" },
  { color: "#c69bf0", shape: "diamond" },
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
};

const art = {};

// ---------------------------------------------------------------------------
// Assets
// ---------------------------------------------------------------------------

function loadImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("asset failed to decode"));
    image.src = source;
  });
}

async function loadAssets() {
  const names = [
    "terrain_barren", "terrain_sugar_1", "terrain_sugar_2",
    "terrain_sugar_3", "terrain_sugar_4", "endcard",
  ];
  const images = await Promise.all(names.map((name) => loadImage(ART[name])));
  names.forEach((name, index) => { art[name] = images[index]; });
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
    for (const cell of frame.cells) state.maxSugar = Math.max(state.maxSugar, cell[0]);
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

const terrain = document.createElement("canvas");
const terrainContext = terrain.getContext("2d");
const maskCanvas = document.createElement("canvas");
const maskContext = maskCanvas.getContext("2d", { willReadFrequently: true });
const scratch = document.createElement("canvas");
const scratchContext = scratch.getContext("2d");
const patterns = new Map();

function smoothstep(edge0, edge1, value) {
  const t = Math.max(0, Math.min(1, (value - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** A repeating texture at native size tiles visibly across the board, so each
 *  layer is scaled up and offset by a different amount — the seams of the five
 *  layers then never coincide and the ground reads as continuous. */
const PATTERN_TRANSFORM = new Map([
  ["terrain_barren", { scale: 1.45, x: 0, y: 0 }],
  ["terrain_sugar_1", { scale: 1.30, x: 137, y: 61 }],
  ["terrain_sugar_2", { scale: 1.55, x: 43, y: 191 }],
  ["terrain_sugar_3", { scale: 1.35, x: 229, y: 113 }],
  ["terrain_sugar_4", { scale: 1.60, x: 91, y: 247 }],
]);

function patternFor(image, target) {
  if (!patterns.has(image)) {
    const pattern = target.createPattern(image, "repeat");
    const name = Object.keys(art).find((key) => art[key] === image);
    const transform = PATTERN_TRANSFORM.get(name);
    if (transform && typeof pattern.setTransform === "function") {
      pattern.setTransform(new DOMMatrix()
        .translate(transform.x, transform.y)
        .scale(transform.scale));
    }
    patterns.set(image, pattern);
  }
  return patterns.get(image);
}

/** Paint `image` over the terrain through a per-cell coverage mask. Building the
 *  mask at lattice resolution and letting the canvas upscale it gives a
 *  continuous landform rather than 1024 visibly tiled squares. */
function layer(frame, image, edge0, edge1) {
  const { width, height } = frame;
  const data = maskContext.createImageData(width, height);
  let visible = false;
  for (let index = 0; index < frame.cells.length; index += 1) {
    const density = frame.cells[index][0] / state.maxSugar;
    const alpha = Math.round(255 * smoothstep(edge0, edge1, density));
    if (alpha > 0) visible = true;
    // cellId = x * height + y (column-major), so decode before writing rows.
    const x = Math.floor(index / height);
    const y = index % height;
    data.data[(y * width + x) * 4 + 3] = alpha;
  }
  if (!visible) return;
  maskContext.putImageData(data, 0, 0);

  scratchContext.setTransform(1, 0, 0, 1, 0, 0);
  scratchContext.clearRect(0, 0, scratch.width, scratch.height);
  scratchContext.imageSmoothingEnabled = true;
  scratchContext.imageSmoothingQuality = "high";
  scratchContext.drawImage(maskCanvas, 0, 0, scratch.width, scratch.height);
  scratchContext.globalCompositeOperation = "source-in";
  scratchContext.fillStyle = patternFor(image, scratchContext);
  scratchContext.fillRect(0, 0, scratch.width, scratch.height);
  scratchContext.globalCompositeOperation = "source-over";

  terrainContext.drawImage(scratch, 0, 0);
}

/** A raking light from the upper left, computed from the CAPACITY field's own
 *  gradient — the landform, not the current stock. Lighting the live sugar
 *  instead made the mountain change shape as it was eaten, so the middle (where
 *  every settler is standing, stripped to zero) sank into a crater. Lit off
 *  capacity, the massif holds its form and the sugar drains out of it. */
function relief() {
  const { width, height } = maskCanvas;
  const data = maskContext.createImageData(width, height);
  const at = (x, y) => state.capacity[
    Math.max(0, Math.min(width - 1, x)) * height + Math.max(0, Math.min(height - 1, y))
  ];
  const lx = -0.62, ly = -0.58, lz = 0.53;
  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) {
      const dx = (at(x + 1, y) - at(x - 1, y)) / (2 * state.maxCapacity);
      const dy = (at(x, y + 1) - at(x, y - 1)) / (2 * state.maxCapacity);
      const scale = 3.1;
      const length = Math.hypot(-dx * scale, -dy * scale, 1);
      const shade = (-dx * scale * lx + -dy * scale * ly + lz) / length;
      const value = Math.max(0, Math.min(255, Math.round(128 + (shade - 0.53) * 340)));
      const offset = (y * width + x) * 4;
      data.data[offset] = value;
      data.data[offset + 1] = value;
      data.data[offset + 2] = value;
      data.data[offset + 3] = 255;
    }
  }
  maskContext.putImageData(data, 0, 0);
  const paint = destination();
  paint.globalCompositeOperation = "soft-light";
  paint.imageSmoothingEnabled = true;
  paint.imageSmoothingQuality = "high";
  paint.drawImage(maskCanvas, 0, 0, terrain.width, terrain.height);
  paint.globalCompositeOperation = "source-over";
}

/** Capacity isolines — the contour read the art direction is named for, and the
 *  thing that keeps the peak legible as a peak once its sugar has been eaten.
 *  Marching squares over the capacity field, one line per whole unit. */
function contours() {
  const { width, height } = maskCanvas;
  const cell = terrain.width / width;
  const at = (x, y) => state.capacity[
    Math.max(0, Math.min(width - 1, x)) * height + Math.max(0, Math.min(height - 1, y))
  ];
  const paint = destination();
  paint.lineWidth = Math.max(1, cell * 0.055);
  paint.lineJoin = "round";
  for (let level = 1; level <= state.maxCapacity; level += 1) {
    paint.strokeStyle = `rgba(60,42,22,${0.20 + level * 0.055})`;
    paint.beginPath();
    for (let x = 0; x < width - 1; x += 1) {
      for (let y = 0; y < height - 1; y += 1) {
        // Corner values of this lattice square, clockwise from top-left.
        const corners = [at(x, y), at(x + 1, y), at(x + 1, y + 1), at(x, y + 1)];
        const edges = [];
        for (let side = 0; side < 4; side += 1) {
          const a = corners[side];
          const b = corners[(side + 1) % 4];
          if ((a >= level) === (b >= level)) continue;
          const t = (level - a) / (b - a);
          // Interpolate along the side, in board pixels.
          const points = [
            [x + t, y], [x + 1, y + t], [x + 1 - t, y + 1], [x, y + 1 - t],
          ][side];
          edges.push([(points[0] + 0.5) * cell, (points[1] + 0.5) * cell]);
        }
        for (let edge = 0; edge + 1 < edges.length; edge += 2) {
          paint.moveTo(edges[edge][0], edges[edge][1]);
          paint.lineTo(edges[edge + 1][0], edges[edge + 1][1]);
        }
      }
    }
    paint.stroke();
  }
}

function drawLattice(frame) {
  const cell = terrain.width / frame.width;
  terrainContext.strokeStyle = "rgba(42,31,18,.26)";
  terrainContext.lineWidth = 1;
  terrainContext.beginPath();
  for (let x = 1; x < frame.width; x += 1) {
    terrainContext.moveTo(Math.round(x * cell) + 0.5, 0);
    terrainContext.lineTo(Math.round(x * cell) + 0.5, terrain.height);
  }
  for (let y = 1; y < frame.height; y += 1) {
    terrainContext.moveTo(0, Math.round(y * cell) + 0.5);
    terrainContext.lineTo(terrain.width, Math.round(y * cell) + 0.5);
  }
  terrainContext.stroke();
}

/** Lift the ground in proportion to CAPACITY, before any sugar is painted.
 *
 *  Height has to carry brightness on its own. The settlers strip the summit
 *  bare, so keying value only to the sugar standing there made the top of the
 *  mountain the DARKEST part of it and the hero object read as a crater. With
 *  the lift, high land looks high even when picked clean, and the sugar reads
 *  as gold lying on top of it. */
function elevationLift() {
  const { width, height } = maskCanvas;
  const data = maskContext.createImageData(width, height);
  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) {
      const elevation = state.capacity[x * height + y] / state.maxCapacity;
      const offset = (y * width + x) * 4;
      data.data[offset] = 214;
      data.data[offset + 1] = 178;
      data.data[offset + 2] = 124;
      data.data[offset + 3] = Math.round(255 * Math.min(1, elevation ** 0.75) * 0.72);
    }
  }
  maskContext.putImageData(data, 0, 0);
  const paint = destination();
  paint.globalCompositeOperation = "screen";
  paint.imageSmoothingEnabled = true;
  paint.imageSmoothingQuality = "high";
  paint.drawImage(maskCanvas, 0, 0, terrain.width, terrain.height);
  paint.globalCompositeOperation = "source-over";
}

/* The LANDFORM is a pure function of capacity, which never changes once the
 * episode has been read — so it is built once and cached. It used to be rebuilt
 * on every timestep along with the sugar, and the marching-squares contours plus
 * three full-board composites were a ~100ms stall every 770ms: the jitter. */
const landform = document.createElement("canvas");
const landformContext = landform.getContext("2d");
let landformKey = "";

function buildLandform(frame) {
  const size = Math.round(BOARD.w * RENDER_SCALE);
  const key = `${size}:${frame.width}x${frame.height}:${state.maxCapacity}:${frames.length}`;
  if (key === landformKey) return;
  landformKey = key;
  landform.width = landform.height = size;
  landformContext.setTransform(1, 0, 0, 1, 0, 0);
  landformContext.clearRect(0, 0, size, size);
  landformContext.fillStyle = patternFor(art.terrain_barren, landformContext);
  landformContext.fillRect(0, 0, size, size);
  const target = terrainContext;
  // relief/elevationLift/contours draw through the shared terrain context, so
  // point them at the landform for this one build.
  drawInto(landformContext, () => { elevationLift(); relief(); contours(); });
  void target;
}

/** Run the terrain painters against a different destination canvas. */
let terrainTarget = null;
function drawInto(context, paint) {
  terrainTarget = context;
  paint();
  terrainTarget = null;
}
function destination() {
  return terrainTarget ?? terrainContext;
}

/** The sugar standing on each cell, right now.
 *
 *  This is the single most important thing on the board — it is what both
 *  policies are competing for and what their settlers are standing on to eat.
 *  Blending it as four soft painterly layers made the massif pretty and made
 *  the actual per-cell resource unreadable, so it is drawn as discrete lattice
 *  cells with a quantised amber ramp: crisp squares, one clear step per unit,
 *  exactly how the model is drawn in the literature. */
const sugarLayer = document.createElement("canvas");
const sugarContext = sugarLayer.getContext("2d");
const SUGAR_RAMP = [
  null,                    // 0 — bare ground shows through
  [176, 118, 46, 0.62],
  [214, 158, 58, 0.78],
  [240, 194, 88, 0.90],
  [255, 224, 148, 0.97],
];

function drawSugar(frame) {
  const { width, height } = frame;
  if (sugarLayer.width !== width) {
    sugarLayer.width = width;
    sugarLayer.height = height;
  }
  const image = sugarContext.createImageData(width, height);
  for (let index = 0; index < frame.cells.length; index += 1) {
    const sugar = frame.cells[index][0];
    if (sugar <= 0) continue;
    const step = SUGAR_RAMP[Math.min(SUGAR_RAMP.length - 1, Math.round(sugar))]
      ?? SUGAR_RAMP[SUGAR_RAMP.length - 1];
    if (!step) continue;
    // cellId = x * height + y (column-major), so decode before writing rows.
    const offset = ((index % height) * width + Math.floor(index / height)) * 4;
    image.data[offset] = step[0];
    image.data[offset + 1] = step[1];
    image.data[offset + 2] = step[2];
    image.data[offset + 3] = Math.round(255 * step[3]);
  }
  sugarContext.putImageData(image, 0, 0);
}

function buildTerrain(frame) {
  const size = Math.round(BOARD.w * RENDER_SCALE);
  if (terrain.width !== size) {
    terrain.width = terrain.height = size;
    scratch.width = scratch.height = size;
    patterns.clear();
    landformKey = "";
  }
  if (maskCanvas.width !== frame.width) {
    maskCanvas.width = frame.width;
    maskCanvas.height = frame.height;
    landformKey = "";
  }
  buildLandform(frame);
  drawSugar(frame);

  terrainContext.setTransform(1, 0, 0, 1, 0, 0);
  terrainContext.clearRect(0, 0, size, size);
  terrainContext.imageSmoothingEnabled = true;
  terrainContext.drawImage(landform, 0, 0);
  // Crisp square cells: the resource read must not be blurred away.
  terrainContext.imageSmoothingEnabled = false;
  terrainContext.drawImage(sugarLayer, 0, 0, size, size);
  terrainContext.imageSmoothingEnabled = true;
  drawLattice(frame);
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

  // The board sits slightly proud of the surround so the eye goes to it.
  context.save();
  context.shadowColor = "rgba(0,0,0,.55)";
  context.shadowBlur = 26;
  context.shadowOffsetY = 6;
  context.fillStyle = C.ink;
  context.fillRect(BOARD.x, BOARD.y, BOARD.w, BOARD.h);
  context.restore();
  context.drawImage(terrain, BOARD.x, BOARD.y, BOARD.w, BOARD.h);

  // A settler starving leaves an expanding ring where it stood.
  for (let index = motes.length - 1; index >= 0; index -= 1) {
    const mote = motes[index];
    const age = (now - mote.born) / (MOTE_MS * animFactor(state.speed));
    if (age >= 1) { motes.splice(index, 1); continue; }
    context.globalAlpha = (1 - age) * 0.85;
    context.strokeStyle = C.loss;
    context.lineWidth = Math.max(1, cell * 0.16 * (1 - age));
    context.beginPath();
    context.arc(mote.px, mote.py, cell * (0.32 + age * 1.05), 0, Math.PI * 2);
    context.stroke();
  }
  context.globalAlpha = 1;

  /* Settlers are DOTS.
   *
   * They were painterly meeple sprites for a while. They looked like stickers
   * pasted on the terrain, they aliased badly when scaled to a ~9px cell, and
   * they buried the one thing a viewer needs from an agent-based model: where
   * the population IS and which policy owns it. A flat disc with a warm-ink
   * outline reads at every size, never aliases, and is how this model has been
   * drawn since 1996. */
  const bodies = interpolate(previous, frame, t);
  const radius = cell * 0.30;
  context.lineWidth = Math.max(0.8, cell * 0.085);
  for (const body of bodies) {
    const seat = SEATS[body.slot] ?? SEATS[0];
    // Wealth reads as size, within a range that never touches a neighbour.
    const size = radius * (0.80 + 0.42 * Math.min(1, Math.log10(1 + body.wealth) / 2.4));
    context.beginPath();
    context.arc(body.px, body.py, size, 0, Math.PI * 2);
    if (body.starving) {
      // Fewer than two timesteps of food left: hollow, and visibly failing.
      context.fillStyle = "rgba(20,15,8,.55)";
      context.fill();
      context.strokeStyle = seat.color;
    } else {
      context.fillStyle = seat.color;
      context.fill();
      context.strokeStyle = C.ink;
    }
    context.stroke();
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

  drawVignette();
}

/** A subtle corner darkening seats the board in the frame. Deliberately gentle:
 *  the read stays orthographic, this is a value gradient, not a rendered desk. */
function drawVignette() {
  const gradient = context.createRadialGradient(
    BOARD.x + BOARD.w / 2, H / 2, BOARD.w * 0.34,
    BOARD.x + BOARD.w / 2, H / 2, BOARD.w * 0.92,
  );
  gradient.addColorStop(0, "rgba(20,16,10,0)");
  gradient.addColorStop(1, "rgba(12,9,5,.62)");
  context.fillStyle = gradient;
  context.fillRect(BOARD.x, BOARD.y, BOARD.w, BOARD.h);
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
    size: 21, weight: 700, fill: C.muted, spacing: 2.6, outline: 3,
  });
}

function panel(x, y, width, height, radius = 10) {
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" `
    + `fill="${C.panel}" stroke="${C.border}" stroke-width="1.5"/>`;
}

function seatMark(x, y, slot, radius) {
  const seat = SEATS[slot] ?? SEATS[0];
  const stroke = `stroke="${C.ink}" stroke-width="1.8"`;
  if (seat.shape === "square") {
    return `<rect x="${x - radius}" y="${y - radius}" width="${radius * 2}" `
      + `height="${radius * 2}" rx="${radius * 0.35}" fill="${seat.color}" ${stroke}/>`;
  }
  if (seat.shape === "triangle") {
    const points = `${x},${y - radius} ${x + radius},${y + radius * 0.8} ${x - radius},${y + radius * 0.8}`;
    return `<polygon points="${points}" fill="${seat.color}" ${stroke}/>`;
  }
  if (seat.shape === "diamond") {
    const points = `${x},${y - radius} ${x + radius},${y} ${x},${y + radius} ${x - radius},${y}`;
    return `<polygon points="${points}" fill="${seat.color}" ${stroke}/>`;
  }
  return `<circle cx="${x}" cy="${y}" r="${radius}" fill="${seat.color}" ${stroke}/>`;
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
    { size: 15, weight: 600, family: F.mono, fill: C.gold, anchor: "end", spacing: 1 },
  );

  if (frame.slots.length !== 2) {
    // Absolute wealth lines — the general case.
    const scaleY = (score) => top + plotH - (score / state.maxWealth) * plotH;
    markup += `<line x1="${left}" y1="${top + plotH}" x2="${left + plotW}" y2="${top + plotH}" `
      + `stroke="rgba(246,234,210,.16)" stroke-width="1"/>`;
    markup += text(format(state.maxWealth), left - 10, top + 6, {
      size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
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
      size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
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
      size: 17, weight: 600, family: F.mono, fill: SEATS[slot].color, outline: 2.8,
    });
  markup += axisEnd(0, top + 18);
  markup += axisEnd(1, top + plotH - 8);
  markup += text("level", left - 10, zeroY + 5, {
    size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  });
  markup += text("t0", left, y + height - 16, {
    size: 18, weight: 500, family: F.mono, fill: C.dim, outline: 2.4,
  });
  markup += text(`t${scheduled}`, left + plotW, y + height - 16, {
    size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "end", outline: 2.4,
  });
  markup += text("lead, in sugar", left + plotW / 2, y + height - 16, {
    size: 18, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
  });
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

  const recent = coalesce(events.filter((event) => event.timestep <= frame.timestep))
    .slice(-4)
    .reverse();

  if (recent.length === 0) {
    markup += text("The settlers spread out across the lattice.", x + 18, y + 62, {
      size: 24, weight: 500, fill: C.muted,
    });
    return markup;
  }

  let rowY = y + 58;
  for (const event of recent) {
    const fresh = (event.until ?? event.timestep) === frame.timestep;
    const stamp = event.merged && event.until > event.since
      ? `t${event.since}–${event.until}`
      : `t${event.timestep}`;
    markup += text(stamp, x + 18, rowY + 15, {
      size: 19, weight: 600, family: F.mono, fill: fresh ? C.gold : C.dim,
    });
    if (event.kind === "death") {
      markup += `<rect x="${x + 112}" y="${rowY - 2}" width="4" height="24" rx="2" fill="${C.loss}"/>`;
      const detail = event.merged
        ? "the mountain thins the edges"
        : event.bySlot
          .filter(([slot]) => slot >= 0)
          .map(([slot, count]) => `${count} ${frame.slots[slot]?.name ?? `slot ${slot}`}`)
          .join(", ");
      markup += text(
        `${event.count} starved${detail ? ` — ${detail}` : ""}`,
        x + 128, rowY + 16,
        { size: 25, weight: 500, fill: fresh ? C.paper : C.muted },
      );
    } else {
      markup += `<rect x="${x + 112}" y="${rowY - 2}" width="4" height="24" rx="2" `
        + `fill="${SEATS[event.slot].color}"/>`;
      markup += text(
        `${event.name} takes the lead`,
        x + 128, rowY + 16,
        { size: 25, weight: 700, fill: fresh ? C.paper : C.muted },
      );
    }
    rowY += 54;
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
  const wealth = frame.agents
    .map((agent) => Math.max(0, agent.sugar + agent.spice))
    .sort((first, second) => first - second);
  const total = wealth.reduce((sum, value) => sum + value, 0);
  markup += `<rect x="${curveX}" y="${curveY}" width="${size}" height="${size}" `
    + `fill="rgba(246,234,210,.04)" stroke="rgba(246,234,210,.12)" stroke-width="1"/>`;
  markup += `<line x1="${curveX}" y1="${curveY + size}" x2="${curveX + size}" y2="${curveY}" `
    + `stroke="rgba(246,234,210,.22)" stroke-width="1" stroke-dasharray="4 4"/>`;
  if (total > 0) {
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
  markup += text("wealth share", curveX + size / 2, curveY + size + 20, {
    size: 17, weight: 500, family: F.mono, fill: C.dim, anchor: "middle", outline: 2.4,
  });

  // Two readouts, not three: the live population is already on both scorebug
  // chips, so repeating it as "survivors" only crowded the panel. Pairing it
  // with the capacity instead is the reading that means something - the world
  // deciding how many settlers it will carry.
  const readX = curveX + size + 26;
  const rows = [
    ["Gini", gini.toFixed(3), gini > 0.4 ? "sharply unequal" : gini > 0.28 ? "unequal" : "even"],
    ["Carrying capacity", format(capacity),
      `${population} alive of ${state.startingPopulation}`],
  ];
  let readY = curveY + 26;
  for (const [label, value, note] of rows) {
    markup += text(label.toUpperCase(), readX, readY, {
      size: 18, weight: 700, fill: C.muted, spacing: 1.8, outline: 2.6,
    });
    markup += text(value, readX, readY + 38, {
      size: 40, weight: 600, family: F.mono, fill: C.paper,
    });
    markup += text(note, readX, readY + 62, {
      size: 19, weight: 500, fill: C.dim,
    });
    readY += 96;
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

  const cardW = 1180;
  const cardH = 580;
  const x = (W - cardW) / 2;
  const y = (H - cardH) / 2;

  let markup = `<g class="endcard">`;
  markup += `<rect x="0" y="0" width="${W}" height="${H}" fill="rgba(10,7,4,.93)"/>`;
  markup += `<clipPath id="endcard-clip"><rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16"/></clipPath>`;
  markup += `<g clip-path="url(#endcard-clip)">`
    + `<image href="${ART.endcard}" x="${x}" y="${y - 60}" width="${cardW}" height="${cardH + 160}" `
    + `preserveAspectRatio="xMidYMid slice" opacity=".55"/>`
    + `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" fill="rgba(14,10,5,.66)"/>`
    + `</g>`;
  markup += `<rect x="${x}" y="${y}" width="${cardW}" height="${cardH}" rx="16" fill="none" `
    + `stroke="${C.gold}" stroke-width="2.5"/>`;

  markup += text("SUGARSCAPE", x + 56, y + 54, {
    size: 21, weight: 700, fill: C.muted, spacing: 4.4,
  });
  markup += eyebrow(tie ? "Final — level" : "Final", x + 56, y + 84);
  markup += seatMark(x + 68, y + 140, winner.index, 21);
  markup += text(winner.name, x + 104, y + 154, { size: 62, weight: 700, fill: C.paper });
  markup += text(verdict, x + 56, y + 212, { size: 27, weight: 500, fill: C.gold });
  markup += text(context, x + 56, y + 250, { size: 22, weight: 500, fill: C.muted });

  let rowY = y + 306;
  for (const [rank, row] of rows.entries()) {
    const leader = rank === 0 && !tie;
    markup += `<rect x="${x + 56}" y="${rowY}" width="${cardW - 112}" height="66" rx="10" `
      + `fill="rgba(20,15,8,.72)" stroke="${leader ? C.gold : C.border}" stroke-width="${leader ? 2 : 1.4}"/>`;
    markup += text(`${rank + 1}`, x + 92, rowY + 44, {
      size: 28, weight: 600, family: F.mono, fill: C.dim, anchor: "middle",
    });
    markup += seatMark(x + 134, rowY + 33, row.index, 12);
    markup += text(row.name, x + 162, rowY + 42, { size: 28, weight: 700, fill: C.paper });
    markup += text(`${row.population} alive`, x + cardW - 250, rowY + 42, {
      size: 20, weight: 500, family: F.mono, fill: C.muted, anchor: "end",
    });
    markup += text(format(row.score), x + cardW - 92, rowY + 44, {
      size: 34, weight: 700, family: F.mono, fill: leader ? C.gold : C.paper, anchor: "end",
    });
    rowY += 78;
  }
  markup += text("Score is the final living population's total sugar plus spice.",
    x + 56, y + cardH - 26, { size: 20, weight: 500, fill: C.dim });
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
  try {
    await loadAssets();
  } catch (error) {
    fail("The broadcast artwork failed to load; this build may be corrupt.");
    return;
  }
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
