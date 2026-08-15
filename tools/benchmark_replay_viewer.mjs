#!/usr/bin/env node

/* Drive the real self-contained viewer through Chrome DevTools Protocol.
 * No browser automation dependency is needed: modern Node provides WebSocket,
 * and Chrome exposes the small Runtime/Page/HeapProfiler surface used here. */

import { spawn } from "node:child_process";
import { readFile, rm } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const manifestPath = process.argv[2];
if (!manifestPath) throw new Error("usage: benchmark_replay_viewer.mjs MANIFEST.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const viewer = await readFile(manifest.viewer);
const artifactByName = new Map(manifest.replays.flatMap((entry) => [
  [basename(entry.path), entry.path],
  [basename(entry.oracle_path), entry.oracle_path],
]));

function listen(server) {
  return new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolvePromise(server.address().port));
  });
}

async function unusedPort() {
  const server = net.createServer();
  const port = await listen(server);
  await new Promise((resolvePromise) => server.close(resolvePromise));
  return port;
}

const web = http.createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (url.pathname === "/" || url.pathname === "/index.html") {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(viewer);
    return;
  }
  if (url.pathname.startsWith("/replays/")) {
    const path = artifactByName.get(basename(url.pathname));
    if (path) {
      response.writeHead(200, { "content-type": "application/octet-stream" });
      response.end(await readFile(path));
      return;
    }
  }
  response.writeHead(404);
  response.end("not found");
});
const webPort = await listen(web);

class Cdp {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(url);
    this.opened = new Promise((resolvePromise, reject) => {
      this.socket.addEventListener("open", resolvePromise, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
      else pending.resolve(message.result);
    });
  }

  async send(method, params = {}) {
    await this.opened;
    const id = this.nextId++;
    const result = new Promise((resolvePromise, reject) => {
      this.pending.set(id, { resolve: resolvePromise, reject });
    });
    this.socket.send(JSON.stringify({ id, method, params }));
    return result;
  }

  close() {
    this.socket.close();
  }
}

async function retry(operation, label, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = await operation();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await delay(25);
  }
  throw new Error(`timed out waiting for ${label}: ${lastError ?? "no result"}`);
}

async function evaluate(cdp, expression) {
  const response = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function navigate(cdp, url) {
  await cdp.send("Page.navigate", { url });
  await retry(
    () => evaluate(cdp, "document.readyState === 'complete'"),
    `page load for ${url}`,
  );
}

const debugPort = await unusedPort();
const profile = join(tmpdir(), `sugarscape-chrome-${process.pid}-${Date.now()}`);
const chrome = spawn(manifest.chrome, [
  "--headless=new",
  "--disable-gpu",
  "--disable-background-networking",
  "--disable-component-update",
  "--no-first-run",
  "--no-default-browser-check",
  `--remote-debugging-port=${debugPort}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });
const chromeExited = new Promise((resolvePromise) => chrome.once("exit", resolvePromise));
let chromeErrors = "";
chrome.stderr.on("data", (chunk) => { chromeErrors += chunk.toString(); });

let cdp;
try {
  const targets = await retry(async () => {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
    if (!response.ok) return null;
    const listed = await response.json();
    return listed.find((target) => target.type === "page") ? listed : null;
  }, "Chrome debugger");
  const page = targets.find((target) => target.type === "page");
  cdp = new Cdp(page.webSocketDebuggerUrl);
  await Promise.all([
    cdp.send("Page.enable"),
    cdp.send("Runtime.enable"),
    cdp.send("HeapProfiler.enable"),
  ]);

  const base = `http://127.0.0.1:${webPort}`;
  const results = [];

  for (const replay of manifest.replays) {
    // A fresh empty-viewer baseline per scenario prevents the first replay's
    // detached navigation context from being charged to the second replay.
    await navigate(cdp, `${base}/index.html?chrome=off`);
    await cdp.send("HeapProfiler.collectGarbage");
    const emptyHeap = (await cdp.send("Runtime.getHeapUsage")).usedSize;
    const started = performance.now();
    await navigate(cdp,
      `${base}/index.html?chrome=off&replay=${encodeURIComponent(`${base}/replays/${basename(replay.path)}`)}`);
    await retry(
      () => evaluate(cdp,
        `frameStore instanceof FrameStore && frameCount() === ${replay.expected_frames} && state.finished`),
      `${replay.scenario} adoption`, 30000,
    );
    const readyMs = performance.now() - started;
    const equivalent = await evaluate(cdp, `(async () => {
      const oracle = await (await fetch(
        ${JSON.stringify(`${base}/replays/`)} + ${JSON.stringify(basename(replay.oracle_path))}
      )).json();
      const difference = (left, right, path = "frame") => {
        if (Object.is(left, right)) return null;
        // The standalone Python converter delegates catalog scoring to the
        // engine while the viewer preserves its historical JS port. Dedicated
        // scorer tests pin that port; this oracle is for stored replay state.
        if (/\\.coworld\\.choices\\.\\d+\\.score$/.test(path)) return null;
        if (typeof left === "number" && typeof right === "number"
            && Math.abs(left - right) <= 1e-12) return null;
        if (typeof left !== "object" || left === null
            || typeof right !== "object" || right === null) {
          return path + ": " + JSON.stringify(left) + " != " + JSON.stringify(right);
        }
        const leftKeys = Object.keys(left);
        const rightKeys = Object.keys(right);
        if (leftKeys.length !== rightKeys.length) {
          return path + ": keys " + JSON.stringify(leftKeys) + " != " + JSON.stringify(rightKeys);
        }
        for (const key of leftKeys) {
          if (!Object.prototype.hasOwnProperty.call(right, key)) return path + "." + key + ": missing";
          const found = difference(left[key], right[key], path + "." + key);
          if (found) return found;
        }
        return null;
      };
      for (let index = 0; index < oracle.frames.length; index += 1) {
        const found = difference(frameStore.frameAt(index), oracle.frames[index]);
        if (found) return index + ": " + found;
      }
      const probes = [0, 31, 32, 33, 511, 999, 1000, 64, 1]
        .filter((index) => index < oracle.frames.length);
      for (const index of probes) {
        const found = difference(frameStore.frameAt(index), oracle.frames[index]);
        if (found) return index + ": " + found;
      }
      return true;
    })()`);
    if (equivalent !== true) {
      throw new Error(`${replay.scenario} FrameStore diverged from eager oracle at frame ${equivalent}`);
    }
    await cdp.send("HeapProfiler.collectGarbage");
    const usedHeap = (await cdp.send("Runtime.getHeapUsage")).usedSize;

    const runtime = await evaluate(cdp, `(() => {
      setPlaying(false);
      const counts = { board: 0, terrain: 0 };
      const timings = { board: 0, terrain: 0, hud: 0, race: 0, inequality: 0, tribe: 0 };
      const originalBoard = drawBoard;
      const originalTerrain = buildTerrain;
      const originalShowTerrain = showTerrain;
      const originalHud = drawHud;
      const originalRace = raceChart;
      const originalInequality = inequalityOverTime;
      const originalTribe = tribeShares;
      const timed = (name, operation) => (...args) => {
        const started = performance.now();
        const result = operation(...args);
        timings[name] += performance.now() - started;
        return result;
      };
      drawBoard = timed("board", (...args) => {
        counts.board += 1;
        return originalBoard(...args);
      });
      buildTerrain = (...args) => {
        counts.terrain += 1;
        return originalTerrain(...args);
      };
      showTerrain = timed("terrain", originalShowTerrain);
      drawHud = timed("hud", originalHud);
      raceChart = timed("race", originalRace);
      inequalityOverTime = timed("inequality", originalInequality);
      tribeShares = timed("tribe", originalTribe);
      return new Promise((resolve) => setTimeout(() => {
        counts.board = 0;
        counts.terrain = 0;
        setTimeout(() => {
          const paused = { ...counts };
          counts.board = 0;
          counts.terrain = 0;
          for (const name of Object.keys(timings)) timings[name] = 0;
          const samples = Math.min(100, frameCount() - 1);
          const firstSample = frameCount() - samples;
          const started = performance.now();
          for (let index = firstSample; index < frameCount(); index += 1) {
            state.cursor = index;
            tick(performance.now());
          }
          const advanceMs = (performance.now() - started) / samples;
          const componentMs = Object.fromEntries(Object.entries(timings)
            .map(([name, total]) => [name, total / samples]));
          let changedCells = 0;
          if (frameStore.mode === "v3") {
            for (let index = firstSample; index < frameCount(); index += 1) {
              const delta = index - 1;
              changedCells += frameStore.cellOffsets[delta + 1] - frameStore.cellOffsets[delta];
            }
          }
          resolve({
            paused_paints_250ms: paused,
            sequential_advance_ms: advanceMs,
            component_ms_per_advance: componentMs,
            changed_cells_per_advance: changedCells / samples,
            changed_cell_fraction: changedCells
              / (samples * frameAt(firstSample).cells.length),
            board_pixels: board.width * board.height,
            terrain_pixels: terrain.width * terrain.height,
            frames: frameCount(),
          });
        }, 250);
      }, 50));
    })()`);
    if (manifest.paint_budgets_enforced
        && (runtime.paused_paints_250ms.board !== 0
          || runtime.paused_paints_250ms.terrain !== 0)) {
      throw new Error(
        `${replay.scenario} painted while paused: ${JSON.stringify(runtime.paused_paints_250ms)}`,
      );
    }
    if (manifest.budgets_enforced
        && Math.max(0, usedHeap - emptyHeap) >= replay.retained_budget_bytes) {
      throw new Error(
        `${replay.scenario} retained ${usedHeap - emptyHeap} bytes, budget ${replay.retained_budget_bytes}`,
      );
    }

    results.push({
      scenario: replay.scenario,
      seed: manifest.seed,
      compressed_bytes: replay.compressed_bytes,
      raw_bytes: replay.raw_bytes,
      generation_ms: replay.generation_ms,
      ready_ms: Number(readyMs.toFixed(3)),
      empty_viewer_heap_bytes: emptyHeap,
      retained_heap_bytes: Math.max(0, usedHeap - emptyHeap),
      retained_budget_bytes: replay.retained_budget_bytes,
      every_frame_storage_oracle_equal: true,
      ...runtime,
    });
  }
  process.stdout.write(`${JSON.stringify({
    browser: manifest.chrome,
    budgets_enforced: manifest.budgets_enforced,
    paint_budgets_enforced: manifest.paint_budgets_enforced,
    results,
  })}\n`);
} catch (error) {
  process.stderr.write(`${error.stack ?? error}\n${chromeErrors}\n`);
  process.exitCode = 1;
} finally {
  if (cdp) cdp.close();
  if (chrome.exitCode === null && chrome.signalCode === null) chrome.kill("SIGTERM");
  await Promise.race([chromeExited, delay(3000)]);
  if (chrome.exitCode === null && chrome.signalCode === null) {
    chrome.kill("SIGKILL");
    await chromeExited;
  }
  await new Promise((resolvePromise) => web.close(resolvePromise));
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
