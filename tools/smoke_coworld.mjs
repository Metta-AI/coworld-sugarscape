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

async function waitForHealth() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/healthz`);
      if (response.ok && await response.text() === "healthy") return;
    } catch {
      // The server thread is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 20));
  }
  throw new Error(`Coworld did not become healthy:\n${output}`);
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

function openCollectingSocket(path, target) {
  return new Promise((resolveOpen, rejectOpen) => {
    const socket = new WebSocket(`ws://127.0.0.1:${port}${path}`);
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
// The replay is served at /client/replay and the live spectator at
// /client/global, from the same document.
const replayPage = await fetch(`${baseUrl}/client/replay`);
assert.equal(replayPage.status, 200);
assert.equal(await replayPage.text(), viewerHtml);
// Nothing may be fetched from outside the document: the hosted embed is a
// sandboxed iframe behind a proxy that cannot reach a CDN, and any separate
// sub-resource 404s under the rewritten base href.
assert.match(viewerHtml, /<base href="\/">/);
assert.doesNotMatch(viewerHtml, /https?:\/\/(fonts|cdn|unpkg|jsdelivr)/);
assert.doesNotMatch(viewerHtml, /<(script|link)[^>]+\b(src|href)="(?!data:)/);

// The viewer's own model is asserted in tools/test_viewer.mjs, which reads the
// generated document off disk and therefore needs neither this binary nor the
// private packages it is built from. What stays here is everything that needs a
// running server: the protocol, the routes, the replay-server lifetime, and the
// late-joiner backlog.


const frames = [];
const lateFrames = [];
const globalSocket = await openCollectingSocket("/global", frames);
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
assert.equal(typeof frames[0].streamId, "string");
assert.ok(frames.every((frame) => frame.streamId === frames[0].streamId));
const firstDecisionFrame = replay.frames.find(
  (frame) => frame.timestep === firstExpected.timestep,
);
const firstAgent = firstDecisionFrame.agents.find(
  (agent) => agent.id === firstExpected.agentId,
);
assert.equal(firstAgent.cell, firstExpected.cell);

// Replay mode is a SERVER: it must publish the recording and then KEEP
// SERVING. It used to exit seconds after boot, so a spectator who opened the
// viewer a moment later - and the certifier's own replay-liveness probe - found
// nothing listening.
const replayPort = port + 1;
const replayChild = spawn(binary, [
  "--host:127.0.0.1",
  `--port:${replayPort}`,
  `--load-replay:${replayPath}`,
], { stdio: ["ignore", "pipe", "pipe"] });
let replayOutput = "";
replayChild.stdout.on("data", (chunk) => { replayOutput += chunk; });
replayChild.stderr.on("data", (chunk) => { replayOutput += chunk; });
replayChild.on("exit", (code) => {
  throw new Error(`replay server exited early with ${code}:\n${replayOutput}`);
});

const replayBase = `http://127.0.0.1:${replayPort}`;
for (let attempt = 0; attempt < 200; attempt += 1) {
  try {
    if ((await fetch(`${replayBase}/healthz`)).ok) break;
  } catch {
    // still starting
  }
  await new Promise((wait) => setTimeout(wait, 20));
}
// Well past the point where publishing has finished.
await new Promise((wait) => setTimeout(wait, 1500));
assert.equal((await fetch(`${replayBase}/healthz`)).status, 200, replayOutput);
assert.equal((await fetch(`${replayBase}/client/replay`)).status, 200);

// Both socket names serve the recording: /global is the spectator stream and
// /replay is what the Coworld certifier probes for replay liveness.
for (const path of ["/global", "/replay"]) {
  const received = [];
  const socket = new WebSocket(`ws://127.0.0.1:${replayPort}${path}`);
  await new Promise((resolveOpen, rejectOpen) => {
    socket.addEventListener("open", resolveOpen, { once: true });
    socket.addEventListener("error", () => rejectOpen(
      new Error(`replay socket ${path} refused the upgrade`),
    ), { once: true });
  });
  await new Promise((wait) => {
    socket.addEventListener("message", (event) => received.push(JSON.parse(event.data)));
    setTimeout(wait, 400);
  });
  socket.close();
  // A late joiner still receives the WHOLE episode, not a trimmed tail.
  assert.deepEqual(
    received.map((frame) => frame.timestep),
    replay.frames.map((frame) => frame.timestep),
    `socket ${path} must replay every recorded frame to a late spectator`,
  );
  assert.equal(received[0].maxTimestep, replay.config.timesteps);
}

replayChild.removeAllListeners("exit");
replayChild.kill();

console.log(
  `Coworld smoke passed: ${observations} observations, ` +
  `${results.actions_received[0]} actions, ${results.fallbacks[0]} fallback, ` +
  `${replay.frames.length} replay frames, replay server stayed up`,
);
