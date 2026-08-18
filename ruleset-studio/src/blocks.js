const Blockly = globalThis.Blockly;

if (!Blockly) {
  throw new Error("Blockly must be loaded before blocks.js");
}

export const TRAIT_NAMES = ["aggression", "trade", "lending", "fertility"];

export const FEATURES = {
  agent: [
    ["sugar", "agent.sugar", "Current sugar"],
    ["spice", "agent.spice", "Current spice"],
    ["wealth", "agent.wealth", "Sugar plus spice"],
    ["sugar metabolism", "agent.sugarMetabolism", "Effective sugar metabolism"],
    ["spice metabolism", "agent.spiceMetabolism", "Effective spice metabolism"],
    ["vision", "agent.vision", "Effective vision"],
    ["movement", "agent.movement", "Effective movement range"],
    ["age", "agent.age", "Current age"],
    ["time to live", "agent.ttl", "DTL findTimeToLive() result"],
    ["MRS", "agent.mrs", "DTL marginal rate of substitution"],
  ],
  cell: [
    ["sugar", "cell.sugar", "Sugar currently at the candidate"],
    ["spice", "cell.spice", "Spice currently at the candidate"],
    ["pollution", "cell.pollution", "Candidate pollution"],
    ["distance", "cell.distance", "DTL travel distance"],
    ["occupied", "cell.occupied", "1.0 when occupied, otherwise 0.0"],
    ["prey wealth", "cell.preyWealth", "Occupant sugar plus spice, or zero"],
    ["welfare", "cell.welfare", "DTL candidate welfare before SugarLang scoring"],
  ],
  world: [
    ["timestep", "world.timestep", "Current tick T"],
    ["population", "world.population", "Population at the start of tick T"],
    ["Gini", "world.gini", "Completed DTL Gini statistic from tick T-1"],
    ["mean wealth", "world.meanWealth", "Completed DTL mean wealth from tick T-1"],
  ],
};

const NARY_OPERATORS = ["+", "-", "*", "/", "min", "max", "and", "or"];
const UNARY_OPERATORS = ["abs", "neg", "not"];
const BINARY_OPERATORS = ["pow", "<", "<=", ">", ">=", "==", "!="];
const OPERATOR_LABELS = {"*": "×", "/": "÷", "<=": "≤", ">=": "≥", "==": "=", "!=": "≠"};

const LIGHT_STYLES = {
  rule_blocks: {colourPrimary: "#eef2f7", colourSecondary: "#c8d4e6", colourTertiary: "#1a3875"},
  feature_blocks: {colourPrimary: "#e9edda", colourSecondary: "#ccd6ae", colourTertiary: "#4c5a2b"},
  math_blocks: {colourPrimary: "#f7edd3", colourSecondary: "#e4cf9a", colourTertiary: "#78591a"},
  compare_blocks: {colourPrimary: "#f5e5da", colourSecondary: "#ddc0ac", colourTertiary: "#86492b"},
  value_blocks: {colourPrimary: "#fffdf4", colourSecondary: "#d4c9b5", colourTertiary: "#111827"},
};

// Same category hues, inverted for dark surfaces: deep fills, lighter borders.
const DARK_STYLES = {
  rule_blocks: {colourPrimary: "#24395b", colourSecondary: "#3b537c", colourTertiary: "#9fb6dd"},
  feature_blocks: {colourPrimary: "#333d1f", colourSecondary: "#4a582f", colourTertiary: "#b5c48a"},
  math_blocks: {colourPrimary: "#40351a", colourSecondary: "#5c4d27", colourTertiary: "#d9bd7a"},
  compare_blocks: {colourPrimary: "#3f2a1c", colourSecondary: "#5a3d29", colourTertiary: "#d6a483"},
  value_blocks: {colourPrimary: "#1f2937", colourSecondary: "#374151", colourTertiary: "#e5e7eb"},
};

export function studioTheme(dark = false) {
  return Blockly.Theme.defineTheme(dark ? "ruleset_studio_dark" : "ruleset_studio", {
    base: Blockly.Themes.Classic,
    blockStyles: dark ? DARK_STYLES : LIGHT_STYLES,
    componentStyles: dark
      ? {
          workspaceBackgroundColour: "#0b1220",
          toolboxBackgroundColour: "#111827",
          toolboxForegroundColour: "#f3f4f6",
          flyoutBackgroundColour: "#1f2937",
          flyoutForegroundColour: "#f3f4f6",
          flyoutOpacity: 1,
          scrollbarColour: "#374151",
          insertionMarkerColour: "#859ebe",
          insertionMarkerOpacity: 0.4,
          cursorColour: "#bacbf5",
        }
      : {
          workspaceBackgroundColour: "#fffaf0",
          toolboxBackgroundColour: "#fffaf0",
          toolboxForegroundColour: "#111827",
          flyoutBackgroundColour: "#f8f6ef",
          flyoutForegroundColour: "#111827",
          flyoutOpacity: 1,
          scrollbarColour: "#d4c9b5",
          insertionMarkerColour: "#859ebe",
          insertionMarkerOpacity: 0.35,
          cursorColour: "#1a3875",
        },
    fontStyle: {family: 'Georgia, "Times New Roman", serif', weight: "600", size: 11},
  });
}

function featureTooltip(category, block) {
  const value = block.getFieldValue("FEATURE");
  return FEATURES[category].find((entry) => entry[1] === value)?.[2] ?? value;
}

function updateVariadicShape(block) {
  let index = 0;
  while (block.getInput(`ARG${index}`)) {
    block.removeInput(`ARG${index}`);
    index += 1;
  }
  for (let inputIndex = 0; inputIndex < block.itemCount_; inputIndex += 1) {
    const input = block.appendValueInput(`ARG${inputIndex}`).setCheck("Number");
    if (inputIndex === 0) input.appendField(OPERATOR_LABELS[block.operator_] ?? block.operator_);
  }
  block.setInputsInline(true);
}

const variadicMixin = {
  itemCount_: 2,
  saveExtraState() {
    return {itemCount: this.itemCount_};
  },
  loadExtraState(state) {
    this.itemCount_ = Math.max(2, Number(state?.itemCount) || 2);
    updateVariadicShape(this);
  },
  decompose(workspace) {
    const container = workspace.newBlock("studio_variadic_container");
    container.initSvg?.();
    let connection = container.getInput("STACK").connection;
    for (let index = 0; index < this.itemCount_; index += 1) {
      const item = workspace.newBlock("studio_variadic_item");
      item.initSvg?.();
      connection.connect(item.previousConnection);
      connection = item.nextConnection;
    }
    return container;
  },
  compose(container) {
    const connections = [];
    let item = container.getInputTargetBlock("STACK");
    while (item) {
      if (!item.isInsertionMarker?.()) connections.push(item.valueConnection_ ?? null);
      item = item.nextConnection?.targetBlock() ?? null;
    }
    while (connections.length < 2) connections.push(null);
    for (let index = 0; index < this.itemCount_; index += 1) {
      const connection = this.getInput(`ARG${index}`)?.connection?.targetConnection;
      if (connection && !connections.includes(connection)) connection.disconnect();
    }
    this.itemCount_ = connections.length;
    updateVariadicShape(this);
    connections.forEach((connection, index) => {
      if (connection) this.getInput(`ARG${index}`).connection.connect(connection);
    });
  },
  saveConnections(container) {
    let item = container.getInputTargetBlock("STACK");
    let index = 0;
    while (item) {
      if (!item.isInsertionMarker?.()) {
        item.valueConnection_ = this.getInput(`ARG${index}`)?.connection?.targetConnection ?? null;
        index += 1;
      }
      item = item.nextConnection?.targetBlock() ?? null;
    }
  },
};

export function registerStudioBlocks() {
  if (Blockly.Blocks.movement) return;

  Blockly.common.defineBlocksWithJsonArray([
    {type: "movement", message0: "movement %1", args0: [{type: "input_statement", name: "RULES", check: "MovementRule"}], style: "rule_blocks", tooltip: "Ordered movement decision list"},
    {type: "when_rule", message0: "when %1 score %2", args0: [{type: "input_value", name: "IF", check: "Number"}, {type: "input_value", name: "SCORE", check: "Number"}], previousStatement: "MovementRule", nextStatement: "MovementRule", inputsInline: true, style: "rule_blocks"},
    {type: "otherwise_rule", message0: "otherwise score %1", args0: [{type: "input_value", name: "SCORE", check: "Number"}], previousStatement: "MovementRule", nextStatement: "MovementRule", inputsInline: true, style: "rule_blocks"},
    {type: "number_literal", message0: "%1", args0: [{type: "field_number", name: "VALUE", value: 0}], output: "Number", style: "value_blocks", tooltip: "Finite numeric literal"},
    {type: "studio_variadic_container", message0: "operands %1", args0: [{type: "input_statement", name: "STACK"}], style: "math_blocks", enableContextMenu: false},
    {type: "studio_variadic_item", message0: "operand", previousStatement: null, nextStatement: null, style: "math_blocks", enableContextMenu: false},
  ]);

  for (const [category, entries] of Object.entries(FEATURES)) {
    Blockly.Blocks[`${category}_feature`] = {
      init() {
        this.appendDummyInput()
          .appendField(category)
          .appendField(new Blockly.FieldDropdown(entries.map(([label, value]) => [label, value])), "FEATURE");
        this.setOutput(true, "Number");
        this.setStyle("feature_blocks");
        this.setTooltip(() => featureTooltip(category, this));
      },
    };
  }

  Blockly.Extensions.registerMutator("studio_variadic_mutator", variadicMixin, undefined, ["studio_variadic_item"]);
  for (const operator of NARY_OPERATORS) {
    Blockly.Blocks[`operator_${operatorName(operator)}`] = {
      init() {
        this.operator_ = operator;
        this.itemCount_ = 2;
        updateVariadicShape(this);
        this.setOutput(true, "Number");
        this.setStyle(["and", "or"].includes(operator) ? "compare_blocks" : "math_blocks");
        this.setMutator(new Blockly.icons.MutatorIcon(["studio_variadic_item"], this));
        this.setTooltip(`${operator} takes two or more operands, evaluated left to right`);
      },
      ...variadicMixin,
    };
  }

  for (const operator of UNARY_OPERATORS) {
    Blockly.Blocks[`operator_${operator}`] = {
      init() {
        this.appendValueInput("ARG0").setCheck("Number").appendField(operator);
        this.setOutput(true, "Number");
        this.setStyle(operator === "not" ? "compare_blocks" : "math_blocks");
      },
    };
  }
  for (const operator of BINARY_OPERATORS) {
    Blockly.Blocks[`operator_${operatorName(operator)}`] = {
      init() {
        this.appendValueInput("ARG0").setCheck("Number");
        this.appendValueInput("ARG1").setCheck("Number").appendField(OPERATOR_LABELS[operator] ?? operator);
        this.setInputsInline(true);
        this.setOutput(true, "Number");
        this.setStyle(operator === "pow" ? "math_blocks" : "compare_blocks");
      },
    };
  }
  Blockly.Blocks.operator_if = {
    init() {
      this.appendValueInput("ARG0").setCheck("Number").appendField("if");
      this.appendValueInput("ARG1").setCheck("Number").appendField("then");
      this.appendValueInput("ARG2").setCheck("Number").appendField("else");
      this.setOutput(true, "Number");
      this.setStyle("compare_blocks");
    },
  };
}

function operatorName(operator) {
  return ({"+": "add", "-": "subtract", "*": "multiply", "/": "divide", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "==": "eq", "!=": "neq"})[operator] ?? operator;
}

function typeOperator(type) {
  const name = type.replace(/^operator_/, "");
  return ({add: "+", subtract: "-", multiply: "*", divide: "/", lt: "<", lte: "<=", gt: ">", gte: ">=", eq: "==", neq: "!="})[name] ?? name;
}

export const TOOLBOX = {
  kind: "categoryToolbox",
  contents: [
    {kind: "category", name: "Rules", colour: "#1a3875", contents: ["movement", "when_rule", "otherwise_rule"].map(type => ({kind: "block", type}))},
    {kind: "category", name: "Features", colour: "#6e8050", contents: ["agent_feature", "cell_feature", "world_feature"].map(type => ({kind: "block", type}))},
    {kind: "category", name: "Math", colour: "#d4a853", contents: ["+", "-", "*", "/", "min", "max", "abs", "neg", "pow"].map(operator => ({kind: "block", type: `operator_${operatorName(operator)}`}))},
    {kind: "category", name: "Compare & logic", colour: "#b36e4e", contents: ["<", "<=", ">", ">=", "==", "!=", "and", "or", "not", "if"].map(operator => ({kind: "block", type: `operator_${operatorName(operator)}`}))},
    {kind: "category", name: "Values", colour: "#999999", contents: [{kind: "block", type: "number_literal"}]},
  ],
};

function target(pathTargets, path, block, kind = "block") {
  pathTargets.set(path, {kind, id: block.id});
}

function compileExpression(block, path, pathTargets, lints) {
  if (!block) {
    lints.push({path, message: "expression socket is empty"});
    return null;
  }
  target(pathTargets, path, block);
  if (block.type === "number_literal") return Number(block.getFieldValue("VALUE"));
  if (block.type.endsWith("_feature")) {
    target(pathTargets, `${path}[0]`, block);
    target(pathTargets, `${path}[1]`, block);
    return ["get", block.getFieldValue("FEATURE")];
  }
  if (!block.type.startsWith("operator_")) {
    lints.push({path, message: `unsupported expression block ${block.type}`});
    return null;
  }
  const operator = typeOperator(block.type);
  target(pathTargets, `${path}[0]`, block);
  const count = NARY_OPERATORS.includes(operator) ? block.itemCount_ : UNARY_OPERATORS.includes(operator) ? 1 : operator === "if" ? 3 : 2;
  const expression = [operator];
  for (let index = 0; index < count; index += 1) {
    expression.push(compileExpression(block.getInputTargetBlock(`ARG${index}`), `${path}[${index + 1}]`, pathTargets, lints));
  }
  return expression;
}

export function compileWorkspace(workspace, traitState = {}) {
  const pathTargets = new Map();
  pathTargets.set("$", {kind: "document", id: "valid-chip"});
  pathTargets.set("$.version", {kind: "document", id: "valid-chip"});
  const lints = [];
  const topBlocks = workspace.getTopBlocks(false);
  const roots = topBlocks.filter(block => block.type === "movement");
  if (roots.length > 1) lints.push({path: "$.movement", message: "only one movement block is allowed"});
  for (const block of topBlocks.filter(block => block.type !== "movement")) {
    lints.push({path: "$", message: `orphan ${block.type} block is not connected to movement`, blockId: block.id});
  }

  const traits = {};
  for (const name of TRAIT_NAMES) {
    const state = traitState[name];
    pathTargets.set(`$.traits.${name}`, {kind: "trait", id: name});
    if (state?.enabled) traits[name] = Number(state.value);
  }

  let movement;
  if (roots[0]) {
    target(pathTargets, "$.movement", roots[0]);
    movement = [];
    let rule = roots[0].getInputTargetBlock("RULES");
    let sawOtherwise = false;
    while (rule) {
      const index = movement.length;
      const rulePath = `$.movement[${index}]`;
      target(pathTargets, rulePath, rule);
      const compiledRule = {};
      if (rule.type === "when_rule") {
        if (sawOtherwise) lints.push({path: rulePath, message: "rules after otherwise are unreachable", blockId: rule.id});
        compiledRule.if = compileExpression(rule.getInputTargetBlock("IF"), `${rulePath}.if`, pathTargets, lints);
      } else if (rule.type === "otherwise_rule") {
        if (sawOtherwise) lints.push({path: rulePath, message: "only one otherwise rule is allowed", blockId: rule.id});
        sawOtherwise = true;
      } else {
        lints.push({path: rulePath, message: `unsupported rule block ${rule.type}`, blockId: rule.id});
      }
      compiledRule.score = compileExpression(rule.getInputTargetBlock("SCORE"), `${rulePath}.score`, pathTargets, lints);
      movement.push(compiledRule);
      rule = rule.nextConnection?.targetBlock() ?? null;
    }
    if (movement.length) {
      let finalBlock = roots[0].getInputTargetBlock("RULES");
      while (finalBlock?.nextConnection?.targetBlock()) finalBlock = finalBlock.nextConnection.targetBlock();
      target(pathTargets, "$.movement[-1]", finalBlock ?? roots[0]);
    }
    if (movement.length && "if" in movement.at(-1)) {
      const finalBlock = pathTargets.get("$.movement[-1]");
      lints.push({path: "$.movement[-1]", message: "final movement rule must be otherwise", blockId: finalBlock?.id});
    }
  }

  let value = null;
  if (Object.keys(traits).length || movement !== undefined) {
    value = {version: 1};
    if (Object.keys(traits).length) value.traits = traits;
    if (movement !== undefined) value.movement = movement;
  }
  const text = canonicalJSONString(value);
  const budgets = budgetRuleset(value, text);
  return {value, text, budgets, pathTargets, lints};
}

function orderedKeys(value) {
  const preferred = ["version", "traits", "movement", ...TRAIT_NAMES, "if", "score"];
  return Object.keys(value).sort((left, right) => {
    const a = preferred.indexOf(left), b = preferred.indexOf(right);
    if (a >= 0 || b >= 0) return (a < 0 ? preferred.length : a) - (b < 0 ? preferred.length : b);
    return left.localeCompare(right);
  });
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(orderedKeys(value).map(key => [key, canonicalValue(value[key])]));
  }
  return value;
}

export function canonicalJSONString(value) {
  return `${JSON.stringify(canonicalValue(value), null, 2)}\n`;
}

function expressionBudget(expression, depth = 1) {
  if (!Array.isArray(expression) || expression[0] === "get") return {nodes: 1, depth};
  let nodes = 1;
  let maximum = depth;
  for (const child of expression.slice(1)) {
    const budget = expressionBudget(child, depth + 1);
    nodes += budget.nodes;
    maximum = Math.max(maximum, budget.depth);
  }
  return {nodes, depth: maximum};
}

export function budgetRuleset(value, text = canonicalJSONString(value)) {
  let nodes = 0;
  let depth = 0;
  if (value && Array.isArray(value.movement)) {
    for (const rule of value.movement) {
      for (const key of ["if", "score"]) {
        if (!(key in rule)) continue;
        const budget = expressionBudget(rule[key]);
        nodes += budget.nodes;
        depth = Math.max(depth, budget.depth);
      }
    }
  }
  return {nodes, depth, bytes: new TextEncoder().encode(text).length};
}

function newBlock(workspace, type) {
  const block = workspace.newBlock(type);
  block.initSvg?.();
  return block;
}

function connectValue(parent, inputName, child) {
  parent.getInput(inputName).connection.connect(child.outputConnection);
}

function decompileExpression(workspace, expression) {
  if (typeof expression === "number") {
    if (!Number.isFinite(expression)) throw new Error("numeric literals must be finite");
    const block = newBlock(workspace, "number_literal");
    block.setFieldValue(String(expression), "VALUE");
    return block;
  }
  if (!Array.isArray(expression) || typeof expression[0] !== "string") throw new Error("invalid SugarLang expression");
  const operator = expression[0];
  if (operator === "get") {
    const feature = String(expression[1]);
    const category = feature.split(".", 1)[0];
    const block = newBlock(workspace, `${category}_feature`);
    block.setFieldValue(feature, "FEATURE");
    return block;
  }
  const block = newBlock(workspace, `operator_${operatorName(operator)}`);
  if (NARY_OPERATORS.includes(operator)) block.loadExtraState({itemCount: expression.length - 1});
  expression.slice(1).forEach((child, index) => connectValue(block, `ARG${index}`, decompileExpression(workspace, child)));
  return block;
}

export function decompileRuleset(workspace, value, setTrait = () => {}) {
  if (value !== null && (typeof value !== "object" || Array.isArray(value))) throw new Error("ruleset must be an object or null");
  for (const name of TRAIT_NAMES) setTrait(name, false, 0);
  if (!value || (!value.traits && !value.movement)) return;
  if (value.traits) {
    for (const name of TRAIT_NAMES) if (name in value.traits) setTrait(name, true, value.traits[name]);
  }
  if (!value.movement) return;
  const movement = newBlock(workspace, "movement");
  let previous = null;
  value.movement.forEach(rule => {
    const ruleBlock = newBlock(workspace, "if" in rule ? "when_rule" : "otherwise_rule");
    if (previous) previous.nextConnection.connect(ruleBlock.previousConnection);
    else movement.getInput("RULES").connection.connect(ruleBlock.previousConnection);
    if ("if" in rule) connectValue(ruleBlock, "IF", decompileExpression(workspace, rule.if));
    connectValue(ruleBlock, "SCORE", decompileExpression(workspace, rule.score));
    previous = ruleBlock;
  });
  movement.moveBy?.(48, 48);
}

export function selectedSubtree(workspace, compilation) {
  const selected = Blockly.getSelected?.();
  if (!selected || selected.workspace !== workspace) return null;
  let bestPath = null;
  for (const [path, entry] of compilation.pathTargets) {
    if (entry.id === selected.id && (!bestPath || path.length < bestPath.length)) bestPath = path;
  }
  if (!bestPath) return {blockId: selected.id, path: null, subtree: null};
  return {blockId: selected.id, path: bestPath, subtree: valueAtPath(compilation.value, bestPath)};
}

function valueAtPath(value, path) {
  if (path === "$" || !path) return value;
  const tokens = [];
  path.replace(/^\$\.?/, "").replace(/([^.\[\]]+)|\[(-?\d+)\]/g, (_match, key, index) => {
    tokens.push(key ?? Number(index));
    return "";
  });
  let current = value;
  for (const token of tokens) {
    if (current == null) return null;
    const actual = token === -1 && Array.isArray(current) ? current.length - 1 : token;
    current = current[actual];
  }
  return current;
}

registerStudioBlocks();
