#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

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

await waitForHealth();
const playerPage = await fetch(`${baseUrl}/client/player`);
assert.equal(playerPage.status, 200);
assert.match(await playerPage.text(), /population-policy socket/);
const viewerPage = await fetch(`${baseUrl}/client/global`);
assert.equal(viewerPage.status, 200);
assert.match(await viewerPage.text(), /Sugarscape Observatory/);

const globalSocket = await openSocket("/global");
const playerSocket = await openSocket("/player?slot=0&token=smoke-token");
const frames = [];
let observations = 0;
let firstExpected = null;

globalSocket.addEventListener("message", (event) => {
  frames.push(JSON.parse(event.data));
});
playerSocket.addEventListener("message", (event) => {
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

const replay = JSON.parse(await readFile(replayPath, "utf8"));
assert.equal(replay.format, "sugarscape.replay.v1");
assert.equal(replay.config.seed, 12345);
assert.deepEqual(replay.frames.map((frame) => frame.timestep), [0, 1, 2, 3]);
assert.ok(frames.length >= 3);
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
const replayExitCode = await new Promise((resolveExit) => {
  replayChild.on("exit", resolveExit);
});
assert.equal(replayExitCode, 0, replayOutput);

console.log(
  `Coworld smoke passed: ${observations} observations, ` +
  `${results.actions_received[0]} actions, ${results.fallbacks[0]} fallback, ` +
  `${replay.frames.length} replay frames`,
);
