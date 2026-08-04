#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import vm from "node:vm";

const root = resolve(import.meta.dirname, "..");
const binary = resolve(process.argv[2] ?? join(root, ".build/sugarscape_coworld"));
const fixture = join(root, "tests/fixtures/coworld_smoke.json");
const workspace = await mkdtemp(join(tmpdir(), "coworld-sugarscape-smoke-"));
const resultsPath = join(workspace, "results.json");
const replayPath = join(workspace, "replay.json");
const port = Number(process.env.SUGARSCAPE_SMOKE_PORT ?? 18173);
const baseUrl = `http://127.0.0.1:${port}`;

const invalidConfigPath = join(workspace, "missing-token.json");
const invalidConfig = JSON.parse(await readFile(fixture, "utf8"));
invalidConfig.tokens = [""];
await writeFile(invalidConfigPath, JSON.stringify(invalidConfig));
const invalidChild = spawn(binary, [`--config-path:${invalidConfigPath}`], {
  stdio: ["ignore", "pipe", "pipe"],
});
let invalidOutput = "";
invalidChild.stdout.on("data", (chunk) => { invalidOutput += chunk; });
invalidChild.stderr.on("data", (chunk) => { invalidOutput += chunk; });
const invalidExitCode = await new Promise((resolveExit) => {
  invalidChild.on("exit", resolveExit);
});
assert.notEqual(invalidExitCode, 0);
assert.match(invalidOutput, /requires a nonempty token/);

const child = spawn(binary, [
  "--host:127.0.0.1",
  `--port:${port}`,
  `--config-path:${fixture}`,
  `--results:${resultsPath}`,
  `--save-replay:${replayPath}`,
], { stdio: ["ignore", "pipe", "pipe"] });

let output = "";
child.stdout.on("data", (chunk) => { output += chunk; });
child.stderr.on("data", (chunk) => { output += chunk; });

async function waitForHealth(url = baseUrl, childOutput = () => output) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`${url}/healthz`);
      if (response.ok && await response.text() === "healthy") return;
    } catch {
      // The server thread is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 20));
  }
  throw new Error(`Coworld did not become healthy:\n${childOutput()}`);
}

function openSocket(path) {
  return new Promise((resolveOpen, rejectOpen) => {
    const socket = new WebSocket(`ws://127.0.0.1:${port}${path}`);
    socket.addEventListener("open", () => resolveOpen(socket), { once: true });
    socket.addEventListener(
      "error",
      () => rejectOpen(new Error(`WebSocket failed: ${path}`)),
      { once: true },
    );
  });
}

function openCollectingSocket(path, target, socketPort = port) {
  return new Promise((resolveOpen, rejectOpen) => {
    const socket = new WebSocket(`ws://127.0.0.1:${socketPort}${path}`);
    socket.addEventListener("message", (event) => {
      target.push(JSON.parse(event.data));
    });
    socket.addEventListener("open", () => resolveOpen(socket), { once: true });
    socket.addEventListener(
      "error",
      () => rejectOpen(new Error(`WebSocket failed: ${path}`)),
      { once: true },
    );
  });
}

await waitForHealth();
const playerPage = await fetch(`${baseUrl}/client/player`);
assert.equal(playerPage.status, 200);
assert.match(await playerPage.text(), /population-policy socket/);
const viewerPage = await fetch(`${baseUrl}/client/global`);
assert.equal(viewerPage.status, 200);
const viewerHtml = await viewerPage.text();
assert.match(viewerHtml, /Sugarscape Observatory/);
assert.match(viewerHtml, /World telemetry/);
assert.match(viewerHtml, /class="world-pane surface"/);

const drawnPoints = [];
const createdElements = [];
const renderOperations = [];
const canvasContext = {
  arc() { renderOperations.push("arc"); },
  beginPath() {},
  clearRect() {},
  fill() { renderOperations.push("fill"); },
  fillRect() { renderOperations.push("fillRect"); },
  fillText() {},
  lineTo(x, y) {
    drawnPoints.push([x, y]);
    renderOperations.push("lineTo");
  },
  moveTo() {},
  stroke() { renderOperations.push("stroke"); },
  strokeRect() { renderOperations.push("strokeRect"); },
};
function fakeElement(selector = "") {
  return {
    addEventListener() {},
    append() {},
    checked: false,
    dataset: {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 1, height: 1}),
    getContext: () => canvasContext,
    height: 150,
    max: 0,
    options: [{textContent: "population"}],
    replaceChildren() {},
    selectedIndex: 0,
    style: {},
    textContent: "",
    value: selector === "#cell-mode"
      ? "resources"
      : selector === "#agent-mode"
        ? "decisionModel"
        : selector === "#series"
          ? "population"
          : "0",
    width: 320,
  };
}
class FakeWebSocket {
  addEventListener() {}
  close() {}
}
const viewerContext = vm.createContext({
  console,
  createdElements,
  renderOperations,
  document: {
    createElement: () => {
      const element = fakeElement();
      createdElements.push(element);
      return element;
    },
    querySelector: (selector) => fakeElement(selector),
  },
  drawnPoints,
  location: {host: "localhost", protocol: "http:"},
  Math,
  Number,
  setTimeout,
  WebSocket: FakeWebSocket,
});
const viewerScript = viewerHtml.match(/<script>([\s\S]*)<\/script>/)?.[1];
assert.ok(viewerScript, "viewer script must be embedded");
vm.runInContext(viewerScript, viewerContext);
const displayState = vm.runInContext(`
  createdElements.length = 0;
  addDefinition("Gini", 0.089);
  cellMode.value = "pollution";
  renderStats({
    timestep: 7,
    agents: [],
    stats: {},
  });
  JSON.stringify({
    metricValue: String(createdElements[2].textContent),
    worldCaption: worldTimestep.textContent,
  });
`, viewerContext);
assert.deepEqual(JSON.parse(displayState), {
  metricValue: "0.089",
  worldCaption: "pollution field · t7",
});
const gameRenderingState = vm.runInContext(`
  const resourceStart = renderOperations.length;
  drawResourceTile([4, 4, 0], 3, 0, 0, 18, 18);
  const resourceOperations = renderOperations.length - resourceStart;
  const pollutionStart = renderOperations.length;
  drawPollutionTile([0, 0, 8], 4, 0, 0, 18, 18, 10);
  const pollutionOperations = renderOperations.length - pollutionStart;
  const spriteAgent = {
    id: 2,
    cell: 0,
    slot: -1,
    decisionModel: "none",
    race: 1,
    depressed: false,
    sick: false,
  };
  const spriteStart = renderOperations.length;
  drawAgentSprite(spriteAgent, {
    timestep: 4,
    width: 1,
    height: 1,
    agents: [spriteAgent],
  }, 18, 18);
  const spriteOperations = renderOperations.length - spriteStart;
  JSON.stringify({
    noise: [visualNoise(7, 11), visualNoise(7, 12), visualNoise(0)],
    pollutionOperations,
    resourceOperations,
    spriteOperations,
  });
`, viewerContext);
const gameRendering = JSON.parse(gameRenderingState);
assert.deepEqual(gameRendering.noise, [0.203, 0.668, 0.761]);
assert.ok(gameRendering.resourceOperations > 0);
assert.ok(gameRendering.pollutionOperations > 0);
assert.ok(gameRendering.spriteOperations > 0);
const reconnectState = vm.runInContext(`
  recordFrame({
    streamId: "first",
    timestep: 1,
    width: 1,
    height: 1,
    cells: [[0, 0, 0]],
    agents: [],
    links: [],
    slots: [],
    stats: {marker: "initial"},
  });
  recordFrame({
    streamId: "first",
    timestep: 2,
    width: 1,
    height: 1,
    cells: [[0, 0, 0]],
    agents: [],
    links: [],
    slots: [],
    stats: {marker: "latest"},
  });
  recordFrame({
    streamId: "first",
    timestep: 1,
    width: 1,
    height: 1,
    cells: [[0, 0, 0]],
    agents: [],
    links: [],
    slots: [],
    stats: {marker: "replayed"},
  });
  JSON.stringify({
    length: frames.length,
    timesteps: frames.map((frame) => frame.timestep),
    marker: frames[0].stats.marker,
  });
`, viewerContext);
assert.deepEqual(JSON.parse(reconnectState), {
  length: 2,
  timesteps: [1, 2],
  marker: "replayed",
});
const restartedState = vm.runInContext(`
  inspectedCell = 99;
  recordFrame({
    streamId: "second",
    timestep: 0,
    width: 1,
    height: 1,
    cells: [[0, 0, 0]],
    agents: [],
    links: [],
    slots: [],
    stats: {marker: "restarted"},
  });
  JSON.stringify({
    length: frames.length,
    timesteps: frames.map((frame) => frame.timestep),
    marker: frames[0].stats.marker,
    inspectedCell,
  });
`, viewerContext);
assert.deepEqual(JSON.parse(restartedState), {
  length: 1,
  timesteps: [0],
  marker: "restarted",
  inspectedCell: -1,
});
const negativeSeriesPoints = vm.runInContext(`
  seriesSelect.value = "meanHappiness";
  recordFrame({
    streamId: "second",
    timestep: 1,
    width: 1,
    height: 1,
    cells: [[0, 0, 0]],
    agents: [],
    links: [],
    slots: [],
    stats: {meanHappiness: -2},
  });
  drawnPoints.length = 0;
  renderSeries();
  JSON.stringify(drawnPoints);
`, viewerContext);
assert.ok(
  JSON.parse(negativeSeriesPoints).every(
    ([x, y]) => Number.isFinite(x) && Number.isFinite(y) &&
      x >= 0 && x <= 320 && y >= 0 && y <= 150,
  ),
);

const frames = [];
const replayFrames = [];
const lateFrames = [];
const globalSocket = await openCollectingSocket("/global", frames);
const replaySocket = await openCollectingSocket("/replay", replayFrames);
const playerSocket = await openSocket("/player?slot=0&token=smoke-token");
let observations = 0;
let firstExpected = null;
let lateGlobalSocket = null;

playerSocket.addEventListener("message", async (event) => {
  const observation = JSON.parse(event.data);
  assert.equal(observation.type, "observation");
  assert.ok(observation.candidates.length > 0);
  observations += 1;
  if (observations === 1) {
    const legitimate = observation.candidates[0].cell;
    const alternative = observation.candidates.find(
      (candidate) => candidate.cell !== legitimate,
    );
    assert.ok(alternative, "first observation needs a spoofable alternative");
    const spoofed = alternative.cell;
    firstExpected = {
      agentId: observation.agent.id,
      cell: legitimate,
      timestep: observation.timestep,
    };
    globalSocket.send(JSON.stringify({
      type: "action",
      requestId: observation.requestId,
      cell: spoofed,
    }));
    setTimeout(() => playerSocket.send(JSON.stringify({
      type: "action",
      requestId: observation.requestId,
      cell: legitimate,
    })), 10);
  } else if (observations === 2) {
    playerSocket.send(JSON.stringify({
      type: "action",
      requestId: observation.requestId,
      cell: -999,
    }));
  } else if (observations === 9) {
    const lateSocketPromise = openCollectingSocket("/global", lateFrames);
    playerSocket.send(JSON.stringify({
      type: "action",
      requestId: observation.requestId,
      cell: observation.candidates[0].cell,
    }));
    lateGlobalSocket = await lateSocketPromise;
  } else {
    playerSocket.send(JSON.stringify({
      type: "action",
      requestId: observation.requestId,
      cell: observation.candidates[0].cell,
    }));
  }
});

const exitCode = await new Promise((resolveExit) => {
  child.on("exit", resolveExit);
});
assert.equal(exitCode, 0, output);
assert.equal(observations, 24);

const results = JSON.parse(await readFile(resultsPath, "utf8"));
assert.deepEqual(results.decision_requests, [24]);
assert.deepEqual(results.actions_received, [23]);
assert.deepEqual(results.fallbacks, [1]);
assert.equal(results.population.length, 1);
assert.match(results.score_semantics, /final population sugar plus spice/);
assert.deepEqual(
  lateFrames.slice(0, 2).map((frame) => frame.timestep),
  [0, 1],
);
lateGlobalSocket?.close();

const replay = JSON.parse(await readFile(replayPath, "utf8"));
assert.equal(replay.format, "sugarscape.replay.v1");
assert.equal(replay.config.seed, 12345);
assert.deepEqual(replay.frames.map((frame) => frame.timestep), [0, 1, 2, 3]);
assert.equal(replay.frames[0].cells[0].length, 3);
assert.ok(Array.isArray(replay.frames[0].links));
assert.equal(typeof replay.frames[0].agents[0].age, "number");
assert.equal(typeof replay.frames[0].agents[0].sick, "boolean");
assert.equal(typeof replay.frames[0].agents[0].movement, "number");
assert.notEqual(
  replay.frames[0].stats.meanWealth,
  replay.frames.at(-1).stats.meanWealth,
);
assert.ok(frames.length >= 3);
assert.ok(replayFrames.length >= 3);
assert.equal(typeof frames[0].streamId, "string");
assert.ok(frames.every((frame) => frame.streamId === frames[0].streamId));
assert.ok(
  replayFrames.every((frame) => frame.streamId === replayFrames[0].streamId),
);
replaySocket.close();
const firstDecisionFrame = replay.frames.find(
  (frame) => frame.timestep === firstExpected.timestep,
);
const firstAgent = firstDecisionFrame.agents.find(
  (agent) => agent.id === firstExpected.agentId,
);
assert.equal(firstAgent.cell, firstExpected.cell);

const replayChild = spawn(binary, [
  "--host:127.0.0.1",
  `--port:${port + 1}`,
  `--load-replay:${replayPath}`,
], { stdio: ["ignore", "pipe", "pipe"] });
let replayOutput = "";
replayChild.stdout.on("data", (chunk) => { replayOutput += chunk; });
replayChild.stderr.on("data", (chunk) => { replayOutput += chunk; });
await waitForHealth(
  `http://127.0.0.1:${port + 1}`,
  () => replayOutput,
);
const loadedReplayFrames = [];
const loadedReplaySocket = await openCollectingSocket(
  "/replay",
  loadedReplayFrames,
  port + 1,
);
for (let attempt = 0; attempt < 100; attempt += 1) {
  if (loadedReplayFrames.length === replay.frames.length) break;
  await new Promise((resolveWait) => setTimeout(resolveWait, 20));
}
assert.deepEqual(
  loadedReplayFrames.map((frame) => frame.timestep),
  replay.frames.map((frame) => frame.timestep),
);
loadedReplaySocket.close();
const replayExitPromise = new Promise((resolveExit) => {
  replayChild.on("exit", (code, signal) => resolveExit({code, signal}));
});
replayChild.kill("SIGTERM");
const replayExit = await replayExitPromise;
assert.deepEqual(replayExit, {code: null, signal: "SIGTERM"}, replayOutput);

console.log(
  `Coworld smoke passed: ${observations} observations, ` +
  `${results.actions_received[0]} actions, ${results.fallbacks[0]} fallback, ` +
  `${replay.frames.length} replay frames`,
);
