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
let agents = new Map();
let scoreSeries = []; // per seat: [{tick, score}, ...] extracted once at load

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
  if (documentValue.format !== "sugarscape.replay.v3" || documentValue.version !== 1) {
    throw new Error("Unsupported Sugarscape replay format.");
  }
  replay = documentValue;
  timeline.max = String(replay.frames.length);
  statusLabel.textContent = `${replay.frames.length} ticks · seed ${replay.header.seed}`;
  extractScoreSeries();
  buildSeatSections();
  seek(0);
  schedule();
}

function extractScoreSeries() {
  scoreSeries = replay.header.targets.map(() => []);
  replay.frames.forEach((frame) => {
    if (!frame.running) return;
    for (const entry of frame.running) {
      scoreSeries[entry.seat].push({ tick: frame.timestep, score: entry.score });
    }
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
}

// Print-cartography terrain: paper where bare, an amber (sugar) ramp and a
// terracotta (spice) ramp that mix toward umber where both resources sit.
// Pollution greys the cell. Values are blended in linear channel space from
// the house palette anchors.
const PAPER_RGB = [255, 253, 244];
const SUGAR_RGB = [212, 168, 83]; // --ink-gold
const SPICE_RGB = [179, 110, 78]; // --ink-terracotta
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
  cells.forEach((cell, index) => {
    const x = Math.floor(index / height);
    const y = index % height;
    const sugar = Math.min(1, cell[0] / Math.max(1, cell[3]));
    const spice = Math.min(1, cell[1] / Math.max(1, cell[4]));
    const pollution = Math.min(1, cell[2] / 20);
    let rgb = PAPER_RGB;
    // Resource intensity eases (sqrt) so low stocks still read on paper.
    if (sugar > 0) rgb = mix(rgb, SUGAR_RGB, Math.sqrt(sugar) * 0.85);
    if (spice > 0) rgb = mix(rgb, SPICE_RGB, Math.sqrt(spice) * 0.7);
    if (pollution > 0) rgb = mix(rgb, POLLUTION_RGB, pollution * 0.6);
    mapContext.fillStyle = `rgb(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])})`;
    mapContext.fillRect(x * scaleX, y * scaleY, Math.ceil(scaleX), Math.ceil(scaleY));
  });
  const radius = Math.max(1.5, Math.min(scaleX, scaleY) * 0.3);
  for (const [, seat, x, y] of agents.values()) {
    mapContext.beginPath();
    mapContext.arc((x + 0.5) * scaleX, (y + 0.5) * scaleY, radius, 0, Math.PI * 2);
    mapContext.fillStyle = seatColors[seat % seatColors.length];
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
      '<canvas class="histogram" width="420" height="120"></canvas>',
      '<div class="pane-caption">Measured (bars) vs target (line)</div>',
      '<canvas class="scoreline" width="420" height="46"></canvas>',
      '<div class="pane-caption">Match score over the episode</div>',
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
  });
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
