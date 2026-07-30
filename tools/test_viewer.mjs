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
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import vm from "node:vm";

const root = resolve(import.meta.dirname, "..");
const viewerHtml = await readFile(join(root, "src/sugarscape/viewer.html"), "utf8");

// The hosted embed is a sandboxed iframe behind a proxy that cannot reach a CDN,
// and any separate sub-resource 404s under the rewritten base href.
assert.match(viewerHtml, /<base href="\/">/);
assert.doesNotMatch(viewerHtml, /https?:\/\/(fonts|cdn|unpkg|jsdelivr)/);
assert.doesNotMatch(viewerHtml, /<(script|link)[^>]+\b(src|href)="(?!data:)/);
// Drive the real viewer script in a sandbox with a DOM stub, so the derived
// broadcast model is covered without a browser.
const viewerTimers = { interval: null, pending: [] };
const gradient = { addColorStop() {} };
const pattern = { setTransform() {} };
const canvasContext = new Proxy({
  createRadialGradient: () => gradient,
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
const viewerContext = vm.createContext({
  console,
  document: {
    createElement: () => fakeElement(),
    getElementById: (id) => elementFor(id),
    querySelector: (selector) => elementFor(selector.replace(/^#/, "")),
    activeElement: null,
    body: null,
  },
  // The sandbox exercises the pure model; setInterval is stubbed out below so
  // playback never starts.
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
  performance: { now: () => 0 },
  URLSearchParams,
  sessionStorage: sessionStorageStub,
  matchMedia: (query) => ({
    media: query,
    get matches() { return motion.matches; },
    addEventListener: (name, fn) => motion.listeners.push(fn),
  }),
  // loadArtifact's own path, which had no coverage at all: the suite hands it a
  // payload rather than a network.
  fetch: () => (viewerContext.payloadForTest
    ? Promise.resolve({ ok: true, json: async () => viewerContext.payloadForTest })
    : Promise.reject(new Error("no network in the sandbox"))),
  // Real timers, driven by hand below. Stubbing these to no-ops made every
  // timer-based path - the silence timeout, the idle settle, the end-card hold -
  // structurally invisible to this suite.
  setInterval: (fn) => { viewerTimers.interval = fn; return 1; },
  setTimeout: (fn, delay) => { viewerTimers.pending.push({ fn, delay }); return viewerTimers.pending.length; },
  clearTimeout: (id) => { if (id) viewerTimers.pending[id - 1] = null; },
});
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

const model = JSON.parse(vm.runInContext(`
  recordFrame(${sandboxFrame(0, [settler(1, 0, 0, 10), settler(2, 1, 1, 4)])});
  recordFrame(${sandboxFrame(1, [settler(1, 0, 0, 11), settler(2, 1, 1, 5)])});
  // Beta overtakes and Alpha's settler starves in the same timestep.
  recordFrame(${sandboxFrame(2, [settler(2, 1, 1, 30)])});
  // A repeat of a timestep already seen must update in place, not append.
  recordFrame(${sandboxFrame(2, [settler(2, 1, 1, 31)])});
  JSON.stringify({
    frames: frames.length,
    timesteps: frames.map((frame) => frame.timestep),
    scheduledEnd: state.maxTimestep,
    standing: ranked(frames.at(-1)).map((row) => [row.name, row.score]),
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
    frames: frames.length,
    series: wealthSeries.at(-1).scores,
    standing: ranked(frames.at(-1)).map((row) => row.score),
  });
`, viewerContext));
assert.equal(afterReplace.frames, 3, "a repeated timestep replaces, never appends");
assert.deepEqual(afterReplace.series, [0, 900], "the chart follows the replacement");
assert.deepEqual(afterReplace.standing, [900, 0], "and so does the standing");

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
  JSON.stringify({ frames: frames.length, events: events.length });
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

// The playback engine itself: nothing used to drive tick(), which is where the
// end-card off-by-one lived.
const playback = JSON.parse(vm.runInContext(`
  resetStream();
  for (let step = 0; step <= 40; step += 1) {
    recordFrame(${sandboxFrame("step", "[settler(1, 0, 0, step)]").replace('"step"', "step").replace('"[settler(1, 0, 0, step)]"', "[{ id: 1, slot: 0, cell: 0, sugar: step, spice: 0, age: 1, decisionModel: 'p0', sugarMetabolism: 1, spiceMetabolism: 0, movement: 1, vision: 1, depressed: false, sick: false, race: -1, sex: 'male', tribe: -1 }]")});
  }
  state.finished = true;
  state.playing = false;
  state.cursor = frames.length - 1;
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
  JSON.stringify({ scheduled: state.maxTimestep, last: frames.at(-1).timestep });
`, viewerContext));
assert.equal(truncated.scheduled, 40);
assert.ok(truncated.last < truncated.scheduled,
  "a stream stopping at t10 of 40 is incomplete and must never read FINAL");

// Speed must collapse dead time between timesteps, never the walk itself.
const tempo = JSON.parse(vm.runInContext(`
  JSON.stringify({
    animAtOne: animFactor(1),
    animAtFour: animFactor(4),
    dwellAtOne: frameDwellMs(1),
    dwellAtFour: frameDwellMs(4),
  });
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
assert.ok(tempo.dwellAtFour < tempo.dwellAtOne, "speed shortens the dwell");
assert.ok(
  tempo.dwellAtFour >= tempo.animAtFour * 620,
  "the dwell is floored to the length of the walk it has to show",
);

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
    seekMid: (() => { seek(indexOfTimestep(27)); return frames[currentIndex()].timestep; })(),
    seekMissing: (() => { seek(indexOfTimestep(99)); return frames[currentIndex()].timestep; })(),
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
  drawHud(frames.at(-1), frames.length - 1); standingsLayer.innerHTML;
`, viewerContext);
assert.match(lateNotice, /joined at t20/,
  "and the overlay must say the earlier timesteps were never delivered");
assert.match(
  vm.runInContext("speak(frames.at(-1)); document.getElementById('commentary').textContent",
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
  drawHud(frames.at(-1), frames.length - 1);
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
// 34 stage units is 11.3 CSS px once the 1920-unit stage is letterboxed into a
// 640px embed. Below that the rail was printing six-pixel type.
assert.ok(density.floor.every((size) => size >= 34),
  `no type may fall below 34 units at the embed floor, got ${density.floor}`);
assert.ok(density.floor[0] < density.floor[1] && density.floor[1] < density.floor[2],
  `the floor ramp must keep its hierarchy, got ${density.floor}`);
assert.deepEqual(density.forced, density.floor,
  "the larger-text control must reach the same ramp at full size");
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
    frames: frames.length,
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
      frames: frames.length,
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

console.log("Viewer model passed");
