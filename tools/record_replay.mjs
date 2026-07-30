#!/usr/bin/env node
// Record a full-scale Sugarscape episode to a replay artifact, driving two
// differentiated population policies over the real player socket. Used to build
// and verify the broadcast replay viewer against a representative match rather
// than the tiny certification fixture.
//
//   node tools/record_replay.mjs [output.json]

import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const binary = join(root, ".build/sugarscape_coworld");
const output = resolve(process.argv[2] ?? join(root, ".build/replay.json"));
const port = Number(process.env.SUGARSCAPE_RECORD_PORT ?? 18291);
const workspace = await mkdtemp(join(tmpdir(), "sugarscape-record-"));
const configPath = join(workspace, "config.json");
const resultsPath = join(workspace, "results.json");

const manifest = JSON.parse(await readFile(join(root, "coworld_manifest.json"), "utf8"));
const variant = manifest.variants.find((entry) => entry.id === "default");
const config = {
  ...variant.game_config,
  seed: Number(process.env.SUGARSCAPE_RECORD_SEED ?? 8675309),
  tokens: ["token-population-a", "token-population-b"],
};
await writeFile(configPath, JSON.stringify(config, null, 2));

const child = spawn(binary, [
  "--host:127.0.0.1",
  `--port:${port}`,
  `--config-path:${configPath}`,
  `--results:${resultsPath}`,
  `--save-replay:${output}`,
], { stdio: ["ignore", "pipe", "pipe"] });

let log = "";
child.stdout.on("data", (chunk) => { log += chunk; });
child.stderr.on("data", (chunk) => { log += chunk; });

async function waitForHealth() {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (response.ok && (await response.text()) === "healthy") return;
    } catch {
      // server thread still starting
    }
    await new Promise((wait) => setTimeout(wait, 20));
  }
  throw new Error(`coworld never became healthy:\n${log}`);
}

// Two deliberately different movement policies so the recorded match has a real
// race rather than two identical populations. Both only ever return a cell the
// engine already offered as a legal candidate.
const policies = [
  // Population A: the reference greedy-best pick (the engine's own ranking).
  (candidates) => candidates[0].cell,
  // Population B: prospector - richest cell it can see, nearest on a tie.
  (candidates) => candidates.reduce((best, candidate) => {
    const wealth = candidate.sugar + candidate.spice;
    const bestWealth = best.sugar + best.spice;
    if (wealth !== bestWealth) return wealth > bestWealth ? candidate : best;
    return candidate.distance < best.distance ? candidate : best;
  }).cell,
];

function connectPolicy(slot) {
  return new Promise((resolveOpen, rejectOpen) => {
    const token = config.tokens[slot];
    const socket = new WebSocket(
      `ws://127.0.0.1:${port}/player?slot=${slot}&token=${token}`,
    );
    socket.addEventListener("open", () => resolveOpen(socket), { once: true });
    socket.addEventListener("error", () => rejectOpen(
      new Error(`player socket ${slot} failed`),
    ), { once: true });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.type !== "observation" || message.candidates.length === 0) return;
      socket.send(JSON.stringify({
        type: "action",
        requestId: message.requestId,
        cell: policies[slot](message.candidates),
      }));
    });
  });
}

await waitForHealth();
const sockets = await Promise.all(policies.map((_, slot) => connectPolicy(slot)));
const exitCode = await new Promise((resolveExit) => child.on("exit", resolveExit));
for (const socket of sockets) socket.close();
if (exitCode !== 0) throw new Error(`coworld exited ${exitCode}:\n${log}`);

const replay = JSON.parse(await readFile(output, "utf8"));
const results = JSON.parse(await readFile(resultsPath, "utf8"));
const bytes = (await readFile(output)).length;
console.log(`replay  ${output}`);
console.log(`format  ${replay.format}`);
console.log(`frames  ${replay.frames.length}  (${(bytes / 1e6).toFixed(2)} MB)`);
console.log(`grid    ${replay.frames[0].width}x${replay.frames[0].height}`);
console.log(`agents  t0=${replay.frames[0].agents.length}  ` +
  `tN=${replay.frames.at(-1).agents.length}`);
console.log(`results ${JSON.stringify(results.names)} scores=` +
  `${JSON.stringify(results.scores)} population=${JSON.stringify(results.population)}`);
