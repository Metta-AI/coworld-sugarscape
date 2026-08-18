#!/usr/bin/env node

/* The viewer's own model, driven headlessly.
 *
 * These assertions need NO Nim toolchain, no server, and no private package -
 * they read the GENERATED document off disk and run its script in a sandbox with
 * a DOM stub. They used to live in smoke_coworld.mjs and source the script by
 * fetching a running binary, which gated four hundred lines of pure-model
 * coverage - socket derivation, the density ramp, the transport, the feed
 * ledger, reduced motion, failure focus, the artifact path - behind a
 * credential that a fork does not have. Now CI runs them on every push.
 *
 * The protocol and server-lifetime assertions stay in smoke_coworld.mjs, which
 * does need the binary.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import vm from "node:vm";

const root = resolve(import.meta.dirname, "..");
const viewerHtml = await readFile(join(root, "replay-viewer/index.html"), "utf8");
const goldenFixture = JSON.parse(await readFile(
  join(root, "tests/fixtures/replay-viewer-v3-golden.json"), "utf8",
));

// The hosted embed is a sandboxed iframe behind a proxy that cannot reach a CDN,
// and any separate sub-resource 404s under the rewritten base href.
assert.match(viewerHtml, /<base href="\/">/);
assert.doesNotMatch(viewerHtml, /https?:\/\/(fonts|cdn|unpkg|jsdelivr)/);
assert.doesNotMatch(viewerHtml, /<(script|link)[^>]+\b(src|href)="(?!data:)/);
// Drive the real viewer script in a sandbox with a DOM stub, so the derived
// broadcast model is covered without a browser.
const viewerTimers = { animation: null, animationStarts: 0, pending: [] };
const documentListeners = new Map();
const windowListeners = new Map();
const gradient = { addColorStop() {} };
const pattern = { setTransform() {} };
const canvasContext = new Proxy({
  createRadialGradient: () => gradient,
  createLinearGradient: () => gradient,
  createPattern: () => pattern,
  createImageData: (width, height) => ({ data: new Uint8ClampedArray(width * height * 4) }),
  measureText: () => ({ width: 0 }),
}, {
  get: (target, key) => (key in target ? target[key] : () => {}),
  set: () => true,
});
// Elements are MEMOISED BY ID. Handing out a fresh stub per lookup made every
// attribute the viewer sets - the scrub's announced value, the toggle's pressed
// state, where a failure puts the focus - unobservable from here.
const elements = new Map();
const stageBox = { width: 1600 };
function fakeElement(id = "") {
  const classes = new Set();
  const attributes = new Map();
  return new Proxy({
    id,
    attributes,
    focused: 0,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    style: { setProperty() {}, removeProperty() {}, getPropertyValue: () => "" },
    getContext: () => canvasContext,
    // The stage's width is what chooses the density ramp, so the suite has to be
    // able to move it.
    getBoundingClientRect: () => ({ left: 0, top: 0, width: stageBox.width, height: 1 }),
    querySelector: (selector) => elementFor(selector.replace(/^#/, "")),
    setAttribute: (name, value) => attributes.set(name, String(value)),
    getAttribute: (name) => (attributes.has(name) ? attributes.get(name) : null),
    addEventListener() {},
    focus() { this.focused += 1; },
    contains: () => false,
    width: 0,
    height: 0,
    value: "0",
    min: "0",
    max: "0",
    innerHTML: "",
    textContent: "",
  }, {
    get: (target, key) => (key in target ? target[key] : () => {}),
    set: (target, key, value) => { target[key] = value; return true; },
  });
}
function elementFor(id) {
  if (!elements.has(id)) elements.set(id, fakeElement(id));
  return elements.get(id);
}
// A session-storage stub that can also be made to THROW, which is what a
// sandboxed iframe with storage denied actually does.
const storage = new Map();
const sessionStorageStub = {
  denied: false,
  getItem(key) {
    if (sessionStorageStub.denied) throw new Error("storage denied");
    return storage.has(key) ? storage.get(key) : null;
  },
  setItem(key, value) {
    if (sessionStorageStub.denied) throw new Error("storage denied");
    storage.set(key, String(value));
  },
  removeItem(key) {
    if (sessionStorageStub.denied) throw new Error("storage denied");
    storage.delete(key);
  },
};
// A media query the suite can flip, so the reduced-motion LISTENER is covered
// rather than only the value it happened to have at load.
const motion = { matches: false, listeners: [] };
let nowValue = 0;
const viewerContext = vm.createContext({
  console,
  // The loader decodes replay BYTES, so the sandbox needs the text codecs. It is
  // deliberately NOT given DecompressionStream: a v1 recording is plain JSON, so
  // the uncompressed fallback is the path these tests should be taking, and if
  // that path ever regresses they must fail rather than quietly inflate.
  TextDecoder,
  TextEncoder,
  document: {
    hidden: false,
    createElement: () => fakeElement(),
    getElementById: (id) => elementFor(id),
    querySelector: (selector) => elementFor(selector.replace(/^#/, "")),
    activeElement: null,
    body: null,
    // layoutStage publishes the live board width to the stylesheet through a
    // custom property, so the transport lane can follow a board that moves.
    documentElement: fakeElement("documentElement"),
    addEventListener: (name, fn) => documentListeners.set(name, fn),
  },
  // The sandbox exercises the pure model; animation frames are driven by hand
  // below so playback never races the assertions.
  // A socket the suite can speak THROUGH, so the message handler, the silence
  // timer and the idle settle can be exercised together rather than one at a
  // time. Driving isRenderableFrame directly is why the two-of-them-together
  // bugs went unnoticed.
  WebSocket: class {
    constructor() {
      this.listeners = new Map();
      lastSocketRef.socket = this;
    }
    addEventListener(name, fn) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(fn);
    }
    fire(name, event) {
      for (const fn of this.listeners.get(name) ?? []) fn(event);
    }
    close() {}
  },
  DOMMatrix: class { translate() { return this; } scale() { return this; } },
  location: { host: "localhost", protocol: "http:", pathname: "/client/global", search: "" },
  performance: { now: () => nowValue },
  URLSearchParams,
  sessionStorage: sessionStorageStub,
  matchMedia: (query) => ({
    media: query,
    get matches() { return motion.matches; },
    addEventListener: (name, fn) => motion.listeners.push(fn),
  }),
  // loadArtifact's own path, which had no coverage at all: the suite hands it a
  // payload rather than a network.
  // The viewer reads BYTES now, because a v3 recording is deflate-compressed and
  // the same path has to take both generations. The stub serves the payload the
  // way the network would, so the test still exercises the real decode.
  fetch: () => (viewerContext.payloadForTest
    ? Promise.resolve({
      ok: true,
      json: async () => viewerContext.payloadForTest,
      arrayBuffer: async () => new TextEncoder()
        .encode(JSON.stringify(viewerContext.payloadForTest)).buffer,
    })
    : Promise.reject(new Error("no network in the sandbox"))),
  // Real timers, driven by hand below. Stubbing these to no-ops made every
  // timer-based path - the silence timeout, the idle settle, the end-card hold -
  // structurally invisible to this suite.
  requestAnimationFrame: (fn) => {
    viewerTimers.animation = fn;
    viewerTimers.animationStarts += 1;
    return viewerTimers.animationStarts;
  },
  cancelAnimationFrame: () => { viewerTimers.animation = null; },
  setTimeout: (fn, delay) => { viewerTimers.pending.push({ fn, delay }); return viewerTimers.pending.length; },
  clearTimeout: (id) => { if (id) viewerTimers.pending[id - 1] = null; },
});
viewerContext.window = viewerContext;
viewerContext.addEventListener = (name, fn) => windowListeners.set(name, fn);
viewerContext.devicePixelRatio = 1;
viewerContext.ResizeObserver = class { observe() {} };
const lastSocketRef = { socket: null };
viewerContext.payloadForTest = null;
Object.defineProperty(viewerContext, "lastSocket", { get: () => lastSocketRef.socket });
// Run every timer the viewer has queued, once. The silence timeout and the idle
// settle are real behaviour and were structurally invisible while these were
// no-ops.
viewerContext.runPendingTimers = () => {
  const queued = viewerTimers.pending.slice();
  viewerTimers.pending.length = 0;
  for (const entry of queued) if (entry) entry.fn();
};
viewerContext.viewerTimersReset = () => { viewerTimers.pending.length = 0; };
viewerContext.paintLoopState = () => ({
  active: viewerTimers.animation !== null,
  starts: viewerTimers.animationStarts,
  pendingTimers: viewerTimers.pending.filter(Boolean).length,
});
viewerContext.runAnimationFrame = (now) => {
  const callback = viewerTimers.animation;
  viewerTimers.animation = null;
  if (callback) callback(now);
};
viewerContext.fireVisibility = (hidden) => {
  viewerContext.document.hidden = hidden;
  documentListeners.get("visibilitychange")?.();
};
viewerContext.setNow = (value) => { nowValue = value; };
viewerContext.fireMotionChange = (matches) => {
  motion.matches = matches;
  for (const listener of motion.listeners) listener({ matches });
};
viewerContext.setStageWidth = (width) => { stageBox.width = width; };
viewerContext.denyStorage = (denied) => { sessionStorageStub.denied = denied; };
viewerContext.elementFor = elementFor;
const viewerScript = viewerHtml.match(/<script>([\s\S]*)<\/script>/)?.[1];
assert.ok(viewerScript, "viewer script must be embedded");
vm.runInContext(viewerScript, viewerContext);

// The socket must be derived from the page's OWN path. Under the Observatory
// proxy the document is served at <prefix>/client/replay and the socket lives
// at the sibling <prefix>/replay; an absolute path resolves off the prefix and
// black-screens the embed.
const socketUrls = JSON.parse(vm.runInContext(`
  JSON.stringify([
    "/client/replay",
    "/client/global",
    "/clients/replay",
    "/v2/coworlds/abc/proxy/client/replay",
  ].map((path) => { location.pathname = path; return socketUrl(); }));
`, viewerContext));
assert.deepEqual(socketUrls, [
  "ws://localhost/replay",
  "ws://localhost/global",
  "ws://localhost/replay",
  "ws://localhost/v2/coworlds/abc/proxy/replay",
]);

function sandboxFrame(timestep, agents, extra = {}) {
  return JSON.stringify({
    streamId: "smoke",
    timestep,
    maxTimestep: 40,
    width: 2,
    height: 2,
    cells: [[1, 0, 0], [2, 0, 0], [0, 0, 0], [4, 0, 0]],
    agents,
    links: [],
    slots: [{ name: "Alpha" }, { name: "Beta" }],
    stats: { giniCoefficient: 0.3, carryingCapacity: 4 },
    ...extra,
  });
}
const settler = (id, slot, cell, sugar) => ({
  id, slot, cell, sugar, spice: 0, age: 1, decisionModel: `p${slot}`,
  sugarMetabolism: 1, spiceMetabolism: 0, movement: 1, vision: 1,
  depressed: false, sick: false, race: -1, sex: "male", tribe: -1,
});

// Hashing canonical JSON covers every nested cell, agent, statistic, and coworld
// field. The fixture was captured from the removed eager materializer, so this
// remains an independent oracle after production became delta-native.
const goldenReplay = JSON.parse(vm.runInContext(`(() => {
  const store = FrameStore.fromV3(${JSON.stringify(goldenFixture.document)});
  const sought = ${JSON.stringify(goldenFixture.expected.seek_order)}
    .map((index) => store.frameAt(index).timestep);
  if (store.cache.size > 3) throw new Error("FrameStore materialization cache exceeded three frames");
  return JSON.stringify({
    format: "sugarscape.replay.v1",
    config: store.config,
    frames: Array.from({ length: store.count }, (_, index) => store.frameAt(index)),
    sought,
  });
})()`, viewerContext));
const frameHash = (frame) => createHash("sha256").update(JSON.stringify(frame)).digest("hex");
const goldenHashes = goldenReplay.frames.map(frameHash);
if (goldenFixture.expected.frame_sha256.length === 0) {
  console.log(`GOLDEN_FRAME_HASHES=${JSON.stringify(goldenHashes)}`);
}
assert.deepEqual(goldenHashes, goldenFixture.expected.frame_sha256,
  "every materialized v3 frame must remain byte-canonically equivalent to the golden oracle");
const numericPacking = JSON.parse(vm.runInContext(`JSON.stringify([
  losslessNumericArray([-32768, 32767]).constructor.name,
  losslessNumericArray([32768]).constructor.name,
  losslessNumericArray([1.5]).constructor.name,
  losslessNumericArray([0.1]).constructor.name,
  losslessNumericArray([Number.MAX_SAFE_INTEGER]).constructor.name,
])`, viewerContext));
assert.deepEqual(numericPacking,
  ["Int16Array", "Int32Array", "Float32Array", "Float64Array", "Float64Array"],
  "numeric planes must use the narrowest representation that is exactly lossless");

const goldenModel = JSON.parse(vm.runInContext(`
  resetStream();
  for (const frame of ${JSON.stringify(goldenReplay.frames)}) recordFrame(frame);
  const compactEvent = (event) => {
    const out = {
      index: event.index, timestep: event.timestep, kind: event.kind,
    };
    if (event.kind === "lead") {
      Object.assign(out, { slot: event.slot, name: event.name, margin: event.margin });
    } else {
      Object.assign(out, {
        count: event.count, cause: event.cause, bySlot: event.bySlot,
        lost: event.agents.map((agent) => [agent.id, agent.cell, agent.slot]),
      });
    }
    return out;
  };
  const sought = ${JSON.stringify(goldenFixture.expected.seek_order)}.map((index) => {
    seek(index);
    return frameAt(currentIndex());
  });
  JSON.stringify({ wealthSeries, events: events.map(compactEvent), sought });
`, viewerContext));
assert.deepEqual(goldenModel.wealthSeries, goldenFixture.expected.wealth_series,
  "historical summary series must match the brute-force golden values");
assert.deepEqual(goldenModel.events, goldenFixture.expected.events,
  "semantic event history must match the brute-force golden values");
assert.deepEqual(goldenModel.sought.map(frameHash),
  goldenFixture.expected.seek_order.map((index) => goldenHashes[index]),
  "random seeking must return the exact indexed materialized frame");

// A duo is one world with two independently scored objectives. Both assigned
// targets must be visible together, and the player glyphs must remain distinct
// without borrowing the culture colour carried by the gnomes themselves.
const duoPresentation = JSON.parse(vm.runInContext(`(() => {
  const store = FrameStore.fromV3(${JSON.stringify(goldenFixture.document)});
  const frame = store.frameAt(2);
  targetPick.hidden = false;
  const pickerShown = fillTargetPicker(frame);
  return JSON.stringify({
    markup: targetHistogram(frame, 0, 0, 500, 358),
    pickerShown,
    pickerHidden: targetPick.hidden,
    playerOne: playerShape(10, 10, 0, 5, "white", "black", 1),
    playerTwo: playerShape(10, 10, 1, 5, "white", "black", 1),
  });
})()`, viewerContext));
assert.match(duoPresentation.markup, /Alpha/);
assert.match(duoPresentation.markup, /Beta/);
assert.match(duoPresentation.markup, /fixture\.alpha/);
assert.match(duoPresentation.markup, /fixture\.beta/);
assert.match(duoPresentation.markup, /0\.500/);
assert.match(duoPresentation.markup, /0\.250/);
assert.match(duoPresentation.markup, /filled bars = measured/);
assert.equal(duoPresentation.pickerShown, false,
  "a single target picker must not replace either assigned duo target");
assert.equal(duoPresentation.pickerHidden, true);
assert.match(duoPresentation.playerOne, /^<circle/);
assert.match(duoPresentation.playerTwo, /^<path/);
assert.notEqual(duoPresentation.playerOne, duoPresentation.playerTwo);

const targetLayouts = JSON.parse(vm.runInContext(`(() => {
  const within = (card, bottom) => card.y + card.height <= bottom;
  const chartWithin = (card, seat) => {
    const markup = compactTargetReading(seat, card.x, card.y, card.width, card.height);
    const axis = markup.match(/<line x1="[^"]+" y1="([^"]+)" x2="[^"]+" y2="([^"]+)"/);
    return axis && Number(axis[1]) <= card.y + card.height && Number(axis[2]) <= card.y + card.height;
  };
  setStageWidth(640); state.largeText = false; measureDensity();
  const compactDuo = targetReadingLayout(2, dense(), 0, 0, 500, 358);
  const compactFour = targetReadingLayout(4, dense(), 0, 0, 500, 358);
  const longSeat = {
    seat: 0, name: "A player with a deliberately long display name",
    variable: "majority_tribe_share", targetId: "tribe.convergence",
    targetProbs: [0.5, 0.5], measuredProbs: [0.4, 0.6], score: 0.75,
  };
  const longMarkup = compactTargetReading(
    longSeat, compactDuo[0].x, compactDuo[0].y, compactDuo[0].width, compactDuo[0].height,
  );
  const compactDuoChartsBounded = compactDuo.every((card) => chartWithin(card, longSeat));
  const compactFourChartsBounded = compactFour.every((card) => chartWithin(card, longSeat));
  setStageWidth(1600); measureDensity();
  const sparseDuo = targetReadingLayout(2, dense(), 0, 0, 500, 358);
  return JSON.stringify({
    compactDuo, compactFour, sparseDuo, longMarkup,
    compactDuoBounded: compactDuo.every((card) => within(card, 344)),
    compactFourBounded: compactFour.every((card) => within(card, 344)),
    compactDuoChartsBounded, compactFourChartsBounded,
  });
})()`, viewerContext));
assert.equal(targetLayouts.compactDuoBounded, true);
assert.equal(targetLayouts.compactFourBounded, true);
assert.equal(targetLayouts.compactDuoChartsBounded, true);
assert.equal(targetLayouts.compactFourChartsBounded, true);
assert.equal(new Set(targetLayouts.compactDuo.map((card) => card.column)).size, 2,
  "dense duo targets must use columns to preserve chart height");
assert.equal(new Set(targetLayouts.sparseDuo.map((card) => card.row)).size, 2,
  "full-size duo targets remain a vertical pair");
assert.match(targetLayouts.longMarkup, /…/,
  "long production player and target labels must elide inside their card");
assert.doesNotMatch(targetLayouts.longMarkup, /majority_tribe_share · tribe\.convergence/);

const soloPicker = JSON.parse(vm.runInContext(`(() => {
  targetOptionsKey = ""; targetChoice = null; targetPick.hidden = true;
  const shown = fillTargetPicker({ coworld: {
    seats: [{ seat: 0, targetId: "solo.target" }],
    choices: [{ id: "solo.target", assigned: true, score: 1 }],
  } });
  return JSON.stringify({ shown, hidden: targetPick.hidden });
})()`, viewerContext));
assert.deepEqual(soloPicker, { shown: true, hidden: false },
  "solo episodes retain counterfactual target browsing");

const badgeCommands = JSON.parse(vm.runInContext(`(() => {
  const commands = [];
  const alphaStack = [];
  const context = {
    globalAlpha: 0.25,
    save() { alphaStack.push(this.globalAlpha); commands.push(["save", this.globalAlpha]); },
    restore() { this.globalAlpha = alphaStack.pop(); commands.push(["restore", this.globalAlpha]); },
    beginPath() { commands.push("begin"); }, closePath() { commands.push("close"); },
    arc() { commands.push("arc"); }, moveTo() { commands.push("move"); },
    lineTo() { commands.push("line"); }, rect() { commands.push("rect"); },
    fill() { commands.push(["fill", this.globalAlpha]); },
    stroke() { commands.push(["stroke", this.globalAlpha]); },
  };
  drawPlayerBadge(context, 10, 10, 0, 12);
  drawPlayerBadge(context, 10, 10, 1, 12);
  return JSON.stringify({ commands, finalAlpha: context.globalAlpha });
})()`, viewerContext));
assert.equal(badgeCommands.commands.filter((command) => command[0] === "save").length, 2);
assert.equal(badgeCommands.commands.filter((command) => command[0] === "restore").length, 2);
assert.deepEqual(badgeCommands.commands.filter((command) => command[0] === "fill").map((command) => command[1]), [1, 1]);
assert.deepEqual(badgeCommands.commands.filter((command) => command[0] === "stroke").map((command) => command[1]), [1, 1]);
assert.equal(badgeCommands.finalAlpha, 0.25);
assert.match(badgeCommands.commands.flat().join(" "), /arc.*restore.*move.*line/,
  "canvas badges must draw the same circle/diamond identities as the HUD");
assert.doesNotMatch(viewerHtml, /yFor\(0\.4\)/,
  "the removed inequality guide must stay out of the generated viewer");

const scoreMethods = JSON.parse(vm.runInContext(`(() => {
  const target = TARGET_CATALOG.find((entry) => entry.id === "wealth.skewed-gini-0.5");
  const collapsed = {
    bins: target.bins,
    probs: target.probs.map((_value, index) => index === 0 ? 1 : 0),
    sample_count: 344,
  };
  const tieTarget = { bins: [0, 1, 4], probs: [0.5, 0.5] };
  return JSON.stringify({
    current: scoreAgainst(target, collapsed, "w1-hyperbolic/1"),
    legacy: scoreAgainst(target, collapsed, "w1-support/1"),
    unknown: scoreAgainst(target, collapsed, "future-method/1"),
    empty: scoreAgainst(target, { ...collapsed, sample_count: 0 }, "w1-hyperbolic/1"),
    tieScale: targetScale(tieTarget.probs, tieTarget.bins),
  });
})()`, viewerContext));
assert.ok(Math.abs(scoreMethods.current - 0.45841492247218735) < 1e-15);
assert.ok(Math.abs(scoreMethods.legacy - 0.9601722666666665) < 1e-15);
assert.equal(scoreMethods.unknown, null, "unknown scoring methods must fail closed");
assert.equal(scoreMethods.empty, 0, "empty measurements retain the engine's hard zero");
assert.equal(scoreMethods.tieScale, 1, "median ties use the leftmost bin width");
vm.runInContext("resetStream()", viewerContext);

const model = JSON.parse(vm.runInContext(`
  recordFrame(${sandboxFrame(0, [settler(1, 0, 0, 10), settler(2, 1, 1, 4)])});
  recordFrame(${sandboxFrame(1, [settler(1, 0, 0, 11), settler(2, 1, 1, 5)])});
  // Beta overtakes and Alpha's settler starves in the same timestep.
  recordFrame(${sandboxFrame(2, [settler(2, 1, 1, 30)])});
  // A repeat of a timestep already seen must update in place, not append.
  recordFrame(${sandboxFrame(2, [settler(2, 1, 1, 31)])});
  JSON.stringify({
    frames: frameCount(),
    timesteps: Array.from({ length: frameCount() }, (_, index) => frameAt(index).timestep),
    scheduledEnd: state.maxTimestep,
    standing: ranked(lastFrame()).map((row) => [row.name, row.score]),
    events: events.map((event) => [event.timestep, event.kind, event.count ?? event.name]),
  });
`, viewerContext));
assert.deepEqual(model.timesteps, [0, 1, 2]);
assert.equal(model.frames, 3);
// The clock counts to the configured limit, not to the last recorded timestep.
assert.equal(model.scheduledEnd, 40);
assert.deepEqual(model.standing, [["Beta", 31], ["Alpha", 0]]);
// Beats are derived by diffing frames: a death and a lead change at t2.
assert.deepEqual(model.events, [[2, "death", 1], [2, "lead", "Beta"]]);

// Replacing a timestep must update everything derived from it. It used to swap
// the frame and return, leaving the race chart describing the overwritten one.
const afterReplace = JSON.parse(vm.runInContext(`
  recordFrame(${sandboxFrame(2, [settler(2, 1, 1, 900)])});
  JSON.stringify({
    frames: frameCount(),
    series: wealthSeries.at(-1).scores,
    standing: ranked(lastFrame()).map((row) => row.score),
  });
`, viewerContext));
assert.equal(afterReplace.frames, 3, "a repeated timestep replaces, never appends");
assert.deepEqual(afterReplace.series, [0, 900], "the chart follows the replacement");
assert.deepEqual(afterReplace.standing, [900, 0], "and so does the standing");

// Only the newest 64 v1 inputs remain as full frames. Replacing an older frame
// exercises the packed slow path and must rebuild summaries and lead events all
// the way through the suffix.
const oldReplacement = JSON.parse(vm.runInContext(`(() => {
  resetStream();
  const base = ${sandboxFrame(
    0, [settler(1, 0, 0, 10), settler(2, 1, 1, 5)],
  )};
  const at = (step, beta) => ({
    ...base,
    timestep: step,
    agents: base.agents.map((agent) => ({ ...agent, sugar: agent.slot === 1 ? beta : 10 })),
  });
  for (let step = 0; step < 70; step += 1) recordFrame(at(step, step === 69 ? 20 : 5));
  const before = JSON.stringify(frameAt(1));
  recordFrame(at(1, 30));
  return JSON.stringify({
    count: frameCount(),
    tail: frameStore.legacyTail.size,
    oldChanged: JSON.stringify(frameAt(1)) !== before,
    leaders: events.filter((event) => event.kind === "lead")
      .map((event) => [event.timestep, event.slot]),
  });
})()`, viewerContext));
assert.deepEqual(oldReplacement, {
  count: 70,
  tail: 64,
  oldChanged: true,
  leaders: [[1, 1], [2, 0], [69, 1]],
});

const midJoin = JSON.parse(vm.runInContext(`(() => {
  resetStream();
  recordFrame(${sandboxFrame(40, [settler(1, 0, 0, 10)])});
  return JSON.stringify({ timestep: firstFrame().timestep, joinedLate: joinedLate() });
})()`, viewerContext));
assert.deepEqual(midJoin, { timestep: 40, joinedLate: true });
vm.runInContext("resetStream()", viewerContext);

// A frame the viewer cannot render must be REJECTED, not half-drawn behind a
// confident HUD. Wrong format, no slots, and a malformed lattice all count.
const guards = JSON.parse(vm.runInContext(`
  JSON.stringify({
    good: isRenderableFrame(${sandboxFrame(9, [])}),
    wrongFormat: isRenderableFrame(Object.assign(${sandboxFrame(9, [])}, { format: "sugarscape.frame.v2" })),
    noSlots: isRenderableFrame(Object.assign(${sandboxFrame(9, [])}, { slots: [] })),
    badCells: isRenderableFrame(Object.assign(${sandboxFrame(9, [])}, { cells: "nope" })),
  });
`, viewerContext));
assert.deepEqual(guards, { good: true, wrongFormat: false, noSlots: false, badCells: false });

// The manifest permits up to 16 populations while the palette lists four.
// Indexing the palette raw threw on the fifth population and blanked the whole
// overlay, and silently dropped those populations' wealth from every total.
const manySeats = JSON.parse(vm.runInContext(`
  const wide = ${sandboxFrame(0, [])};
  wide.slots = Array.from({ length: 16 }, (_, index) => ({ name: \`Population \${index}\` }));
  wide.agents = wide.slots.map((_, index) => (${settler.toString()})(index, index, index % 4, 5));
  recordFrame(wide);
  JSON.stringify({
    seats: wide.slots.map((_, index) => Boolean(seatOf(index) && seatOf(index).color)),
    counted: ranked(wide).reduce((sum, row) => sum + row.population, 0),
    scored: ranked(wide).filter((row) => row.score > 0).length,
  });
`, viewerContext));
assert.ok(manySeats.seats.every(Boolean), "every declared population must get a colour");
assert.equal(manySeats.counted, 16, "no population may be dropped from the standing");
assert.equal(manySeats.scored, 16, "no population may be silently scored zero");

// A stream from a new server run resets rather than interleaving.
const afterRestart = JSON.parse(vm.runInContext(`
  recordFrame(${sandboxFrame(0, [settler(9, 0, 0, 1)], { streamId: "second" })});
  JSON.stringify({ frames: frameCount(), events: events.length });
`, viewerContext));
assert.deepEqual(afterRestart, { frames: 1, events: 0 });
// A restart must not inherit the previous episode's schedule, or the clock
// counts to the old buzzer and the race chart is scaled to the wrong length.
assert.equal(
  Number(vm.runInContext("String(state.maxTimestep)", viewerContext)),
  40,
  "the new stream's own maxTimestep must replace the old one",
);

// EVERY overlay panel must render for every population count the manifest
// permits. Nothing here used to call the markup functions at all, which is
// exactly how a raw palette index shipped and blanked the whole HUD on a
// five-population match while the suite stayed green.
for (const seats of [1, 2, 3, 5, 16]) {
  const rendered = vm.runInContext(`
    (() => {
      const wide = ${sandboxFrame(4, [])};
      wide.slots = Array.from({ length: ${seats} }, (_, i) => ({ name: \`Population \${i}\` }));
      wide.agents = wide.slots.map((_, i) => (${settler.toString()})(i, i, i % 4, 5 + i));
      resetStream();
      recordFrame(wide);
      drawHud(wide, 0);
      drawBeats(wide, 0);
      state.finished = true;
      state.cursor = 0;
      drawBeats(wide, 0);
      return standingsLayer.innerHTML.length + ":" + beatsLayer.innerHTML.length;
    })()
  `, viewerContext);
  const [standing, beats] = rendered.split(":").map(Number);
  assert.ok(standing > 0, `${seats} populations must render a standings overlay`);
  assert.ok(beats > 0, `${seats} populations must render an end card`);
}

/* NO beat plate covers the board. Every beat is a LINE, a row or a marker.
 *
 * Two plates died the same death. The die-off went first: it dropped across the
 * middle of the board for two seconds whenever three settlers went at once,
 * which on the shipped config is most timesteps. The LEAD CHANGE plate outlived
 * it and then failed the same test — owner call, on a plate covering roughly a
 * third of the lattice.
 *
 * Neither reading was lost with its plate, and that is what makes the removal
 * safe rather than merely quieter: a lead change is still a marked step in the
 * lead band, a "takes the lead" row in the feed, the running count over the race
 * panel and a clause on the end card. This pins all of it — that neither kind of
 * event queues a beat, that no plate text survives in the document, that the
 * end card still renders, and that the strip carries one point per timestep. */
assert.doesNotMatch(viewerHtml, /DIE-OFF/,
  "no die-off plate may survive anywhere in the served document");
assert.doesNotMatch(viewerHtml, /LEAD CHANGE/,
  "no lead-change plate may survive anywhere in the served document");
assert.doesNotMatch(viewerHtml, /moves ahead by/,
  "nor the plate's detail line");

const dieOff = JSON.parse(vm.runInContext(`
  (() => {
    const at = (id, slot, cell, sugar) => (${settler.toString()})(id, slot, cell, sugar);
    resetStream();
    const open = ${sandboxFrame(0, [])};
    open.agents = [at(1, 0, 0, 10), at(2, 0, 1, 10), at(3, 0, 2, 10), at(4, 1, 3, 4)];
    recordFrame(open);
    // Three of Alpha's four settlers go at once - the old die-off threshold.
    const cull = ${sandboxFrame(1, [])};
    cull.agents = [at(1, 0, 0, 11), at(4, 1, 3, 5)];
    recordFrame(cull);
    onFrameEntered(1, 0);
    // beatsSignature short-circuits a repaint that would not change anything, so
    // clear it or the second read below returns the first read's markup.
    beatsSignature = "";
    drawBeats(frameAt(1));
    const afterDeaths = beatsLayer.innerHTML;
    // And now Beta overtakes, which used to earn the surviving plate.
    const overtake = ${sandboxFrame(2, [])};
    overtake.agents = [at(1, 0, 0, 11), at(4, 1, 3, 90)];
    recordFrame(overtake);
    onFrameEntered(2, 0);
    beatsSignature = "";
    drawBeats(frameAt(2));
    const afterLead = beatsLayer.innerHTML;
    // The overtake must still be RECORDED even though it no longer interrupts -
    // this is what the lead band, the feed row and the end card's clause read.
    const leadsRecorded = events.filter((event) => event.kind === "lead").length;
    const deathsRecorded = events.filter((event) => event.kind === "death").length;
    // The strip itself, at two timesteps, against a scale of its own.
    const strip = (until, at = (t) => t) => settlerStrip(frameAt(until), {
      big: false, left: 0, plotW: 100, scaleX: at, scheduled: 40, footY: 60,
      top: 0, height: 50,
      visible: wealthSeries.filter((point) => point.timestep <= until),
    });
    const pointsIn = (markup) => (markup.match(/points="[^"]*"/g) || [])
      .map((run) => run.split(" ").length);
    drawHud(frameAt(1), 1);
    return JSON.stringify({
      afterDeaths, afterLead, leadsRecorded, deathsRecorded,
      railNamesTheStrip: /settlers alive/.test(standingsLayer.innerHTML),
      atFirst: pointsIn(strip(0)),
      atThird: pointsIn(strip(2)),
      labelled: /settlers alive/.test(strip(2)),
      // Alpha opens with three settlers and Beta with one, so each head must
      // carry its OWN figure - set after the head while the episode still has
      // axis to run, and flipped in front of it once the head reaches the end.
      // (The ">3<" set to the end is the cap in the gutter, hence the "1" here.)
      headsAfter: /text-anchor="start"[^>]*>3</.test(strip(0))
        && /text-anchor="start"[^>]*>1</.test(strip(0)),
      headsFlipped: /text-anchor="end"[^>]*>1</.test(strip(0, () => 100)),
      // Sixteen populations cannot carry sixteen figures in a strip this short.
      crowded: /text-anchor="start"[^>]*>1</.test(settlerStrip(
        { slots: Array.from({ length: 16 }, (_, index) => ({ name: \`P\${index}\` })) },
        {
          big: false, left: 0, plotW: 100, scaleX: (t) => t, scheduled: 40, footY: 60,
          top: 0, height: 50,
          visible: [{ timestep: 0, population: Array.from({ length: 16 }, () => 1) }],
        },
      )),
    });
  })()
`, viewerContext));
assert.equal(dieOff.afterDeaths, "",
  "three settlers lost in one timestep must put nothing over the board");
assert.equal(dieOff.afterLead, "",
  "and neither may a lead change - no beat plate covers the lattice mid-episode");
// The half that makes the removal safe: the events are still there to be read,
// they are just read off the band, the feed and the end card instead of a plate.
assert.equal(dieOff.leadsRecorded, 1, "the overtake must still be recorded as a lead change");
assert.ok(dieOff.deathsRecorded > 0, "and the cull as deaths");
assert.ok(dieOff.railNamesTheStrip, "the race panel must name its headcount plot");
assert.ok(dieOff.labelled, "and the strip must carry that label itself");
// One line per population, one point per timestep delivered - which is what
// "updates tick by tick" has to mean for a chart that replaced a per-tick banner.
assert.deepEqual(dieOff.atFirst, [1, 1], "one point per population at the first frame");
assert.deepEqual(dieOff.atThird, [3, 3], "and one more on every timestep after it");
assert.ok(dieOff.headsAfter, "every head must carry its population's own live count");
assert.ok(dieOff.headsFlipped,
  "and set it in front of the head once there is no axis left to set it after");
assert.ok(!dieOff.crowded,
  "sixteen figures may not pile up in a strip that cannot separate them");

const decimation = JSON.parse(vm.runInContext(`(() => {
  const values = Array(1000).fill(0);
  values[517] = 100;
  const indices = lttbIndices(values.length, 100, (index) => index, (index) => values[index]);
  return JSON.stringify({
    count: indices.length,
    first: indices[0],
    last: indices.at(-1),
    spike: indices.includes(517),
    passthrough: lttbIndices(4, 10, (index) => index, (index) => index),
  });
})()`, viewerContext));
assert.deepEqual(decimation, {
  count: 100, first: 0, last: 999, spike: true, passthrough: [0, 1, 2, 3],
}, "chart decimation stays within the pixel budget while retaining endpoints and peaks");

// The playback engine itself: nothing used to drive tick(), which is where the
// end-card off-by-one lived.
const playback = JSON.parse(vm.runInContext(`
  resetStream();
  for (let step = 0; step <= 40; step += 1) {
    recordFrame(${sandboxFrame("step", "[settler(1, 0, 0, step)]").replace('"step"', "step").replace('"[settler(1, 0, 0, step)]"', "[{ id: 1, slot: 0, cell: 0, sugar: step, spice: 0, age: 1, decisionModel: 'p0', sugarMetabolism: 1, spiceMetabolism: 0, movement: 1, vision: 1, depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 }]")});
  }
  state.finished = true;
  state.playing = false;
  state.cursor = frameCount() - 1;
  tick();
  const atEndText = beatsLayer.innerHTML;
  state.cursor = 0;
  tick();
  JSON.stringify({
    endCardAtLast: /FINAL/.test(atEndText),
    endCardScore: (atEndText.match(/>(\\d+)</g) || []).join(","),
    noCardAtStart: !/FINAL/.test(beatsLayer.innerHTML),
  });
`, viewerContext));
assert.ok(playback.endCardAtLast, "the end card must appear on the final frame");
assert.ok(playback.noCardAtStart, "and must not appear after scrubbing back to the start");
assert.ok(playback.endCardScore.includes("40"),
  `the end card must show the FINAL frame's score, got ${playback.endCardScore}`);

// A stream that stops short must not crown anyone.
const truncated = JSON.parse(vm.runInContext(`
  resetStream();
  for (let step = 0; step <= 10; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [])}, { timestep: step, maxTimestep: 40 }));
  }
  JSON.stringify({ scheduled: state.maxTimestep, last: lastFrame().timestep });
`, viewerContext));
assert.equal(truncated.scheduled, 40);
assert.ok(truncated.last < truncated.scheduled,
  "a stream stopping at t10 of 40 is incomplete and must never read FINAL");

// Speed is an honest multiplier over the whole recorded beat.
const tempo = JSON.parse(vm.runInContext(`
  (() => {
    resetStream();
    state.playing = false;
    recordFrame(${sandboxFrame(0, [])});
    recordFrame(${sandboxFrame(1, [])});
    state.finished = true;
    state.speed = 4;
    setNow(100);
    setPlaybackCursor(frameCount() - 1, 100);
    setPlaying(true);
    tick(100);
    setPlaying(false);
    const result = {
      animAtOne: animFactor(1),
      animAtFour: animFactor(4),
      dwellAtOne: frameDwellMs(1),
      dwellAtFour: frameDwellMs(4),
      endHoldAtFour: state.holdUntil - 100,
    };
    state.speed = 1;
    setNow(0);
    setPlaybackCursor(0, 0);
    return JSON.stringify(result);
  })()
`, viewerContext));
assert.equal(tempo.animAtOne, 1);
// Every speed step has to actually do something. With the animation cap at 2x
// both levers saturated there and "4x" changed the label and nothing else.
const dwells = JSON.parse(vm.runInContext(
  "JSON.stringify(SPEEDS.map((speed) => frameDwellMs(speed)))", viewerContext));
assert.equal(new Set(dwells).size, dwells.length, `speed steps must differ: ${dwells}`);
assert.ok(dwells.every((value, index) => index === 0 || value < dwells[index - 1]),
  `each speed step must shorten the dwell: ${dwells}`);
assert.equal(tempo.animAtFour, 1 / 3, "motion is capped at 3x real time");
assert.equal(tempo.dwellAtOne, 770, "1x preserves the existing complete beat");
assert.equal(tempo.dwellAtFour, 192.5, "4x is four times the 1x wall-clock rate");
assert.equal(tempo.endHoldAtFour, 1300, "the end hold scales by the selected speed too");

/* The transport announces TIMESTEPS, and its own min/max/value are timesteps.
 *
 * They used to be frame INDICES while aria-valuetext said timestep, so anything
 * falling back to valuenow read a different number from the one spoken - and on
 * a stream that does not begin at zero the two axes are not even parallel. */
const transport = JSON.parse(vm.runInContext(`
  resetStream();
  for (let step = 20; step <= 30; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [])}, {
      timestep: step, maxTimestep: 40,
      agents: [{ id: 1, slot: 0, cell: 0, sugar: step, spice: 0, age: 1,
        decisionModel: 'p0', sugarMetabolism: 1, spiceMetabolism: 0, movement: 1,
        vision: 1, depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 }],
    }));
  }
  state.playing = false;
  state.cursor = 4;
  tick();
  const scrub = document.getElementById("scrub");
  JSON.stringify({
    min: scrub.min,
    max: scrub.max,
    value: scrub.value,
    valuetext: scrub.getAttribute("aria-valuetext"),
    seekMid: (() => { seek(indexOfTimestep(27)); return frameAt(currentIndex()).timestep; })(),
    seekMissing: (() => { seek(indexOfTimestep(99)); return frameAt(currentIndex()).timestep; })(),
    joinedLate: joinedLate(),
  });
`, viewerContext));
assert.equal(transport.min, "20", "the range's floor is the first timestep delivered");
assert.equal(transport.max, "30", "and its ceiling the last");
assert.equal(transport.value, "24", "its value is a timestep, not a frame index");
assert.equal(transport.valuetext, "timestep 24 of 40",
  "and what it announces must be the same number it carries");
assert.equal(transport.seekMid, 27, "seeking by timestep lands on that timestep");
assert.equal(transport.seekMissing, 30, "and an unrecorded one snaps to the nearest frame");
// A spectator handed a stream that starts at t20 of a 40-timestep match has been
// cut off at the HEAD by the server's live backlog cap. Nothing used to say so,
// and every "of 64 survived" total silently became a window.
assert.ok(transport.joinedLate, "a stream that does not start at t0 must be flagged");
const lateNotice = vm.runInContext(`
  drawHud(lastFrame(), frameCount() - 1); standingsLayer.innerHTML;
`, viewerContext);
assert.match(lateNotice, /joined at t20/,
  "and the overlay must say the earlier timesteps were never delivered");
assert.match(
  vm.runInContext("speak(lastFrame()); document.getElementById('commentary').textContent",
    viewerContext),
  /joined at timestep 20/,
  "the spoken broadcast must carry it too",
);

/* The event feed is a LEDGER, not a window.
 *
 * Its rows used to sum to fewer deaths than the count the emergence panel
 * printed two panels below, with nothing on screen to reconcile them. Every beat
 * the feed does not name individually is now inside a summary row's totals. */
const ledger = JSON.parse(vm.runInContext(`
  resetStream();
  const living = (count, step) => Array.from({ length: count }, (_, index) => ({
    id: index, slot: index % 2, cell: index % 4, sugar: step, spice: 0, age: 1,
    decisionModel: 'p' + (index % 2), sugarMetabolism: 1, spiceMetabolism: 0,
    movement: 1, vision: 1, depressed: false, sick: false, race: -1,
    sex: 'male', tribe: -1,
  }));
  // Thirty timesteps, one settler lost on each of the last twenty: far more
  // beats than the feed has rows.
  for (let step = 0; step <= 30; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [])}, {
      timestep: step, maxTimestep: 40,
      agents: living(Math.max(4, 24 - Math.max(0, step - 10)), step),
      stats: { giniCoefficient: 0.3, agentStarvationDeaths: 1 },
    }));
  }
  const total = events.reduce((sum, e) => sum + (e.kind === "death" ? e.count : 0), 0);
  drawHud(lastFrame(), frameCount() - 1);
  JSON.stringify({
    total,
    deaths: events.filter((e) => e.kind === "death").length,
    // Every row width the panel actually renders, at both densities.
    rows: [4, 3].map((slots) => feedRows(events, slots)
      .map((row) => (row.kind === "lead" ? 0 : row.count))),
    leads: [4, 3].map((slots) => feedRows(events, slots)
      .reduce((sum, row) => sum + (row.kind === "lead" ? 1 : row.leads ?? 0), 0)),
    counts: [4, 3].map((slots) => feedRows(events, slots).length),
  });
`, viewerContext));
assert.ok(ledger.deaths > 6,
  `the fixture must produce more beats than the feed has rows, got ${ledger.deaths}`);
for (const [index, rows] of ledger.rows.entries()) {
  assert.equal(
    rows.reduce((sum, value) => sum + value, 0),
    ledger.total,
    `the feed's rows must account for every loss: ${rows} vs ${ledger.total}`,
  );
  assert.ok(ledger.counts[index] > 1,
    "and the panel must be full whenever there is more than one beat to show");
}

/* Terrain and board painting are invalidated by data and geometry, not clocks.
 * A paused/hidden viewer owns no animation frame; explicit interaction paints once. */
const invalidation = JSON.parse(vm.runInContext(`
  (() => {
    resetStream();
    state.playing = false;
    setStageWidth(640);
    measureDensity();
    const original = ${sandboxFrame(0, [])};
    const same = ${sandboxFrame(1, [])};
    const changed = ${sandboxFrame(2, [])};
    changed.cells[0] = [2, 0, 0];
    const firstPaint = showTerrain(original);
    const unchangedPaint = showTerrain(same);
    const changedPaint = showTerrain(changed);
    const small = [board.width, board.height, terrain.width, terrain.height];
    devicePixelRatio = 2;
    measureDensity();
    const densityPaint = showTerrain(changed);
    const retina = [board.width, board.height];
    devicePixelRatio = 1;
    setStageWidth(1600);
    measureDensity();
    const geometryPaint = showTerrain(changed);
    const large = [board.width, board.height, terrain.width, terrain.height];

    recordFrame(original);
    recordFrame(same);
    const paused = paintLoopState();
    setPlaying(true);
    const playing = paintLoopState();
    fireVisibility(true);
    const hidden = paintLoopState();
    fireVisibility(false);
    const visible = paintLoopState();
    setPlaying(false);
    return JSON.stringify({
      firstPaint, unchangedPaint, changedPaint, densityPaint, geometryPaint,
      small, retina, large, paused, playing, hidden, visible,
    });
  })()
`, viewerContext));
assert.deepEqual(
  [invalidation.firstPaint, invalidation.unchangedPaint,
    invalidation.changedPaint, invalidation.densityPaint, invalidation.geometryPaint],
  [true, false, true, true, true],
  "terrain paints only for changed resources or changed geometry",
);
assert.deepEqual(invalidation.small.slice(0, 2), [640, 360],
  "a 640px stage needs only a 640x360 DPR1 board backing store");
assert.deepEqual(invalidation.retina, [1280, 720],
  "a DPR change resizes the backing store even when CSS geometry is stable");
assert.deepEqual(invalidation.large.slice(0, 2), [1600, 900],
  "backing resolution follows visible stage density up to the cap");
assert.equal(invalidation.paused.active, false, "paused playback owns no animation frame");
assert.equal(invalidation.playing.active, true, "playing playback owns one animation frame");
assert.equal(invalidation.hidden.active, false, "a hidden page owns no animation frame");
assert.equal(invalidation.visible.active, true, "visibility return restarts active playback");

// A delayed callback can cross two boundaries at honest 4x. Every crossed
// index must still enter, or death rings and other boundary work disappear.
const crossed = JSON.parse(vm.runInContext(`
  (() => {
    resetStream();
    state.playing = false;
    for (let step = 0; step <= 2; step += 1) {
      recordFrame(Object.assign(${sandboxFrame(0, [])}, { timestep: step }));
    }
    events.length = 0;
    events.push(
      { index: 1, timestep: 1, kind: "death", agents: [{ id: 1, cell: 0, slot: 0 }] },
      { index: 2, timestep: 2, kind: "death", agents: [{ id: 2, cell: 1, slot: 0 }] },
    );
    motes.length = 0;
    state.lastDrawnIndex = 0;
    state.speed = 4;
    setNow(0);
    setPlaybackCursor(0.99, 0);
    setPlaying(true);
    setNow(200);
    tick(200);
    setPlaying(false);
    const result = { index: currentIndex(), motes: motes.map((mote) => [mote.cx, mote.cy]) };
    state.speed = 1;
    setNow(0);
    setPlaybackCursor(0, 0);
    return JSON.stringify(result);
  })()
`, viewerContext));
assert.equal(crossed.index, 2, "the fixture must cross two frame boundaries");
assert.equal(crossed.motes.length, 2, "every crossed frame must run boundary handling");

// The epoch clock rebases without jumping, ignores hidden paint throttling, and
// snaps at 8x/16x while semantic history remains complete.
const epochClock = JSON.parse(vm.runInContext(`(() => {
  resetStream();
  state.playing = false;
  for (let step = 0; step <= 20; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [])}, { timestep: step, maxTimestep: 20 }));
  }
  state.finished = true;
  viewerTimersReset();
  setNow(0);
  setPlaybackSpeed(1, 0);
  setPlaybackCursor(0, 0);
  setPlaying(true);
  setNow(770);
  tick(770);
  const atOne = state.cursor;
  setPlaybackSpeed(4, 770);
  const afterSpeedChange = state.cursor;
  setNow(962.5);
  tick(962.5);
  const atTwo = state.cursor;
  setPlaying(false);
  setNow(1962.5);
  tick(1962.5);
  const whilePaused = state.cursor;
  setPlaying(true);
  setNow(2155);
  tick(2155);
  const afterResume = state.cursor;
  setPlaying(false);

  setNow(0);
  setPlaybackSpeed(4, 0);
  setPlaybackCursor(0, 0);
  let paints = 0;
  const originalDrawBoard = drawBoard;
  drawBoard = (...args) => { paints += 1; return originalDrawBoard(...args); };
  setPlaying(true);
  paints = 0;
  fireVisibility(true);
  setNow(1000);
  const hidden = { cursor: state.cursor, paints, loop: paintLoopState() };
  fireVisibility(false);
  const visible = { cursor: state.cursor, paints, loop: paintLoopState() };
  drawBoard = originalDrawBoard;
  setPlaying(false);

  events.length = 0;
  events.push(
    { index: 1, timestep: 1, kind: "death", agents: [{ id: 1, cell: 0, slot: 0 }] },
    { index: 2, timestep: 2, kind: "lead", slot: 1, name: "Beta", margin: 2 },
    { index: 3, timestep: 3, kind: "death", agents: [{ id: 2, cell: 1, slot: 0 }] },
  );
  motes.length = 0;
  state.lastDrawnIndex = 0;
  setNow(0);
  setPlaybackSpeed(16, 0);
  setPlaybackCursor(0, 0);
  setPlaying(true);
  tick(200);
  const skipped = {
    index: currentIndex(), semanticEvents: events.length, transientMotes: motes.length,
  };
  setPlaying(false);

  viewerTimersReset();
  setNow(0);
  setPlaybackCursor(frameCount() - 1, 0);
  setPlaying(true);
  const held = paintLoopState();
  setPlaying(false);
  setPlaybackSpeed(1, 0);
  return JSON.stringify({
    atOne, afterSpeedChange, atTwo, whilePaused, afterResume,
    hidden, visible, skipped, held,
    interpolation: SPEEDS.map((speed) => interpolatesAt(speed)),
  });
})()`, viewerContext));
assert.equal(epochClock.atOne, 1, "770ms at 1x advances exactly one frame");
assert.equal(epochClock.afterSpeedChange, 1, "changing speed rebases without jumping");
assert.equal(epochClock.atTwo, 2, "the rebased 4x epoch advances from the same cursor");
assert.equal(epochClock.whilePaused, 2, "paused wall time does not advance the epoch");
assert.equal(epochClock.afterResume, 3, "resume rebases from the paused cursor");
assert.equal(epochClock.hidden.cursor, 0, "hidden wall time does not mutate the last painted cursor");
assert.equal(epochClock.hidden.paints, 0, "a hidden page paints nothing");
assert.equal(epochClock.hidden.loop.active, false, "a hidden page schedules no animation frame");
assert.equal(epochClock.hidden.loop.pendingTimers, 0, "a hidden page schedules no timer either");
assert.ok(Math.abs(epochClock.visible.cursor - (1000 / 192.5)) < 1e-9,
  "visibility return computes the wall-clock cursor before painting");
assert.equal(epochClock.visible.paints, 1, "visibility return issues exactly one catch-up paint");
assert.equal(epochClock.visible.loop.active, true, "then schedules the next visible animation frame");
assert.deepEqual(epochClock.skipped, { index: 4, semanticEvents: 3, transientMotes: 0 },
  "16x selects the latest due frame without replaying skipped transient effects");
assert.equal(epochClock.held.active, false, "the final hold owns no animation loop");
assert.ok(epochClock.held.pendingTimers > 0, "the final hold schedules one intentional wake-up");
assert.deepEqual(epochClock.interpolation, [true, true, true, true, false, false],
  "only dwells of at least 150ms interpolate");

const speechThrottle = JSON.parse(vm.runInContext(`(() => {
  resetStream();
  state.playing = false;
  for (let step = 0; step <= 40; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [settler(1, 0, 0, 10)])}, {
      timestep: step, maxTimestep: 40,
    }));
  }
  state.finished = true;
  state.speed = 16;
  spokenKey = "";
  lastSpokenAt = -Infinity;
  state.cursor = 1;
  speak(frameAt(1), 0);
  const first = commentary.textContent;
  state.cursor = 11;
  speak(frameAt(11), 100);
  const throttled = commentary.textContent;
  speak(frameAt(11), 1100);
  const later = commentary.textContent;
  state.cursor = frameCount() - 1;
  speak(lastFrame(), 1101);
  const final = verdictLine.textContent;
  state.speed = 1;
  return JSON.stringify({ first, throttled, later, final });
})()`, viewerContext));
assert.equal(speechThrottle.throttled, speechThrottle.first,
  "16x must not enqueue a new aria-live utterance every skipped beat");
assert.notEqual(speechThrottle.later, speechThrottle.first,
  "high-speed commentary may update at a human-readable cadence");
assert.match(speechThrottle.final, /^Final\./,
  "the final verdict bypasses high-speed announcement throttling");

/* A TILE HOLDS UP TO FOUR OF EACH, AND THEY ARE COUNTABLE.
 *
 * The board draws one dot per unit held, on two interleaved lattices — sugar on
 * the square, spice on the diamond — so four of each reads as four and four
 * rather than as eight of something. This pins the properties that make them
 * countable at all: enough slots for the cap, no slot shared between the two
 * resources, and every dot far enough from its neighbours to stay a separate
 * mark at the radius they are drawn with. */
const dots = JSON.parse(vm.runInContext(`
  const span = 2 * (DOT_RADIUS + DOT_HALO);
  let worstGap = Infinity, outside = 0, missing = 0;
  const layouts = [];
  for (let index = 0; index < 400; index += 1) {
    const points = cellDotLayout(index, 4, 4);
    layouts.push(points);
    if (points.length !== 8 || points.some((p) => !p)) missing += 1;
    for (let i = 0; i < points.length; i += 1) {
      const [px, py] = points[i];
      const edge = DOT_RADIUS + DOT_HALO;
      if (px - edge < 0 || px + edge > 1 || py - edge < 0 || py + edge > 1) outside += 1;
      for (let j = i + 1; j < points.length; j += 1) {
        worstGap = Math.min(worstGap, Math.hypot(px - points[j][0], py - points[j][1]));
      }
    }
  }
  const shapes = new Set(layouts.map((points) =>
    points.map(([px, py]) => px.toFixed(3) + "," + py.toFixed(3)).join("|")));
  const again = cellDotLayout(7, 4, 4);
  JSON.stringify({
    perCell: layouts[0].length, missing, outside, worstGap, span,
    distinctLayouts: shapes.size, cells: layouts.length,
    stable: JSON.stringify(again) === JSON.stringify(layouts[7]),
  });
`, viewerContext));
/* The strapline states the win condition, and it shares its band with the clock.
 *
 * It has overflowed into that panel twice now — once as "populations forage one
 * lattice", and again when v3's rules had to be described in the same space. So
 * both wordings are measured here rather than eyeballed, at the width where the
 * two actually meet. */
const strapline = JSON.parse(vm.runInContext(`
  setStageWidth(1600); state.largeText = false; measureDensity();
  const scored = { slots: [{ name: "A" }], coworld: { seats: [{ variable: "wealth" }] } };
  const race = { slots: [{ name: "A" }, { name: "B" }] };
  JSON.stringify({
    v3: mastheadStrapline(scored, false),
    v1: mastheadStrapline(race, false),
    onePopulation: mastheadStrapline({ slots: [{ name: "A" }] }, false),
    twoSeats: mastheadStrapline(
      { slots: [{ name: "A" }], coworld: { seats: [{ variable: "wealth" }, { variable: "wealth" }] } },
      false),
  });
`, viewerContext));
// 506 is where the clock panel starts; 18 units is the strapline's type size.
// 0.5 em per character is a deliberate OVER-estimate for this face, so a wording
// that passes here has margin rather than sitting exactly on the boundary.
const strapFits = (line) => 32 + line.length * (18 * 0.5) < 506;
assert.ok(strapFits(strapline.v3), `v3 strapline must clear the clock panel: "${strapline.v3}"`);
assert.ok(strapFits(strapline.v1), `and so must the race one: "${strapline.v1}"`);
assert.match(strapline.v3, /match the target/,
  "a v3 world is won by matching a target, and must not claim otherwise");
assert.doesNotMatch(strapline.v3, /most .* wins/,
  "v3 is not won by holding the most of anything");
assert.match(strapline.v1, /most .* wins/, "a v1 replay is still a race and still says so");
// The plural has to agree, in both directions.
assert.match(strapline.onePopulation, /^1 population,/, "one population, not '1 populations'");
assert.match(strapline.v3, /^1 seat ·/, "one seat, not '1 seats'");
assert.match(strapline.twoSeats, /^2 seats ·/, "and two seats takes the plural");

/* A SETTLER MUST NOT BE THE COLOUR OF THE GROUND IT STANDS ON.
 *
 * TRIBE_INK[0] shipped byte-identical to SPICE_HEX — settlers of the first tribe
 * were exactly the colour of the spice dots around them, a 1.00:1 collision, and
 * nothing in this file noticed. TRIBE_INK[3] measured 6.98:1 against the plate,
 * under the bar it was chosen to clear. Both are measured here now, because a
 * settler standing on stripped ground has only its body value to carry it: the
 * ink ring is 1.09:1 against the plate and cannot do the work. */
const inks = JSON.parse(vm.runInContext(`
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = (hex) => {
    const h = hex.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)];
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  JSON.stringify(TRIBE_INK.map((ink) => ({
    ink,
    plate: ratio(ink, PLATE_HEX),
    spice: ratio(ink, SPICE_HEX),
    sugar: ratio(ink, SUGAR_HEX),
  })));
`, viewerContext));
for (const row of inks) {
  assert.ok(row.plate >= 7,
    `tribe ink ${row.ink} must clear 7:1 on the plate it stands on, got ${row.plate.toFixed(2)}`);
  assert.ok(row.spice > 1.05,
    `tribe ink ${row.ink} must not be the colour of a spice dot, got ${row.spice.toFixed(2)}`);
  assert.ok(row.sugar > 1.05,
    `nor of a sugar dot, got ${row.sugar.toFixed(2)} for ${row.ink}`);
}
assert.equal(new Set(inks.map((row) => row.ink)).size, inks.length,
  "and no two tribes may share an ink");

assert.equal(dots.perCell, 8, "four sugar plus four spice positions per cell");
assert.equal(dots.missing, 0, "every position must be placed");
assert.equal(dots.outside, 0, "and every dot stays wholly inside its own cell");
assert.ok(dots.worstGap > dots.span,
  `no two dots may touch anywhere on the board: worst gap ${dots.worstGap} vs span ${dots.span}`);
// The whole point of the exercise: the plate must not repeat one motif. A fixed
// lattice with a small nudge passed every separation check above and STILL read
// as a pattern, so the property that actually matters is pinned directly.
assert.equal(dots.distinctLayouts, dots.cells,
  `every cell must draw its own arrangement, got ${dots.distinctLayouts} for ${dots.cells} cells`);
assert.ok(dots.stable, "and a cell's arrangement must not change between repaints");

/* Density is a RAMP SWITCH, not a scale factor, and the viewer's own larger-text
 * control forces it at any size. */
const density = JSON.parse(vm.runInContext(`
  setStageWidth(1600); state.largeText = false; measureDensity();
  const base = [17, 25, 40].map((size) => T(size));
  setStageWidth(640); measureDensity();
  const floor = [17, 25, 40].map((size) => T(size));
  setStageWidth(1600); measureDensity();
  setLargeText(true);
  const forced = [17, 25, 40].map((size) => T(size));
  const pressed = document.getElementById("text-size").getAttribute("aria-pressed");
  setLargeText(false);
  JSON.stringify({ base, floor, forced, pressed, off: [17, 25, 40].map((s) => T(s)) });
`, viewerContext));
assert.deepEqual(density.base, [17, 25, 40], "at full size the ramp is the design's own sizes");
/* The compact ramp is a PHYSICAL FLOOR, so the assertion is in CSS pixels.
 *
 * It used to be "at least 34 stage units", which was the same statement only at
 * the one width the constants were tuned for. Held as fixed units, that floor
 * printed the caption at 11.3px at the 640 embed and at 20.8px on an 800px stage
 * — type built for a phone, rendered half again as large on a laptop, which is
 * exactly what the owner saw. */
const floorPx = density.floor.map((size) => size * (640 / 1920));
assert.ok(floorPx.every((pixels) => pixels >= 11),
  `no type may print below 11 CSS px at the embed floor, got ${floorPx.map((p) => p.toFixed(1))}`);
assert.ok(density.floor[0] < density.floor[1] && density.floor[1] < density.floor[2],
  `the floor ramp must keep its hierarchy, got ${density.floor}`);
/* And the larger-text control is a MULTIPLIER, not that floor.
 *
 * It used to be asserted equal to the embed floor's ramp, which only held while
 * the floor was fixed units. A floor is the wrong shape for this control: on a
 * 1600px stage the design's own sizes already clear it, so expressing "larger
 * text" as a floor would have made the button do nothing on any desktop — a
 * silent failure of the one affordance in the product for someone who needs
 * bigger type. */
assert.deepEqual(density.forced, density.base.map((size) => size * 1.5),
  `larger text must magnify the design's sizes at any width, got ${density.forced}`);
assert.equal(density.pressed, "true", "and report its state to assistive technology");
assert.deepEqual(density.off, density.base, "turning it off must restore the design's sizes");
// A sandboxed iframe can refuse storage outright; the toggle must still work.
assert.doesNotThrow(
  () => vm.runInContext("denyStorage(true); setLargeText(true); setLargeText(false); denyStorage(false);",
    viewerContext),
  "denied session storage must not take the toggle - or the overlay - down",
);

// Reduced motion is read LIVE. Sampling it once at load left the replay
// animating for the rest of the session for someone who had just asked it to
// stop. It is ONE-DIRECTIONAL: turning the preference off must not force-start
// playback over a viewer's explicit pause, which is what an OS that flips the
// setting on a schedule would otherwise do.
const motionResponse = JSON.parse(vm.runInContext(`
  state.playing = true;
  fireMotionChange(true);
  const stopped = state.playing;
  fireMotionChange(false);
  const afterOff = state.playing;
  state.playing = true;
  fireMotionChange(true);
  const stopsAgain = state.playing;
  fireMotionChange(false);
  JSON.stringify({ stopped, afterOff, stopsAgain });
`, viewerContext));
assert.equal(motionResponse.stopped, false,
  "turning reduced motion ON must stop the replay advancing");
assert.equal(motionResponse.afterOff, false,
  "and turning it off must NOT resume over the viewer's own pause");
assert.equal(motionResponse.stopsAgain, false,
  "the listener must keep working after the first flip");

/* What a failure does to the transport depends on whether anything is playable.
 *
 * With NOTHING to play it takes the transport away, and must take the focus with
 * it - a keyboard user left standing on a hidden button never reaches the
 * message that replaced it. With frames in hand it must KEEP the transport: the
 * board is still animating and looping, and hiding the only pause control while
 * the picture keeps moving fails SC 2.2.2 outright. */
const emptyFailure = JSON.parse(vm.runInContext(`
  resetStream();
  document.getElementById("controls").hidden = false;
  document.getElementById("notice").focused = 0;
  fail("The episode stream closed before sending any frames.");
  JSON.stringify({
    hidden: document.getElementById("controls").hidden === true,
    focused: document.getElementById("notice").focused,
    text: document.getElementById("notice").innerHTML,
  });
`, viewerContext));
assert.ok(emptyFailure.hidden, "with nothing to play, a failure hides the transport");
assert.equal(emptyFailure.focused, 1, "and moves the focus to the message");
assert.match(emptyFailure.text, /Reload to try again/);

const midStreamFailure = JSON.parse(vm.runInContext(`
  resetStream();
  recordFrame(${sandboxFrame(0, [settler(1, 0, 0, 10), settler(2, 1, 1, 4)])});
  recordFrame(${sandboxFrame(1, [settler(1, 0, 0, 12), settler(2, 1, 1, 6)])});
  document.getElementById("controls").hidden = false;
  fail("This episode is sending frames this viewer cannot read.");
  JSON.stringify({
    hidden: document.getElementById("controls").hidden === true,
    frames: frameCount(),
    text: document.getElementById("notice").innerHTML,
  });
`, viewerContext));
assert.equal(midStreamFailure.frames, 2);
assert.equal(midStreamFailure.hidden, false,
  "a failure mid-stream must LEAVE the transport: the board is still moving");
assert.match(midStreamFailure.text, /cannot read/);


/* The `?replay=` path must GUARD every frame, exactly as the socket path does.
 *
 * It validated the envelope and then fed the frames straight to recordFrame, so
 * one malformed frame gave a ground-coloured stage, no message, no controls, and
 * a TypeError every 16 ms for the life of the tab - on a documented path with no
 * coverage at all. */
const artifact = vm.runInContext(`
  (async () => {
    resetStream();
    rejectedFormat = false;
    rejectedShape = false;
    document.getElementById("notice").innerHTML = "";
    const good = ${sandboxFrame(0, [settler(1, 0, 0, 10), settler(2, 1, 1, 4)])};
    const bad = ${sandboxFrame(1, [settler(1, 0, 0, 11)])};
    delete bad.agents;
    payloadForTest = {
      format: "sugarscape.replay.v1",
      config: { timesteps: 40 },
      frames: [good, bad],
    };
    await loadArtifact("about:test");
    let threw = null;
    try { tick(); tick(); } catch (error) { threw = String(error); }
    return JSON.stringify({
      frames: frameCount(),
      notice: document.getElementById("notice").innerHTML,
      truncated: state.truncated,
      finished: state.finished,
      threw,
    });
  })()
`, viewerContext);
const artifactResult = JSON.parse(await artifact);
assert.equal(artifactResult.frames, 1, "only the readable frames may be recorded");
assert.match(artifactResult.notice, /cannot read/,
  "and the viewer must SAY the recording went bad, never sit on a blank stage");
assert.equal(artifactResult.truncated, true, "a recording that goes bad is not a result");
assert.equal(artifactResult.finished, false, "so nobody is crowned from it");
assert.equal(artifactResult.threw, null, "and the tick loop must not throw");

/* A rejected frame must clear the silence timer too. It only cleared on the
 * accepted path, so twelve seconds after naming the exact format it could not
 * read, the viewer replaced that with "not sending any frames" - while frames
 * were arriving and being discarded. */
const silence = JSON.parse(vm.runInContext(`
  resetStream();
  rejectedFormat = false;
  rejectedShape = false;
  viewerTimersReset();
  connect();
  const bad = ${sandboxFrame(0, [])};
  bad.format = "sugarscape.frame.v2";
  lastSocket.fire("message", { data: JSON.stringify(bad) });
  const afterReject = document.getElementById("notice").innerHTML;
  runPendingTimers();
  JSON.stringify({ afterReject, afterTimeout: document.getElementById("notice").innerHTML });
`, viewerContext));
assert.match(silence.afterReject, /sugarscape\.frame\.v2/,
  "the viewer must name the format it cannot read");
assert.equal(silence.afterTimeout, silence.afterReject,
  "and the silence timer must not overwrite that with a false diagnosis");

/* The feed's "guarantee the most recent lead change a row" branch has to
 * actually produce a row. It appended the rescued lead and then re-sliced to
 * make room for the summary, removing exactly the row it had just rescued - at
 * both densities, every time. The ledger still balanced, so the totals test
 * stayed green while the panel's declared priority was dead code. */
const priority = JSON.parse(vm.runInContext(`
  resetStream();
  const cohort = (count, step, lead) => Array.from({ length: count }, (_, index) => ({
    id: index, slot: index % 2, cell: index % 4,
    sugar: index % 2 === 0 ? (lead ? step : step * 3) : (lead ? step * 4 : step),
    spice: 0, age: 1,
    decisionModel: 'p' + (index % 2), sugarMetabolism: 1, spiceMetabolism: 0,
    movement: 1, vision: 1, depressed: false, sick: false, race: -1,
    sex: 'male', tribe: -1,
  }));
  for (let step = 0; step <= 30; step += 1) {
    recordFrame(Object.assign(${sandboxFrame(0, [])}, {
      timestep: step, maxTimestep: 40,
      agents: cohort(Math.max(4, 24 - Math.max(0, step - 10)), step, step >= 5),
      stats: { giniCoefficient: 0.3, agentStarvationDeaths: 1 },
    }));
  }
  JSON.stringify({
    leads: events.filter((e) => e.kind === "lead").length,
    kinds: [4, 3].map((slots) => feedRows(events, slots).map((row) => row.kind)),
    totals: [4, 3].map((slots) => feedRows(events, slots)
      .reduce((sum, row) => sum + (row.kind === "lead" ? 0 : row.count), 0)),
    all: events.reduce((sum, e) => sum + (e.kind === "death" ? e.count : 0), 0),
  });
`, viewerContext));
assert.ok(priority.leads >= 1, "the fixture must contain a lead change");
for (const [index, kinds] of priority.kinds.entries()) {
  assert.ok(kinds.includes("lead"),
    `the most recent lead change must get its own row, got ${kinds}`);
  assert.equal(priority.totals[index], priority.all,
    "and the ledger must still account for every loss");
}

/* A lead change that passes THROUGH a tie must still be a lead change.
 * Comparing adjacent frames and suppressing whenever either was tied dropped it
 * entirely: A ahead, level, B ahead emitted nothing. */
const throughTie = JSON.parse(vm.runInContext(`
  resetStream();
  const pair = (a, b) => [
    { id: 1, slot: 0, cell: 0, sugar: a, spice: 0, age: 1, decisionModel: 'p0',
      sugarMetabolism: 1, spiceMetabolism: 0, movement: 1, vision: 1,
      depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 },
    { id: 2, slot: 1, cell: 1, sugar: b, spice: 0, age: 1, decisionModel: 'p1',
      sugarMetabolism: 1, spiceMetabolism: 0, movement: 1, vision: 1,
      depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 },
  ];
  const at = (step, a, b) => recordFrame(Object.assign(${sandboxFrame(0, [])}, {
    timestep: step, maxTimestep: 40, agents: pair(a, b),
  }));
  at(0, 10, 5);   // Alpha ahead
  at(1, 7, 7);    // level
  at(2, 5, 12);   // Beta ahead - a real change, through the tie
  JSON.stringify(events.filter((e) => e.kind === "lead").map((e) => [e.timestep, e.name]));
`, viewerContext));
assert.deepEqual(throughTie, [[2, "Beta"]],
  "a lead that changes hands across a tied frame is still one lead change");

/* The lead plot DIVERGES, and its band is stacked by resource.
 *
 * Both halves were drawn upward once, with hue the only thing saying who held
 * the lead. Owner call: blue on one side, red on the other. Position is now a
 * second, redundant channel for the one question the panel exists to answer, and
 * the poles are named so "up" decodes as a population rather than as a verdict.
 * The band is stacked sugar-then-spice because a lead can be made of either —
 * on the shipped recording the two resources favour different populations on
 * 9.5% of timesteps. */
const diverging = JSON.parse(vm.runInContext(`
  (() => {
    resetStream();
    const pair = (aSugar, aSpice, bSugar, bSpice) => [
      { id: 1, slot: 0, cell: 0, sugar: aSugar, spice: aSpice, age: 1, decisionModel: 'p0',
        sugarMetabolism: 1, spiceMetabolism: 1, movement: 1, vision: 1,
        depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 },
      { id: 2, slot: 1, cell: 1, sugar: bSugar, spice: bSpice, age: 1, decisionModel: 'p1',
        sugarMetabolism: 1, spiceMetabolism: 1, movement: 1, vision: 1,
        depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 },
    ];
    const at = (step, as, ap, bs, bp) => recordFrame(Object.assign(${sandboxFrame(0, [])}, {
      timestep: step, maxTimestep: 40, environmentMaxSpice: 4, agents: pair(as, ap, bs, bp),
    }));
    at(0, 10, 10, 40, 10);   // B ahead by 30
    at(1, 60, 10, 40, 10);   // A ahead by 20, through the line
    // The LAST lead is the running peak, so the head sits hard against the top
    // of the plot - the normal case for a lead that grows, and the one that put
    // the caption outside the panel.
    at(2, 140, 30, 40, 10);  // A ahead by 120, the maximum
    state.maxSpice = 4;
    // The chart ALONE, not the whole hud: the scorebug names both populations
    // too, so asserting the poles are named against the full overlay would pass
    // whether or not the plot carries a single label of its own.
    const markup = raceChart(frameAt(2), 0, 0, 600, 300);
    const polys = [...markup.matchAll(/<polygon[^>]*>/g)].map((m) => m[0]);
    const clipped = (clip, opacity) => polys.filter((p) =>
      p.includes(clip) && p.includes('opacity="' + opacity + '"'));
    return JSON.stringify({
      // One band per resource per SIDE. The INNER band, against the line, is the
      // denser .46 and is spice; sugar is stacked outside it at .24.
      baseAbove: clipped('lead-above', '.46').length,
      baseBelow: clipped('lead-below', '.46').length,
      stackedAbove: clipped('lead-above', '.24').length,
      stackedBelow: clipped('lead-below', '.24').length,
      // Each half is drawn in its own seat's colour, never both in one.
      aboveIsSeat0: clipped('lead-above', '.46').every((p) => p.includes('#f5504a')),
      belowIsSeat1: clipped('lead-below', '.46').every((p) => p.includes('#5a7cff')),
      polesNamed: /&gt;Alpha&lt;|>Alpha</.test(markup) && /&gt;Beta&lt;|>Beta</.test(markup),
      keyed: /lead:/.test(markup) && /&gt;sugar&lt;|>sugar</.test(markup),
      captionY: Number((markup.match(/<text x="[^"]*" y="([\\d.]+)"[^>]*>[^<]*ahead</) || [])[1] ?? -1),
      // The top of the plot, read off the band itself: the head is AT the peak
      // on this frame, so the band's highest point IS the plot's top edge. Any
      // caption above that has left the plot and is over the panel's heading.
      plotTop: Math.min(...polys.flatMap((p) => (p.match(/points="([^"]*)"/) || ["", ""])[1]
        .split(" ").filter(Boolean).map((pair) => Number(pair.split(",")[1])))),
      /* WHICH resource is at the base, read off the geometry rather than trusted.
       * This frame gives A a sugar lead of 100 and a spice lead of 20, so the
       * inner band reaching a sixth of the way to the peak is spice and five
       * sixths would be sugar. Renaming the assertions when the two were swapped
       * would otherwise have proved nothing. */
      baseShare: (() => {
        const ys = (clipped('lead-above', '.46')[0].match(/points="([^"]*)"/) || ["", ""])[1]
          .split(" ").filter(Boolean).map((pair) => Number(pair.split(",")[1]));
        const midline = Math.max(...ys);
        const top = Math.min(...polys.flatMap((p) => (p.match(/points="([^"]*)"/) || ["", ""])[1]
          .split(" ").filter(Boolean).map((pair) => Number(pair.split(",")[1]))));
        return (midline - Math.min(...ys)) / (midline - top);
      })(),
    });
  })()
`, viewerContext));
assert.equal(diverging.baseAbove, 1, "the spice band is drawn into the upper half");
assert.equal(diverging.baseBelow, 1, "and into the lower half, clipped at the line");
assert.equal(diverging.stackedAbove, 1, "with the sugar band stacked on it above");
assert.equal(diverging.stackedBelow, 1, "and below");
assert.ok(diverging.aboveIsSeat0,
  "the half above the line may only ever be the first seat's colour");
assert.ok(diverging.belowIsSeat1,
  "and the half below it the second's - never both leads on one side");
assert.ok(diverging.polesNamed,
  "both poles must be named, so 'up' reads as a population and not as winning");
assert.ok(diverging.keyed, "and the two stacked shades must be keyed to their resources");
// The head caption stays BELOW the panel's heading. `peak` is the running
// maximum, so a growing lead puts the head at the very top of the plot on most
// frames; offset upward from there, the caption printed straight through that
// heading at the embed floor — "LEAD, IN SUGAR + SPICA ahead".
assert.ok(Math.abs(diverging.baseShare - 20 / 120) < 0.02,
  `the band against the line must trace the SPICE lead, a sixth of this frame's `
  + `total, not the sugar lead which is five sixths (was ${diverging.baseShare.toFixed(3)})`);
assert.ok(diverging.captionY > diverging.plotTop,
  `the leader caption must stay inside the plot `
  + `(caption ${diverging.captionY} vs plot top ${diverging.plotTop})`);

/* The strip's caption takes the far side from the heads.
 *
 * Pinned to the bottom-left it was correct only at the END of an episode. At the
 * start the head is barely off the axis, its figure prints a few units to the
 * right of it, and a steep early die-off drives both straight through the label
 * — which restoring spice made the common case, two metabolisms burning a
 * settler down while the episode is still near t0. */
const caption = JSON.parse(vm.runInContext(`
  (() => {
    const at = (id, slot, cell, sugar) => (${settler.toString()})(id, slot, cell, sugar);
    resetStream();
    const open = ${sandboxFrame(0, [])};
    open.agents = [at(1, 0, 0, 10), at(2, 1, 1, 10)];
    recordFrame(open);
    const strip = (scaleX) => settlerStrip(firstFrame(), {
      big: false, left: 0, plotW: 100, scaleX, scheduled: 40, footY: 60,
      top: 0, height: 50, visible: wealthSeries,
    });
    const sideOf = (markup) => {
      const found = markup.match(/<text[^>]*text-anchor="([^"]*)"[^>]*>settlers alive</);
      return found ? found[1] : null;
    };
    return JSON.stringify({ early: sideOf(strip(() => 0)), late: sideOf(strip(() => 100)) });
  })()
`, viewerContext));
assert.equal(caption.early, "end",
  "while the heads are in the left half the caption must sit at the right");
assert.equal(caption.late, "start",
  "and move to the left once the heads have crossed to the right");

/* The feed's summary row is budgeted against the panel it sits in.
 *
 * It is the longest line the feed prints — a count, a cause, a per-population
 * breakdown and a folded lead-change tally — and it drew with no measurement, so
 * at the 640 embed floor it ran off the right edge, losing the very tally the
 * clause exists to disclose. It sheds instead: the tally first (the race panel's
 * header carries the same count), then the breakdown, never the count or cause. */
const budgeted = JSON.parse(vm.runInContext(`
  (() => {
    const at = (id, slot, cell, sugar) => (${settler.toString()})(id, slot, cell, sugar);
    resetStream();
    const open = ${sandboxFrame(0, [])};
    open.agents = [at(1, 0, 0, 10), at(2, 1, 1, 10)];
    recordFrame(open);
    events.length = 0;
    events.push({
      index: 1, timestep: 0, kind: "summary", since: 0, until: 0,
      count: 164, cause: "starved", leads: 2,
      bySlot: [[0, 71], [1, 93]], agents: [],
    });
    const line = (width) => {
      const found = eventFeed(firstFrame(), 0, 0, width, 300)
        .match(/>([^<]*starved[^<]*)</);
      return found ? found[1] : null;
    };
    return JSON.stringify({ narrow: line(420), wide: line(1400) });
  })()
`, viewerContext));
assert.ok(budgeted.narrow && !/lead change/.test(budgeted.narrow),
  "a summary that cannot fit its panel must shed the folded lead-change tally");
assert.match(budgeted.narrow, /164 starved/,
  "but never the count and the cause it is reporting");
assert.match(budgeted.wide, /lead change/,
  "and a panel with room for the tally must still print it");

console.log("Viewer model passed");
