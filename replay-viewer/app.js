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
const seatColors = ["#53b9ff", "#ff6b6b", "#c795ff", "#5ee39d", "#ffd166", "#f78cdd"];

let replay = null;
let frameIndex = 0;
let playing = true;
let timer = null;
let cells = [];
let agents = new Map();

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
  buildHistogramCards();
  seek(0);
  schedule();
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
  tickLabel.textContent = `T${frame ? frame.timestep : 0}`;
  renderMap(frame);
  renderHistograms(frame);
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

function renderMap(frame) {
  const {width, height} = replay.header.initial_grid;
  const scaleX = mapCanvas.width / width;
  const scaleY = mapCanvas.height / height;
  mapContext.fillStyle = "#0e1318";
  mapContext.fillRect(0, 0, mapCanvas.width, mapCanvas.height);
  cells.forEach((cell, index) => {
    const x = Math.floor(index / height);
    const y = index % height;
    const sugar = Math.min(1, cell[0] / Math.max(1, cell[3]));
    const spice = Math.min(1, cell[1] / Math.max(1, cell[4]));
    const pollution = Math.min(1, cell[2] / 20);
    const red = Math.round(45 + 190 * spice);
    const green = Math.round(45 + 175 * sugar);
    const blue = Math.round(35 + 45 * pollution);
    mapContext.fillStyle = `rgb(${red},${green},${blue})`;
    mapContext.fillRect(x * scaleX, y * scaleY, Math.ceil(scaleX), Math.ceil(scaleY));
  });
  for (const [, seat, x, y] of agents.values()) {
    mapContext.fillStyle = seatColors[seat % seatColors.length];
    mapContext.beginPath();
    const radius = Math.max(1.5, Math.min(scaleX, scaleY) * 0.32);
    mapContext.arc((x + 0.5) * scaleX, (y + 0.5) * scaleY, radius, 0, Math.PI * 2);
    mapContext.fill();
  }
}

function buildHistogramCards() {
  histogramRoot.replaceChildren();
  replay.header.targets.forEach((target, seat) => {
    const card = document.createElement("section");
    card.className = "seat-card";
    card.innerHTML = [
      '<div class="seat-heading"><div>',
      `<div class="seat-name">Seat ${seat + 1}</div>`,
      '<div class="target-name"></div></div>',
      '<div class="seat-score">—</div></div>',
      '<canvas class="histogram" width="420" height="130"></canvas>',
    ].join("");
    card.querySelector(".target-name").textContent = `${target.id} · ${target.variable}`;
    histogramRoot.append(card);
  });
}

function latestRunning(frame) {
  if (frame && frame.running) return frame.running;
  for (let index = frameIndex - 2; index >= 0; index -= 1) {
    if (replay.frames[index].running) return replay.frames[index].running;
  }
  return [];
}

function renderHistograms(frame) {
  const running = latestRunning(frame);
  const cards = histogramRoot.querySelectorAll(".seat-card");
  replay.header.targets.forEach((target, seat) => {
    const current = running.find((entry) => entry.seat === seat);
    const measured = current ? current.histogram.probs : target.probs.map(() => 0);
    cards[seat].querySelector(".seat-score").textContent = current ? current.score.toFixed(3) : "—";
    drawHistogram(cards[seat].querySelector("canvas"), target.probs, measured, seatColors[seat % seatColors.length]);
  });
}

function drawHistogram(canvas, target, measured, color) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const maximum = Math.max(0.001, ...target, ...measured);
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "#758292";
  context.setLineDash([4, 3]);
  context.beginPath();
  target.forEach((value, index) => {
    const x = (index / Math.max(1, target.length - 1)) * width;
    const y = height - (value / maximum) * (height - 8);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.stroke();
  context.setLineDash([]);
  const barWidth = width / measured.length;
  context.fillStyle = `${color}bb`;
  measured.forEach((value, index) => {
    const barHeight = (value / maximum) * (height - 8);
    context.fillRect(index * barWidth + 1, height - barHeight, Math.max(1, barWidth - 2), barHeight);
  });
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
