"use strict";

const mapCanvas = document.querySelector("#map");
const mapContext = mapCanvas.getContext("2d");
const timeline = document.querySelector("#timeline");
const playButton = document.querySelector("#play");
const speedSelect = document.querySelector("#speed");
const tickLabel = document.querySelector("#tick");
const statusLabel = document.querySelector("#status");
const histogramRoot = document.querySelector("#histograms");
const errorBox = document.querySelector("#error");

// House game palette (Ink & Print design system) — seat identity colors.
const seatColors = ["#2563eb", "#9333ea", "#059669", "#d97706", "#dc2626"];
// Ink & Print tokens used inside the canvases.
const INK = "#111827";
const INK_SUBTLE = "#555555";
const INK_MUTED = "#999999";
const PAPER = "#fffdf4";
const PAPER_ALT = "#f8f6ef";
const HAIRLINE = "#e4dac8";

let replay = null;
let frameIndex = 0;
let playing = true;
let timer = null;
let cells = [];
let agents = new Map(); // id -> dynamic row [id, x, y, sugar_b, spice_b, tribe, diseases]
let roster = new Map(); // id -> static row [id, seat, born, sex01, vision, movement, mSugar, mSpice, maxAge]
let scoreSeries = []; // per seat: [{tick, score}, ...] extracted once at load
let populationSeries = []; // per seat: [count per frame], reconstructed at load
let maxWealthSeen = 1; // for stable agent-dot radius scaling across the episode

const seatOf = (agentId) => {
  const staticRow = roster.get(agentId);
  return staticRow ? staticRow[1] : 0;
};
const wealthOf = (dynamicRow) => (dynamicRow[3] || 0) + (dynamicRow[4] || 0);

const params = new URLSearchParams(location.search);
if (params.get("chrome") === "off") document.body.classList.add("chrome-off");

async function inflate(bytes) {
  if (!("DecompressionStream" in window)) {
    throw new Error("This browser does not support zlib replay decompression (DecompressionStream). ");
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function loadBytes(bytes) {
  const raw = await inflate(bytes);
  const documentValue = JSON.parse(new TextDecoder().decode(raw));
  if (documentValue.format !== "sugarscape.replay.v3") {
    throw new Error("Unsupported Sugarscape replay format.");
  }
  if (documentValue.version !== 2) {
    throw new Error(
      `This replay was recorded in an incompatible format version (${documentValue.version}); ` +
      "this viewer plays version 2 replays. Episodes recorded before the format change " +
      "cannot be replayed here."
    );
  }
  replay = documentValue;
  timeline.max = String(replay.frames.length);
  statusLabel.textContent = `${replay.frames.length} ticks · seed ${replay.header.seed}`;
  extractSeries();
  buildSeatSections();
  seek(0);
  schedule();
}

// One pass over all frames at load: the full agent roster (statics arrive
// once, at header or birth), score snapshots, per-seat population per tick,
// and the episode-wide wealth maximum for dot-radius scaling.
function extractSeries() {
  const seatCount = replay.header.targets.length;
  scoreSeries = replay.header.targets.map(() => []);
  populationSeries = replay.header.targets.map(() => []);
  maxWealthSeen = 1;
  roster = new Map(replay.header.roster.map((row) => [row[0], row]));
  const live = new Set(replay.header.initial_agents.map((row) => row[0]));
  for (const row of replay.header.initial_agents) {
    maxWealthSeen = Math.max(maxWealthSeen, wealthOf(row));
  }
  replay.frames.forEach((frame) => {
    if (frame.running) {
      for (const entry of frame.running) {
        scoreSeries[entry.seat].push({ tick: frame.timestep, score: entry.score });
      }
    }
    for (const row of frame.agent_deltas.births) roster.set(row[0], row);
    for (const row of frame.agent_deltas.upsert) {
      live.add(row[0]);
      maxWealthSeen = Math.max(maxWealthSeen, wealthOf(row));
    }
    for (const agentId of frame.agent_deltas.remove) live.delete(agentId);
    const counts = new Array(seatCount).fill(0);
    for (const agentId of live) counts[seatOf(agentId) % seatCount] += 1;
    counts.forEach((count, seat) => populationSeries[seat].push(count));
  });
}

function resetGrid() {
  cells = replay.header.initial_grid.cells.map((cell) => cell.slice());
  agents = new Map(replay.header.initial_agents.map((agent) => [agent[0], agent.slice()]));
}

function seek(nextIndex) {
  frameIndex = Math.max(0, Math.min(Number(nextIndex), replay.frames.length));
  resetGrid();
  for (let index = 0; index < frameIndex; index += 1) applyDeltas(replay.frames[index]);
  timeline.value = String(frameIndex);
  const frame = frameIndex > 0 ? replay.frames[frameIndex - 1] : null;
  tickLabel.textContent = `T${frame ? frame.timestep : 0} · ${agents.size} agents`;
  renderMap(frame);
  renderSeatPanes(frame);
}

function applyDeltas(frame) {
  for (const [index, sugar, spice, pollution] of frame.cell_deltas) {
    cells[index][0] = sugar;
    cells[index][1] = spice;
    cells[index][2] = pollution;
  }
  for (const agent of frame.agent_deltas.upsert) agents.set(agent[0], agent.slice());
  for (const agentId of frame.agent_deltas.remove) agents.delete(agentId);
  // Births only add roster statics; the newborn's dynamic row arrives in the
  // same frame's upsert list (already applied above).
}

// Print-cartography terrain, two independent channels per cell: sugar is an
// amber (ink-gold) FILL ramp, spice is a terracotta diagonal HATCH whose
// weight tracks the spice stock — each amount stays readable on its own, the
// way a printed map separates tint from line work. Pollution greys the fill.
const PAPER_RGB = [255, 253, 244];
const SUGAR_RGB = [212, 168, 83]; // --ink-gold
const SPICE_HATCH = "#b36e4e"; // --ink-terracotta
const POLLUTION_RGB = [138, 138, 138];

function mix(base, tint, amount) {
  return [
    base[0] + (tint[0] - base[0]) * amount,
    base[1] + (tint[1] - base[1]) * amount,
    base[2] + (tint[2] - base[2]) * amount,
  ];
}

function renderMap(frame) {
  const { width, height } = replay.header.initial_grid;
  const scaleX = mapCanvas.width / width;
  const scaleY = mapCanvas.height / height;
  mapContext.fillStyle = PAPER;
  mapContext.fillRect(0, 0, mapCanvas.width, mapCanvas.height);
  // Pass 1 — sugar fill (plus pollution grey).
  cells.forEach((cell, index) => {
    const x = Math.floor(index / height);
    const y = index % height;
    const sugar = Math.min(1, cell[0] / Math.max(1, cell[3]));
    const pollution = Math.min(1, cell[2] / 20);
    let rgb = PAPER_RGB;
    // Resource intensity eases (sqrt) so low stocks still read on paper.
    if (sugar > 0) rgb = mix(rgb, SUGAR_RGB, Math.sqrt(sugar) * 0.9);
    if (pollution > 0) rgb = mix(rgb, POLLUTION_RGB, pollution * 0.6);
    mapContext.fillStyle = `rgb(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])})`;
    mapContext.fillRect(x * scaleX, y * scaleY, Math.ceil(scaleX), Math.ceil(scaleY));
  });
  // Pass 2 — spice hatch: 1–3 diagonal strokes per cell by stock level.
  mapContext.strokeStyle = SPICE_HATCH;
  mapContext.lineWidth = Math.max(1, scaleX * 0.09);
  mapContext.lineCap = "round";
  cells.forEach((cell, index) => {
    const spice = Math.min(1, cell[1] / Math.max(1, cell[4]));
    if (spice <= 0) return;
    const x = Math.floor(index / height) * scaleX;
    const y = (index % height) * scaleY;
    const strokes = spice > 0.66 ? 3 : spice > 0.33 ? 2 : 1;
    mapContext.globalAlpha = 0.45 + 0.45 * spice;
    mapContext.beginPath();
    for (let line = 1; line <= strokes; line += 1) {
      const offset = (line / (strokes + 1)) * (scaleX + scaleY);
      const startX = x + Math.max(0, offset - scaleY);
      const startY = y + Math.min(scaleY, offset);
      const endX = x + Math.min(scaleX, offset);
      const endY = y + Math.max(0, offset - scaleX);
      mapContext.moveTo(startX, startY);
      mapContext.lineTo(endX, endY);
    }
    mapContext.stroke();
  });
  mapContext.globalAlpha = 1;
  // Agents: seat-colored dots sized by wealth (sqrt ramp, episode-stable
  // scale) with a paper outline — the canonical mark, made data-bearing.
  const baseRadius = Math.max(1.5, Math.min(scaleX, scaleY) * 0.22);
  const maxRadius = Math.min(scaleX, scaleY) * 0.46;
  for (const row of agents.values()) {
    const [agentId, x, y] = row;
    const radius = baseRadius + (maxRadius - baseRadius) * Math.sqrt(wealthOf(row) / maxWealthSeen);
    mapContext.beginPath();
    mapContext.arc((x + 0.5) * scaleX, (y + 0.5) * scaleY, radius, 0, Math.PI * 2);
    mapContext.fillStyle = seatColors[seatOf(agentId) % seatColors.length];
    mapContext.fill();
    mapContext.lineWidth = 1;
    mapContext.strokeStyle = PAPER;
    mapContext.stroke();
  }
}

function buildSeatSections() {
  histogramRoot.replaceChildren();
  replay.header.targets.forEach((target, seat) => {
    const section = document.createElement("section");
    section.className = "seat-section";
    section.innerHTML = [
      '<div class="seat-heading"><div>',
      `<div class="seat-name"><span class="seat-dot"></span>Seat ${seat + 1}</div>`,
      '<div class="target-name"></div></div>',
      '<div><span class="seat-score">—</span>',
      '<span class="seat-score-label">distribution match</span></div></div>',
      '<div class="pane-label">Measured (bars) vs target (line)</div>',
      '<canvas class="histogram" width="420" height="120"></canvas>',
      '<div class="pane-label">Match score over the episode</div>',
      '<canvas class="scoreline" width="420" height="46"></canvas>',
      '<div class="pane-label popline-caption">Living agents</div>',
      '<canvas class="popline" width="420" height="46"></canvas>',
    ].join("");
    section.querySelector(".seat-dot").style.background = seatColors[seat % seatColors.length];
    section.querySelector(".target-name").textContent = `${target.id} · ${target.variable}`;
    histogramRoot.append(section);
  });
}

function latestRunning(frame) {
  if (frame && frame.running) return frame.running;
  for (let index = frameIndex - 2; index >= 0; index -= 1) {
    if (replay.frames[index].running) return replay.frames[index].running;
  }
  return [];
}

function renderSeatPanes(frame) {
  const running = latestRunning(frame);
  const sections = histogramRoot.querySelectorAll(".seat-section");
  const currentTick = frame ? frame.timestep : 0;
  replay.header.targets.forEach((target, seat) => {
    const current = running.find((entry) => entry.seat === seat);
    const measured = current ? current.histogram.probs : target.probs.map(() => 0);
    sections[seat].querySelector(".seat-score").textContent = current ? current.score.toFixed(3) : "—";
    const color = seatColors[seat % seatColors.length];
    drawHistogram(sections[seat].querySelector(".histogram"), target.probs, measured, color);
    drawScoreline(sections[seat].querySelector(".scoreline"), scoreSeries[seat], currentTick, color);
    const populationNow = frameIndex > 0 ? populationSeries[seat][frameIndex - 1] : populationSeries[seat][0] || 0;
    sections[seat].querySelector(".popline-caption").textContent =
      `Living agents · now ${populationNow}`;
    drawPopline(sections[seat].querySelector(".popline"), populationSeries[seat], currentTick, color);
  });
}

function drawPopline(canvas, series, currentTick, color) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  context.fillStyle = PAPER_ALT;
  context.fillRect(0, 0, width, height);
  const totalTicks = replay.frames.length || 1;
  const maximum = Math.max(1, ...populationSeries.flat());
  context.strokeStyle = HAIRLINE;
  context.lineWidth = 1;
  [4.5, height - 4.5].forEach((y) => {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  });
  if (!series.length) return;
  const yFor = (count) => height - 4.5 - (count / maximum) * (height - 9);
  // Filled area under the line makes population read as mass, not a trace.
  context.beginPath();
  context.moveTo(0, yFor(series[0]));
  series.forEach((count, index) => {
    context.lineTo(((index + 1) / totalTicks) * width, yFor(count));
  });
  context.lineTo((series.length / totalTicks) * width, height - 4.5);
  context.lineTo(0, height - 4.5);
  context.closePath();
  context.fillStyle = `${color}22`;
  context.fill();
  context.strokeStyle = color;
  context.lineWidth = 1.5;
  context.beginPath();
  series.forEach((count, index) => {
    const x = ((index + 1) / totalTicks) * width;
    if (index === 0) context.moveTo(x, yFor(count)); else context.lineTo(x, yFor(count));
  });
  context.stroke();
  context.strokeStyle = INK_MUTED;
  context.setLineDash([2, 3]);
  context.beginPath();
  const playheadX = (currentTick / totalTicks) * width;
  context.moveTo(playheadX, 0);
  context.lineTo(playheadX, height);
  context.stroke();
  context.setLineDash([]);
}

function drawHistogram(canvas, target, measured, color) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const baseline = height - 12;
  const maximum = Math.max(0.001, ...target, ...measured);
  context.fillStyle = PAPER_ALT;
  context.fillRect(0, 0, width, height);
  // Measured distribution: bars in the seat color at print weight.
  const barWidth = width / measured.length;
  context.fillStyle = `${color}55`;
  context.strokeStyle = color;
  context.lineWidth = 1;
  measured.forEach((value, index) => {
    const barHeight = (value / maximum) * (baseline - 8);
    const x = index * barWidth + 1.5;
    context.fillRect(x, baseline - barHeight, Math.max(1, barWidth - 3), barHeight);
    context.strokeRect(x, baseline - barHeight, Math.max(1, barWidth - 3), barHeight);
  });
  // Target silhouette: a stepped ink outline over the bars.
  context.strokeStyle = INK;
  context.lineWidth = 1.5;
  context.beginPath();
  target.forEach((value, index) => {
    const y = baseline - (value / maximum) * (baseline - 8);
    const x0 = index * barWidth;
    if (index === 0) context.moveTo(x0, y); else context.lineTo(x0, y);
    context.lineTo(x0 + barWidth, y);
  });
  context.stroke();
  // Baseline hairline.
  context.strokeStyle = HAIRLINE;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(0, baseline + 0.5);
  context.lineTo(width, baseline + 0.5);
  context.stroke();
}

function drawScoreline(canvas, series, currentTick, color) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  context.fillStyle = PAPER_ALT;
  context.fillRect(0, 0, width, height);
  const totalTicks = replay.frames.length || 1;
  // Score gridline at 1.0 (perfect match) and 0.
  context.strokeStyle = HAIRLINE;
  context.lineWidth = 1;
  [4.5, height - 4.5].forEach((y) => {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  });
  if (!series.length) return;
  const yFor = (score) => height - 4.5 - Math.max(0, Math.min(1, score)) * (height - 9);
  context.strokeStyle = color;
  context.lineWidth = 1.5;
  context.beginPath();
  series.forEach((point, index) => {
    const x = (point.tick / totalTicks) * width;
    if (index === 0) context.moveTo(x, yFor(point.score)); else context.lineTo(x, yFor(point.score));
  });
  context.stroke();
  // Playhead marker: ink tick at the current position.
  context.strokeStyle = INK_MUTED;
  context.setLineDash([2, 3]);
  context.beginPath();
  const playheadX = (currentTick / totalTicks) * width;
  context.moveTo(playheadX, 0);
  context.lineTo(playheadX, height);
  context.stroke();
  context.setLineDash([]);
}

function schedule() {
  clearTimeout(timer);
  if (!playing || !replay) return;
  timer = setTimeout(() => {
    seek(frameIndex >= replay.frames.length ? 0 : frameIndex + 1);
    schedule();
  }, Number(speedSelect.value));
}

playButton.addEventListener("click", () => {
  playing = !playing;
  playButton.textContent = playing ? "Pause" : "Play";
  schedule();
});
timeline.addEventListener("input", () => seek(timeline.value));
speedSelect.addEventListener("change", schedule);

window.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "coworld-replay") return;
  const value = event.data.bytes;
  let bytes;
  if (value instanceof ArrayBuffer) {
    bytes = new Uint8Array(value);
  } else if (ArrayBuffer.isView(value)) {
    bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  } else {
    showError(new Error("postMessage replay bytes must be an ArrayBuffer or typed array."));
    return;
  }
  loadBytes(bytes).catch(showError);
});

function showError(error) {
  playing = false;
  errorBox.hidden = false;
  errorBox.textContent = `Unable to load replay: ${error.message}`;
  statusLabel.textContent = "Replay failed";
}

const replayUrl = params.get("replay");
if (replayUrl) {
  fetch(replayUrl)
    .then((response) => {
      if (!response.ok) throw new Error(`Replay fetch returned HTTP ${response.status}.`);
      return response.arrayBuffer();
    })
    .then((buffer) => loadBytes(new Uint8Array(buffer)))
    .catch(showError);
}
