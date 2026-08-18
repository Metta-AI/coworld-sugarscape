#!/usr/bin/env node

/* End-to-end Ruleset Studio Play test using Chrome's built-in CDP only. */

import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdir, mkdtemp, rm, writeFile} from "node:fs/promises";
import net from "node:net";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import process from "node:process";
import {setTimeout as delay} from "node:timers/promises";

const root = resolve(import.meta.dirname, "..");
const outputDir = resolve(root, process.env.COWORLD_STUDIO_BROWSER_OUTPUT || "build/studio");

function chromePath() {
  const candidates = [process.env.CHROME, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"].filter(Boolean);
  const found = candidates.find(existsSync);
  if (!found) throw new Error("Chrome or Chromium not found; set CHROME=/path/to/browser");
  return found;
}

async function unusedPort() {
  const server = net.createServer();
  const port = await new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolvePromise(server.address().port));
  });
  await new Promise(resolvePromise => server.close(resolvePromise));
  return port;
}

class Cdp {
  constructor(url) {
    this.nextId = 1; this.pending = new Map(); this.listeners = new Map(); this.socket = new WebSocket(url);
    this.opened = new Promise((resolvePromise, reject) => {
      this.socket.addEventListener("open", resolvePromise, {once: true});
      this.socket.addEventListener("error", reject, {once: true});
    });
    this.socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id); if (!pending) return; this.pending.delete(message.id);
        message.error ? pending.reject(new Error(JSON.stringify(message.error))) : pending.resolve(message.result); return;
      }
      for (const listener of this.listeners.get(message.method) || []) listener(message.params);
    });
  }
  on(method, listener) { this.listeners.set(method, [...(this.listeners.get(method) || []), listener]); }
  async send(method, params = {}) {
    await this.opened;
    const id = this.nextId++;
    const result = new Promise((resolvePromise, reject) => {
      const timer = setTimeout(() => reject(new Error(`CDP ${method} timed out`)), 15000);
      this.pending.set(id, {resolve: value => { clearTimeout(timer); resolvePromise(value); }, reject});
    });
    this.socket.send(JSON.stringify({id, method, params}));
    return result;
  }
  close() { this.socket.close(); }
}

async function retry(operation, label, timeout = 20000) {
  const deadline = Date.now() + timeout; let last;
  while (Date.now() < deadline) {
    try { const value = await operation(); if (value) return value; } catch (error) { last = error; }
    await delay(30);
  }
  throw new Error(`timed out waiting for ${label}: ${last || "no result"}`);
}

async function evaluate(cdp, expression, contextId) {
  const response = await cdp.send("Runtime.evaluate", {expression, contextId, awaitPromise: true, returnByValue: true});
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
  return response.result.value;
}

async function click(cdp, selector) {
  const clicked = await evaluate(cdp, `(() => { const node = document.querySelector(${JSON.stringify(selector)}); if (!node) return false; node.click(); return true; })()`);
  if (!clicked) throw new Error(`missing click target ${selector}`);
}

async function screenshot(cdp, name) {
  const capture = await cdp.send("Page.captureScreenshot", {format: "png", fromSurface: true});
  const path = join(outputDir, name);
  await writeFile(path, Buffer.from(capture.data, "base64"));
  return path;
}

function assert(condition, message) { if (!condition) throw new Error(message); }

async function assertFullViewer(cdp, viewerContext) {
  const parent = await evaluate(cdp, `(() => { const rect = selector => { const value = document.querySelector(selector).getBoundingClientRect(); return {width:value.width,height:value.height,bottom:value.bottom}; }; return {viewportHeight:innerHeight,iframe:rect('#replay-frame'),container:rect('.player-frame')}; })()`);
  const viewer = await evaluate(cdp, `(() => { const stage = document.querySelector('#stage').getBoundingClientRect(); return {viewportHeight:innerHeight,stage:{width:stage.width,height:stage.height,bottom:stage.bottom}}; })()`, viewerContext);
  assert(parent.container.bottom >= parent.viewportHeight - 20 && Math.abs(parent.iframe.width - parent.container.width) < 1 && Math.abs(parent.iframe.height - parent.container.height) < 1, `iframe does not fill the run area: ${JSON.stringify(parent)}`);
  assert(viewer.stage.bottom <= viewer.viewportHeight + 1 && Math.abs(viewer.stage.width / viewer.stage.height - 16 / 9) < 0.01, `viewer stage is clipped: ${JSON.stringify(viewer)}`);
}

const temporary = await mkdtemp(join(tmpdir(), "ruleset-studio-browser-"));
const [linkPort, apiPort, runPort, debugPort] = await Promise.all([unusedPort(), unusedPort(), unusedPort(), unusedPort()]);
const linkOrigin = `http://localhost:${linkPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const runOrigin = `http://localhost:${runPort}`;
const pageUrl = `${linkOrigin}/?${new URLSearchParams({api: apiOrigin, run: runOrigin})}`;
await mkdir(outputDir, {recursive: true});

const launcherOutput = [];
const launcher = spawn(resolve(root, ".venv/bin/python"), [resolve(root, "tools/ruleset_studio.py"), "--no-open", "--link-port", String(linkPort), "--api-port", String(apiPort), "--run-port", String(runPort), "--runs-dir", join(temporary, "runs")], {cwd: root, env: {...process.env, PYTHONHASHSEED: "0"}, stdio: ["ignore", "pipe", "pipe"]});
launcher.stdout.on("data", chunk => launcherOutput.push(chunk.toString()));
launcher.stderr.on("data", chunk => launcherOutput.push(chunk.toString()));
const chrome = spawn(chromePath(), ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--no-first-run", "--no-default-browser-check", "--window-size=1440,1000", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${join(temporary, "chrome")}`, "about:blank"], {stdio: ["ignore", "ignore", "pipe"]});
let chromeErrors = ""; chrome.stderr.on("data", chunk => { chromeErrors += chunk.toString(); });

let cdp;
try {
  await retry(async () => {
    if (launcher.exitCode !== null) throw new Error(launcherOutput.join(""));
    return (await fetch(linkOrigin)).ok;
  }, "launcher");
  const targets = await retry(async () => {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`); if (!response.ok) return null;
    const values = await response.json(); return values.find(target => target.type === "page") ? values : null;
  }, "Chrome debugger");
  cdp = new Cdp(targets.find(target => target.type === "page").webSocketDebuggerUrl);
  const contexts = new Map(); const exceptions = [];
  cdp.on("Runtime.executionContextCreated", ({context}) => { if (context.auxData?.isDefault && context.auxData?.frameId) contexts.set(context.auxData.frameId, context.id); });
  cdp.on("Runtime.executionContextsCleared", () => contexts.clear());
  cdp.on("Runtime.exceptionThrown", ({exceptionDetails}) => exceptions.push(exceptionDetails.exception?.description || exceptionDetails.text));
  await Promise.all([cdp.send("Page.enable"), cdp.send("Runtime.enable")]);
  await cdp.send("Emulation.setEmulatedMedia", {features: [{name: "prefers-reduced-motion", value: "no-preference"}]});
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", {source: `(() => {
    const nativeFetch = window.fetch.bind(window); window.__expireRuns = false;
    window.fetch = (input, options = {}) => {
      const url = String(input); const method = String(options.method || "GET").toUpperCase();
      if (window.__expireRuns && method === "GET" && /\\/api\\/run\\/[0-9a-f]{32}$/.test(url)) return Promise.resolve(new Response('{"error":"run not found"}', {status: 404, headers: {"Content-Type": "application/json"}}));
      return nativeFetch(input, options);
    };
  })();`});
  await cdp.send("Page.navigate", {url: pageUrl});
  await retry(() => evaluate(cdp, "document.querySelector('#valid-chip')?.textContent.includes('Valid')"), "Blockly validation");
  await click(cdp, "#settings-button");
  await evaluate(cdp, `(() => {
    const mode = document.querySelector('input[name="run-mode"][value="exploration"]'); mode.click();
    document.querySelector('#quick-button').click(); return true;
  })()`);
  await click(cdp, "#close-settings");
  await retry(() => evaluate(cdp, "document.querySelector('#valid-chip')?.textContent.includes('Valid') && document.querySelector('#play-button').getAttribute('aria-disabled') === 'false'"), "exploration validation");
  const editor = await screenshot(cdp, "ruleset-studio-editor.png");

  await click(cdp, "#play-button");
  const iframeUrl = await retry(() => evaluate(cdp, "document.querySelector('#replay-frame').src || null"), "live iframe");
  const match = iframeUrl.match(new RegExp(`^${runOrigin.replaceAll("/", "\\/")}\\/runs\\/([0-9a-f]{32})\\/client\\/replay$`));
  assert(match, `unexpected live iframe URL ${iframeUrl}`);
  const runId = match[1];
  const viewerFrame = await retry(async () => {
    const tree = await cdp.send("Page.getFrameTree"); const stack = [tree.frameTree];
    while (stack.length) { const current = stack.pop(); if (current.frame.url === iframeUrl) return current.frame; stack.push(...(current.childFrames || [])); }
    return null;
  }, "viewer frame");
  const viewerContext = await retry(() => contexts.get(viewerFrame.id), "viewer context");
  const initial = await retry(() => evaluate(cdp, `(() => frameCount() > 0 ? ({tick: frameStore.timestepAt(0), coworld: frameAt(0).coworld?.seats?.length || 0}) : null)()`, viewerContext), "tick zero");
  assert(initial.tick === 0 && initial.coworld > 0, "tick zero or coworld panel data missing");
  await assertFullViewer(cdp, viewerContext);
  await evaluate(cdp, `(() => { window.__handoff = {reset:false, advanced:false, minimum:Infinity}; const watch = () => { if (state.finished && !state.live) { const before = window.__handoff.minimum; window.__handoff.minimum = Math.min(before, state.cursor); window.__handoff.reset ||= state.cursor < 2; if (window.__handoff.reset && state.cursor > window.__handoff.minimum) window.__handoff.advanced = true; } requestAnimationFrame(watch); }; requestAnimationFrame(watch); })()`, viewerContext);
  const running = await screenshot(cdp, "ruleset-studio-running.png");
  await retry(() => evaluate(cdp, "Number(document.querySelector('#run-progress').value) > 0"), "progress");
  const status = await retry(async () => { const response = await fetch(`${apiOrigin}/api/run/${runId}`); const value = await response.json(); return value.state === "done" ? value : null; }, "completion", 30000);
  await retry(() => evaluate(cdp, "!document.querySelector('#verdict').hidden"), "verdict");
  const handoff = await retry(() => evaluate(cdp, `window.__handoff?.reset && window.__handoff?.advanced ? ({...window.__handoff, final:lastFrame()?.final, live:state.live, playing:state.playing, finalScore:lastFrame()?.coworld?.finalScores?.[0]}) : null`, viewerContext), "live replay handoff");
  assert(handoff.final === true && handoff.live === false && handoff.playing === true, "viewer did not settle into playing replay mode");
  assert(handoff.finalScore === status.results.scores[0], "viewer and API final scores differ");
  const verdict = await evaluate(cdp, "document.querySelector('.seat-score').textContent");
  assert(verdict.includes(Number(status.results.scores[0]).toLocaleString(undefined, {maximumFractionDigits: 3})), "Studio verdict differs from API results");
  await assertFullViewer(cdp, viewerContext);
  const settled = await screenshot(cdp, "ruleset-studio-settled.png");

  await click(cdp, "#editor-button");
  await click(cdp, "#score-chip");
  const canonical = await retry(() => evaluate(cdp, "document.querySelector('#replay-frame').src.includes('?replay=') && document.querySelector('#replay-frame').src"), "canonical reopen");
  assert(canonical === `${runOrigin}/runs/${runId}/client/replay?replay=/runs/${runId}/replay.bin`, "canonical reopen URL is wrong");

  await click(cdp, "#editor-button");
  await click(cdp, "#settings-button");
  await evaluate(cdp, `(() => { const ticks = document.querySelector('#timesteps'); ticks.value = '2000'; ticks.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  await click(cdp, "#close-settings");
  await retry(() => evaluate(cdp, "document.querySelector('#valid-chip').textContent.includes('Valid')"), "post-context validation");
  await click(cdp, "#play-button");
  await retry(() => evaluate(cdp, "document.querySelector('#play-button').textContent.includes('Stop')"), "Stop button");
  await click(cdp, "#play-button");
  await retry(() => evaluate(cdp, "document.querySelector('#run-status').textContent.startsWith('Cancelled')"), "cancellation", 15000);

  await click(cdp, "#editor-button");
  await evaluate(cdp, "window.__expireRuns = true");
  await click(cdp, "#play-button");
  await retry(() => evaluate(cdp, "!document.querySelector('#expired-run').hidden"), "expired recovery", 10000);
  await cdp.send("Emulation.setEmulatedMedia", {features: [{name: "prefers-reduced-motion", value: "reduce"}]});
  const audit = await evaluate(cdp, `({reduced:matchMedia('(prefers-reduced-motion: reduce)').matches, transition:getComputedStyle(document.querySelector('#play-button')).transitionDuration, positiveTabindex:document.querySelectorAll('[tabindex]:not([tabindex="0"]):not([tabindex="-1"])').length, overflow:document.documentElement.scrollWidth > innerWidth})`);
  assert(audit.reduced && audit.transition === "0s", `reduced motion failed: ${JSON.stringify(audit)}`);
  assert(audit.positiveTabindex === 0 && !audit.overflow, `keyboard/layout audit failed: ${JSON.stringify(audit)}`);
  assert(exceptions.length === 0, `browser exceptions: ${exceptions.join("\n")}`);
  console.log(JSON.stringify({run_id: runId, screenshots: [editor, running, settled], progress: status.tick, score: status.results.scores[0]}, null, 2));
} finally {
  cdp?.close();
  if (chrome.exitCode === null) chrome.kill("SIGTERM");
  if (launcher.exitCode === null) launcher.kill("SIGTERM");
  const waitExit = child => child.exitCode !== null ? Promise.resolve() : new Promise(resolvePromise => child.once("exit", resolvePromise));
  await Promise.all([waitExit(chrome), waitExit(launcher)].map(promise => Promise.race([promise, delay(8000)])));
  await rm(temporary, {recursive: true, force: true});
  if (chromeErrors && process.env.COWORLD_STUDIO_BROWSER_DEBUG) process.stderr.write(chromeErrors);
}
