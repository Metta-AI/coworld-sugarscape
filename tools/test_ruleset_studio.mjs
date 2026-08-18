#!/usr/bin/env node

import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {existsSync, readFileSync} from "node:fs";
import {resolve, join} from "node:path";
import {spawnSync} from "node:child_process";
import vm from "node:vm";

const root = resolve(import.meta.dirname, "..");
const vendor = join(root, "ruleset-studio/src/vendor/blockly/blockly.min.js");
const sandbox = {console, setTimeout, clearTimeout, TextEncoder};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
sandbox.self = sandbox;
vm.createContext(sandbox);
vm.runInContext(readFileSync(vendor, "utf8"), sandbox);
globalThis.Blockly = sandbox.Blockly;

const {
  TRAIT_NAMES,
  budgetRuleset,
  canonicalJSONString,
  compileWorkspace,
  decompileRuleset,
} = await import("../ruleset-studio/src/blocks.js");
const {
  PlaySettings,
  RunController,
  STUDIO_SETTINGS_KEY,
  readRunOrigin,
  runViewerUrl,
} = await import("../ruleset-studio/src/play.js");

assert.equal(Blockly.VERSION, "13.2.0");

const worked = JSON.parse(await readFile(join(root, "rulesets/worked-example.json"), "utf8"));
const traitsOnly = JSON.parse(await readFile(join(root, "tests/fixtures/rulesets/traits-only.json"), "utf8"));
const nullRuleset = JSON.parse(await readFile(join(root, "tests/fixtures/rulesets/null.json"), "utf8"));

const allOperators = {
  version: 1,
  traits: {aggression: 0.2, trade: 0.8, lending: 0.4, fertility: 1.2},
  movement: [
    {
      if: ["and",
        ["<", ["get", "agent.ttl"], 5],
        ["<=", ["get", "agent.age"], 90],
        [">", ["get", "world.population"], 0],
        [">=", ["get", "world.timestep"], 1],
        ["==", ["get", "cell.occupied"], 0],
        ["!=", ["get", "agent.mrs"], -1],
        ["not", ["get", "world.gini"]],
      ],
      score: ["+",
        ["-", ["get", "cell.welfare"], ["get", "cell.pollution"], ["get", "cell.distance"]],
        ["*", 0.5, ["get", "cell.sugar"], ["get", "cell.spice"]],
        ["/", ["get", "agent.wealth"], 2, 3],
        ["min", ["get", "agent.sugar"], ["get", "agent.spice"], ["get", "world.meanWealth"]],
        ["max", ["get", "agent.vision"], ["get", "agent.movement"], 1],
        ["abs", ["neg", ["get", "cell.preyWealth"]]],
        ["pow", ["get", "cell.sugar"], 2],
        ["if", ["or", ["get", "agent.sugarMetabolism"], ["get", "agent.spiceMetabolism"], ["get", "cell.occupied"]], ["get", "cell.welfare"], 0],
      ],
    },
    {score: ["+", ["get", "cell.welfare"], ["get", "cell.sugar"], ["get", "cell.spice"]]},
  ],
};

function roundTrip(value) {
  const workspace = new Blockly.Workspace();
  const traits = Object.fromEntries(TRAIT_NAMES.map(name => [name, {enabled: false, value: 0}]));
  decompileRuleset(workspace, value, (name, enabled, traitValue) => {
    traits[name] = {enabled, value: traitValue};
  });
  const first = compileWorkspace(workspace, traits);
  const secondWorkspace = new Blockly.Workspace();
  const secondTraits = Object.fromEntries(TRAIT_NAMES.map(name => [name, {enabled: false, value: 0}]));
  decompileRuleset(secondWorkspace, first.value, (name, enabled, traitValue) => {
    secondTraits[name] = {enabled, value: traitValue};
  });
  const second = compileWorkspace(secondWorkspace, secondTraits);
  assert.equal(first.text, canonicalJSONString(value));
  assert.equal(second.text, first.text, "decompiler layout/topology must be deterministic");
  assert.deepEqual(first.budgets, budgetRuleset(first.value, first.text));
  workspace.dispose();
  secondWorkspace.dispose();
  return first;
}

const corpus = [worked, allOperators, traitsOnly, nullRuleset].map(roundTrip);

const python = process.env.PYTHON
  ?? [join(root, ".venv/bin/python"), resolve(root, "../../../.venv/bin/python")].find(existsSync);
assert.ok(python, "set PYTHON to the project venv interpreter");
const verifier = String.raw`
import json, sys
from coworld.ruleset import RulesetLimits, parse_ruleset
case = json.load(sys.stdin)
text, nodes, depth = case["text"], case["nodes"], case["depth"]
result = parse_ruleset(text)
payload = {"valid": result.valid, "errors": [str(e) for e in result.errors], "nodes": result.node_count, "bytes": result.byte_count}
if result.valid and depth:
    payload["at_depth_valid"] = parse_ruleset(text, RulesetLimits(max_depth=depth)).valid
    payload["below_depth_valid"] = parse_ruleset(text, RulesetLimits(max_depth=max(1, depth - 1))).valid if depth > 1 else True
print(json.dumps(payload))
`;

for (const compiled of corpus) {
  const checked = spawnSync(python, ["-c", verifier], {
    cwd: root,
    env: {...process.env, PYTHONPATH: join(root, "src")},
    input: JSON.stringify({text: compiled.text, nodes: compiled.budgets.nodes, depth: compiled.budgets.depth}),
    encoding: "utf8",
  });
  assert.equal(checked.status, 0, checked.stderr);
  const result = JSON.parse(checked.stdout);
  assert.equal(result.valid, true, result.errors?.join("; "));
  assert.equal(result.nodes, compiled.budgets.nodes, "client and validator node counts differ");
  assert.equal(result.bytes, compiled.budgets.bytes, "client and validator byte counts differ");
  if (compiled.budgets.depth) {
    assert.equal(result.at_depth_valid, true, "client under-reported expression depth");
    if (compiled.budgets.depth > 1) assert.equal(result.below_depth_valid, false, "client over-reported expression depth");
  }
}

const workspace = new Blockly.Workspace();
const add = workspace.newBlock("operator_add");
add.loadExtraState({itemCount: 5});
assert.equal(add.itemCount_, 5);
assert.ok(add.getInput("ARG4"));
const rootBlock = workspace.newBlock("movement");
const rule = workspace.newBlock("otherwise_rule");
rootBlock.getInput("RULES").connection.connect(rule.previousConnection);
rule.getInput("SCORE").connection.connect(add.outputConnection);
for (let index = 0; index < 5; index += 1) {
  const literal = workspace.newBlock("number_literal");
  literal.setFieldValue(String(index + 1), "VALUE");
  add.getInput(`ARG${index}`).connection.connect(literal.outputConnection);
}
const variadic = compileWorkspace(workspace);
assert.deepEqual(variadic.value.movement[0].score, ["+", 1, 2, 3, 4, 5]);
workspace.dispose();

const incomplete = new Blockly.Workspace();
const movement = incomplete.newBlock("movement");
const conditional = incomplete.newBlock("when_rule");
movement.getInput("RULES").connection.connect(conditional.previousConnection);
const invalid = compileWorkspace(incomplete);
assert.ok(invalid.lints.some(issue => issue.path === "$.movement[0].if"));
assert.ok(invalid.lints.some(issue => issue.path === "$.movement[-1]"));
assert.equal(invalid.pathTargets.get("$.movement[-1]").id, conditional.id);
incomplete.dispose();

const mapped = roundTrip(worked);
assert.equal(mapped.pathTargets.get("$.movement[0].if[1][1]").kind, "block");
assert.equal(mapped.pathTargets.get("$.movement[-1]").kind, "block");

class MemoryStorage {
  constructor(initial = {}) { this.values = new Map(Object.entries(initial)); }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
}

class FakeTimers {
  constructor() { this.callbacks = []; }
  setTimeout(callback) { this.callbacks.push(callback); return callback; }
  clearTimeout(callback) { this.callbacks = this.callbacks.filter(entry => entry !== callback); }
  runNext() { const callback = this.callbacks.shift(); assert.ok(callback); callback(); }
}

const catalog = {
  default_variant: "solo-ladder",
  variants: [
    {id: "solo-ladder", name: "Solo Ladder", kind: "pooled", modes: ["ranked-preview", "exploration"], context_id: "solo-ladder", seats: 1, timesteps: 1000, measurement_window: 100, scenarios: [
      {id: "one", context_id: "solo-ladder:one", description: "One", targets: ["target.one"]},
      {id: "two", context_id: "solo-ladder:two", description: "Two", targets: ["target.two"]},
    ]},
    {id: "commonwealth", name: "Commonwealth", kind: "fixed", modes: ["fixed"], context_id: "commonwealth", seats: 4, timesteps: 1000, measurement_window: 100, scenarios: []},
  ],
};

{
  const storage = new MemoryStorage({[STUDIO_SETTINGS_KEY]: JSON.stringify({version: 0, variantId: "commonwealth"})});
  const settings = new PlaySettings(catalog, {storage});
  assert.equal(settings.snapshot().variantId, "solo-ladder");
  settings.setMode("exploration");
  settings.update({scenarioId: "two", seedMode: "fixed", fixedSeed: "900719925474099312345", timesteps: 100});
  assert.deepEqual(settings.runOptions(), {variant: "solo-ladder", mode: "exploration", seed: "900719925474099312345", scenario: "two", timesteps: 100});
  assert.equal(settings.contextId(), "solo-ladder:two");
  settings.setMode("ranked-preview");
  assert.equal(settings.derivedScenario(), catalog.variants[0].scenarios[Number(900719925474099312345n % 2n)].id);
  settings.setContext("commonwealth");
  assert.equal(settings.snapshot().variantId, "commonwealth");
  assert.equal(settings.snapshot().mode, "fixed");
  settings.setContext("solo-ladder:one");
  assert.equal(settings.snapshot().mode, "exploration");
  assert.equal(settings.snapshot().scenarioId, "one");
  settings.update({seedMode: "fixed", fixedSeed: "01"});
  assert.throws(() => settings.runOptions(), /canonical/);
  assert.equal(JSON.parse(storage.getItem(STUDIO_SETTINGS_KEY)).version, 1);
}

{
  assert.equal(readRunOrigin({search: "?run=http%3A%2F%2Flocalhost%3A7002"}), "http://localhost:7002");
  assert.throws(() => readRunOrigin({search: "?run=https%3A%2F%2Fevil.example"}), /loopback/);
  const runId = "b".repeat(32);
  assert.equal(runViewerUrl("http://127.0.0.1:7002", runId), `http://127.0.0.1:7002/runs/${runId}/client/replay`);
  assert.match(runViewerUrl("http://127.0.0.1:7002", runId, {canonical: true}), /\?replay=\/runs\//);
}

{
  const timers = new FakeTimers();
  const runId = "c".repeat(32);
  const displayed = [];
  const statuses = [
    {run_id: runId, state: "running", tick: 4, total: 10, running_scores: [0.4]},
    {run_id: runId, state: "done", tick: 10, total: 10, results: {scores: [0.8], details: []}},
  ];
  const api = {
    startRun: async ruleset => { assert.deepEqual(ruleset, worked); return {run_id: runId, seed: "9007199254740993", scenario_id: "one", context_id: "solo-ladder:one", seats: 1, timesteps: 10, opponents: []}; },
    setDisplayedRun: async id => { displayed.push(id); },
    getRun: async () => statuses.shift(),
    cancelRun: async () => ({run_id: runId, state: "cancelling", tick: 4, total: 10}),
  };
  const controller = new RunController(api, "http://127.0.0.1:7002", {timers});
  const frames = [];
  controller.onFrame(frame => frames.push(frame));
  await controller.start(worked, {variant: "solo-ladder", mode: "ranked-preview", seed: "9007199254740993"});
  assert.equal(frames.length, 1);
  assert.equal(frames[0], `http://127.0.0.1:7002/runs/${runId}/client/replay`);
  timers.runNext(); await new Promise(resolvePromise => setImmediate(resolvePromise));
  timers.runNext(); await new Promise(resolvePromise => setImmediate(resolvePromise));
  assert.equal(controller.snapshot().phase, "done");
  assert.equal(frames.length, 1, "terminal polling must not replace the live iframe");
  await controller.openCanonical();
  assert.match(frames.at(-1), /\?replay=\/runs\//);
  await controller.showEditor();
  assert.equal(frames.at(-1), null);
  assert.deepEqual(displayed, [runId, runId, null]);
}

{
  const timers = new FakeTimers();
  const runId = "d".repeat(32);
  const missing = Object.assign(new Error("run not found"), {status: 404});
  let displayCalls = 0;
  const api = {
    startRun: async () => ({run_id: runId, seed: "1", scenario_id: null, context_id: "commonwealth", seats: 4, timesteps: 10, opponents: []}),
    setDisplayedRun: async () => { if (++displayCalls > 1) throw missing; },
    getRun: async () => ({run_id: runId, state: "done", tick: 10, total: 10, results: {scores: [2], details: []}}),
  };
  const controller = new RunController(api, "http://127.0.0.1:7002", {timers});
  await controller.start(null, {variant: "commonwealth", mode: "fixed", seed: "1"});
  timers.runNext(); await new Promise(resolvePromise => setImmediate(resolvePromise));
  assert.equal(controller.snapshot().phase, "done");
  await controller.reopen();
  assert.equal(controller.snapshot().phase, "expired");
}

console.log("Ruleset Studio block model passed");
