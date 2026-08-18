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

console.log("Ruleset Studio block model passed");
