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
const replayByName = new Map(manifest.replays.map((entry) => [basename(entry.path), entry.path]));

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
    const path = replayByName.get(basename(url.pathname));
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
        `typeof frames !== "undefined" && frames.length === ${replay.expected_frames} && state.finished`),
      `${replay.scenario} adoption`, 30000,
    );
    const readyMs = performance.now() - started;
    await cdp.send("HeapProfiler.collectGarbage");
    const usedHeap = (await cdp.send("Runtime.getHeapUsage")).usedSize;

    const runtime = await evaluate(cdp, `(() => {
      setPlaying(false);
      const counts = { board: 0, terrain: 0 };
      const originalBoard = drawBoard;
      const originalTerrain = buildTerrain;
      drawBoard = (...args) => { counts.board += 1; return originalBoard(...args); };
      buildTerrain = (...args) => { counts.terrain += 1; return originalTerrain(...args); };
      return new Promise((resolve) => setTimeout(() => {
        counts.board = 0;
        counts.terrain = 0;
        setTimeout(() => {
          const paused = { ...counts };
          counts.board = 0;
          counts.terrain = 0;
          const samples = Math.min(100, frames.length - 1);
          const started = performance.now();
          for (let index = 1; index <= samples; index += 1) {
            state.cursor = index;
            tick(performance.now());
          }
          const advanceMs = (performance.now() - started) / samples;
          resolve({
            paused_paints_250ms: paused,
            sequential_advance_ms: advanceMs,
            board_pixels: board.width * board.height,
            terrain_pixels: terrain.width * terrain.height,
            frames: frames.length,
          });
        }, 250);
      }, 50));
    })()`);

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
      ...runtime,
    });
  }
  process.stdout.write(`${JSON.stringify({
    browser: manifest.chrome,
    budgets_enforced: manifest.budgets_enforced,
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
