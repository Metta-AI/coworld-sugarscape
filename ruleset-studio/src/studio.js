import {
  TOOLBOX,
  TRAIT_NAMES,
  compileWorkspace,
  decompileRuleset,
  selectedSubtree,
  studioTheme,
} from "./blocks.js";

const limits = {nodes: 256, depth: 16, bytes: 32768};
const apiBase = new URLSearchParams(location.search).get("api") ?? "http://127.0.0.1:4323";
const traitState = Object.fromEntries(TRAIT_NAMES.map(name => [name, {enabled: false, value: 0}]));
let contexts = [];
let activeContext = null;
let activeFile = null;
let compilation = null;
let serverValidation = null;
let validationGeneration = 0;
let validationTimer = null;
let highlighted = null;
let toastTimer = null;
let applyingSnapshot = false;

const workspace = Blockly.inject("blockly", {
  toolbox: TOOLBOX,
  theme: studioTheme(),
  renderer: "zelos",
  media: "vendor/blockly/media/",
  sounds: false,
  trashcan: true,
  grid: {spacing: 18, length: 1, colour: "#e4dac8", snap: false},
  zoom: {controls: true, wheel: true, startScale: 0.88, maxScale: 1.5, minScale: 0.45, scaleSpeed: 1.1},
  move: {scrollbars: true, drag: true, wheel: true},
});

class RulesetPatchEvent extends Blockly.Events.Abstract {
  static TYPE = "ruleset_studio_patch";

  constructor(oldRuleset = null, newRuleset = null) {
    super();
    this.type = RulesetPatchEvent.TYPE;
    this.workspaceId = workspace.id;
    this.oldRuleset = oldRuleset;
    this.newRuleset = newRuleset;
    this.recordUndo = true;
  }

  toJson() {
    return {...super.toJson(), oldRuleset: this.oldRuleset, newRuleset: this.newRuleset};
  }

  static fromJson(json) {
    const event = new RulesetPatchEvent(json.oldRuleset, json.newRuleset);
    event.workspaceId = json.workspaceId;
    return event;
  }

  run(forward) {
    applyRulesetSnapshot(forward ? this.newRuleset : this.oldRuleset, {clearUndo: false});
  }
}

Blockly.registry.register(Blockly.registry.Type.EVENT, RulesetPatchEvent.TYPE, RulesetPatchEvent);

workspace.addChangeListener(event => {
  if (applyingSnapshot || event.isUiEvent || event.type === Blockly.Events.FINISHED_LOADING) return;
  updateStudio();
});
window.addEventListener("resize", () => Blockly.svgResize(workspace));

document.querySelectorAll(".disclose").forEach(button => {
  button.addEventListener("click", () => {
    const section = button.closest(".dsection");
    const collapsed = section.classList.toggle("collapsed");
    button.setAttribute("aria-expanded", String(!collapsed));
    Blockly.svgResize(workspace);
  });
});

document.getElementById("new-button").addEventListener("click", () => {
  activeFile = null;
  applyRulesetSnapshot(null, {clearUndo: true});
  renderActiveFile();
  toast("Fresh null ruleset");
});
document.getElementById("load-button").addEventListener("click", () => loadRuleset(document.getElementById("file-select").value));
document.getElementById("save-button").addEventListener("click", saveRuleset);
document.getElementById("context-select").addEventListener("change", event => selectContext(event.target.value));
document.getElementById("chat-form").addEventListener("submit", sendChat);

async function fetchJson(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, options);
  let payload;
  try { payload = await response.json(); } catch { payload = {error: `HTTP ${response.status}`}; }
  if (!response.ok) {
    const error = new Error(payload.error ?? `HTTP ${response.status}`);
    error.response = response;
    error.payload = payload;
    throw error;
  }
  return payload;
}

async function boot() {
  try {
    const [contextPayload, filesPayload] = await Promise.all([fetchJson("/api/context"), fetchJson("/api/rulesets")]);
    contexts = contextPayload.contexts;
    renderContexts();
    selectContext(contextPayload.default);
    renderFiles(filesPayload.rulesets);
    const latest = filesPayload.rulesets[0]?.name ?? "worked-example.json";
    await loadRuleset(latest);
  } catch (error) {
    setStatus("bad", "API unavailable");
    renderIssues([{path: "$", message: `Studio API unavailable: ${error.message}`}]);
  }
}

function renderContexts() {
  const select = document.getElementById("context-select");
  select.replaceChildren(...contexts.map(context => new Option(context.label, context.id)));
}

function selectContext(id) {
  activeContext = contexts.find(context => context.id === id) ?? contexts[0] ?? null;
  if (!activeContext) return;
  document.getElementById("context-select").value = activeContext.id;
  for (const name of TRAIT_NAMES) {
    const [minimum, maximum] = activeContext.trait_ranges[name];
    traitState[name].value = Math.min(maximum, Math.max(minimum, traitState[name].value));
  }
  renderTraits();
  updateStudio();
}

function renderTraits() {
  const host = document.getElementById("traits");
  host.replaceChildren();
  for (const name of TRAIT_NAMES) {
    const state = traitState[name];
    const [minimum, maximum] = activeContext?.trait_ranges[name] ?? [0, 1];
    const [dtlMinimum, dtlMaximum] = activeContext?.dtl_factor_ranges[name] ?? [0, 0];
    const generated = dtlMinimum === dtlMaximum ? formatNumber(dtlMinimum) : `generated in [${formatNumber(dtlMinimum)}, ${formatNumber(dtlMaximum)}]`;
    const step = minimum === maximum ? 1 : Math.max((maximum - minimum) / 100, 0.001);
    const row = document.createElement("div");
    row.className = `trait${state.enabled ? "" : " off"}`;
    row.dataset.trait = name;
    row.innerHTML = `<div class="trait-head"><input type="checkbox" id="trait-${name}-enabled" aria-label="Override ${name}"><label class="trait-name" for="trait-${name}-enabled">${name}</label><span class="trait-value"></span></div><input type="range" id="trait-${name}" min="${minimum}" max="${maximum}" step="${step}" aria-label="${name} value"><div class="trait-range"><span>${formatNumber(minimum)}</span><span>clamps at spawn</span><span>${formatNumber(maximum)}</span></div>`;
    const checkbox = row.querySelector("input[type=checkbox]");
    const slider = row.querySelector("input[type=range]");
    checkbox.checked = state.enabled;
    slider.disabled = !state.enabled || minimum === maximum;
    slider.value = String(state.enabled ? state.value : Math.min(maximum, Math.max(minimum, dtlMinimum)));
    row.querySelector(".trait-value").textContent = state.enabled ? formatNumber(state.value) : generated;
    checkbox.addEventListener("change", () => {
      state.enabled = checkbox.checked;
      if (state.enabled) state.value = Number(slider.value);
      renderTraits();
      updateStudio();
    });
    slider.addEventListener("input", () => {
      state.value = Number(slider.value);
      row.querySelector(".trait-value").textContent = formatNumber(state.value);
      updateStudio();
    });
    host.append(row);
  }
}

function formatNumber(value) {
  return Number(value).toLocaleString(undefined, {maximumFractionDigits: 3});
}

function renderFiles(files) {
  const select = document.getElementById("file-select");
  select.replaceChildren(...files.map(file => new Option(`${file.valid ? "" : "⚠ "}${file.name}`, file.name)));
  if (activeFile) select.value = activeFile;
}

async function refreshFiles() {
  const payload = await fetchJson("/api/rulesets");
  renderFiles(payload.rulesets);
}

async function loadRuleset(name) {
  if (!name) return;
  try {
    const response = await fetch(`${apiBase}/api/rulesets/${encodeURIComponent(name)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const value = JSON.parse(await response.text());
    activeFile = name;
    applyRulesetSnapshot(value, {clearUndo: true});
    renderActiveFile();
    document.getElementById("file-select").value = name;
    toast(`Loaded ${name}`);
  } catch (error) {
    toast(`Could not load ${name}: ${error.message}`);
  }
}

function applyRulesetSnapshot(value, {clearUndo}) {
  applyingSnapshot = true;
  Blockly.Events.disable();
  try {
    workspace.clear();
    decompileRuleset(workspace, value, (name, enabled, traitValue) => {
      traitState[name] = {enabled, value: Number(traitValue)};
    });
    renderTraits();
  } finally {
    Blockly.Events.enable();
    applyingSnapshot = false;
  }
  if (clearUndo) workspace.clearUndo();
  workspace.render();
  Blockly.svgResize(workspace);
  if (workspace.getTopBlocks(false).length) workspace.scrollCenter();
  updateStudio();
}

function updateStudio() {
  compilation = compileWorkspace(workspace, traitState);
  document.getElementById("json-preview").textContent = compilation.text;
  renderBudgets(compilation.budgets);
  serverValidation = null;
  setStatus("wait", "Checking");
  renderIssues(localIssues());
  clearTimeout(validationTimer);
  const generation = ++validationGeneration;
  validationTimer = setTimeout(() => validateCandidate(generation), 300);
}

function localIssues() {
  const issues = [...compilation.lints];
  if (activeContext) {
    for (const name of TRAIT_NAMES) {
      const state = traitState[name];
      const [minimum, maximum] = activeContext.trait_ranges[name];
      if (state.enabled && (state.value < minimum || state.value > maximum)) issues.push({path: `$.traits.${name}`, message: `trait must be inside [${minimum}, ${maximum}]`});
    }
  }
  return issues;
}

async function validateCandidate(generation) {
  try {
    const result = await fetchJson("/api/validate", {method: "POST", headers: {"Content-Type": "application/json"}, body: compilation.text});
    if (generation !== validationGeneration) return;
    serverValidation = result;
    const issues = [...localIssues(), ...result.errors];
    renderIssues(issues);
    setStatus(issues.length || !result.valid ? "bad" : "ok", issues.length || !result.valid ? `${issues.length} issue${issues.length === 1 ? "" : "s"}` : "Valid");
  } catch (error) {
    if (generation !== validationGeneration) return;
    renderIssues([...localIssues(), {path: "$", message: `Validation unavailable: ${error.message}`}]);
    setStatus("bad", "Offline");
  }
}

function renderBudgets(budgets) {
  document.getElementById("budget-summary").textContent = `${budgets.nodes}/256 · depth ${budgets.depth} · ${budgets.bytes.toLocaleString()} B`;
  for (const name of ["nodes", "depth", "bytes"]) {
    const used = budgets[name], cap = limits[name];
    const bar = document.getElementById(`bar-${name}`);
    bar.style.width = `${Math.max(1, Math.min(100, used / cap * 100))}%`;
    bar.classList.toggle("over", used > cap);
    document.getElementById(`val-${name}`).textContent = `${used.toLocaleString()} / ${cap.toLocaleString()}`;
  }
}

function renderIssues(issues) {
  const host = document.getElementById("validation-list");
  host.replaceChildren();
  if (!issues.length) {
    const row = document.createElement("div");
    row.className = "validation-row ok";
    row.innerHTML = '<span class="mark">✓</span><span>Structure and budgets are valid</span>';
    host.append(row);
    return;
  }
  for (const issue of issues) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "validation-row";
    const mark = document.createElement("span"); mark.className = "mark"; mark.textContent = "!";
    const text = document.createElement("span");
    const path = document.createElement("code"); path.textContent = issue.path;
    text.append(path, document.createElement("br"), issue.message);
    button.append(mark, text);
    button.addEventListener("click", () => highlightPath(issue.path, issue.blockId));
    host.append(button);
  }
}

function highlightPath(path, explicitBlockId) {
  let entry = explicitBlockId ? {kind: "block", id: explicitBlockId} : compilation.pathTargets.get(path);
  let candidate = path;
  while (!entry && candidate !== "$" && candidate) {
    candidate = candidate.replace(/(?:\.[^.\[]+|\[-?\d+\])$/, "") || "$";
    entry = compilation.pathTargets.get(candidate);
  }
  if (!entry) return;
  if (entry.kind === "trait") {
    document.getElementById(`trait-${entry.id}-enabled`)?.focus();
    return;
  }
  if (entry.kind === "document") {
    document.getElementById(entry.id)?.focus();
    return;
  }
  const block = workspace.getBlockById(entry.id);
  if (!block) return;
  block.select();
  workspace.centerOnBlock(block.id);
  highlighted?.getSvgRoot?.()?.classList.remove("studio-error-highlight");
  highlighted = block;
  block.getSvgRoot?.()?.classList.add("studio-error-highlight");
  setTimeout(() => block.getSvgRoot?.()?.classList.remove("studio-error-highlight"), 1800);
}

function setStatus(kind, text) {
  const chip = document.getElementById("valid-chip");
  chip.className = `chip chip-${kind}`;
  chip.lastChild.textContent = text;
}

function renderActiveFile() {
  document.getElementById("active-file").textContent = activeFile ?? "untitled.json";
}

async function saveRuleset() {
  let name = activeFile;
  if (!name) name = window.prompt("Save as (letters, numbers, . _ - only)", "untitled.json")?.trim();
  if (!name) return;
  if (!/^[A-Za-z0-9._-]+\.json$/.test(name)) {
    toast("Filename must match [A-Za-z0-9._-]+.json");
    return;
  }
  try {
    await putRuleset(name, false);
  } catch (error) {
    if (error.response?.status !== 422) return toast(`Save failed: ${error.message}`);
    const summary = error.payload.errors.map(issue => `${issue.path}: ${issue.message}`).join("\n");
    if (!window.confirm(`This ruleset is invalid and was not saved:\n\n${summary}\n\nForce-save it anyway?`)) return;
    try { await putRuleset(name, true); } catch (forcedError) { return toast(`Force-save failed: ${forcedError.message}`); }
  }
  activeFile = name;
  renderActiveFile();
  await refreshFiles();
  document.getElementById("file-select").value = name;
  toast(`Saved ${name}`);
}

function putRuleset(name, force) {
  return fetchJson(`/api/rulesets/${encodeURIComponent(name)}${force ? "?force=1" : ""}`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: compilation.text});
}

function appendMessage(who, message, patch = null) {
  const thread = document.getElementById("chat-thread");
  const item = document.createElement("div");
  item.className = "msg";
  const label = document.createElement("div"); label.className = "who eyebrow"; label.textContent = who;
  const paragraph = document.createElement("p"); paragraph.textContent = message;
  item.append(label, paragraph);
  if (patch) {
    const actions = document.createElement("div"); actions.className = "patch-actions";
    const apply = document.createElement("button"); apply.type = "button"; apply.className = "btn btn-secondary"; apply.textContent = "Apply to canvas";
    apply.addEventListener("click", () => { window.link.applyPatch(patch); apply.disabled = true; });
    actions.append(apply); item.append(actions);
  }
  thread.append(item);
  thread.scrollTop = thread.scrollHeight;
}

async function sendChat(event) {
  event.preventDefault();
  const input = document.getElementById("chat-text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMessage("You", text);
  document.getElementById("chat-cap").textContent = "Waiting for your live coding session…";
  const response = await window.link.ask(text, null, {
    ruleset: compilation.value,
    activeFile,
    contextId: activeContext?.id,
    validation: {local: localIssues(), server: serverValidation},
    selected: selectedSubtree(workspace, compilation),
  });
  document.getElementById("chat-cap").textContent = response.timedOut ? "The bridge did not answer; editing remains available." : "Replies can propose an undoable canvas patch.";
  appendMessage("Agent · live session", response.reply ?? "", response.patch);
}

window.linkApplyPatch = async set => {
  if (!("ruleset" in set)) return;
  const candidateText = `${JSON.stringify(set.ruleset, null, 2)}\n`;
  let validation;
  try {
    validation = await fetchJson("/api/validate", {method: "POST", headers: {"Content-Type": "application/json"}, body: candidateText});
  } catch (error) {
    appendMessage("Studio", `Could not validate the proposed patch: ${error.message}`);
    return;
  }
  if (!validation.valid) {
    appendMessage("Studio", `Patch rejected: ${validation.errors.map(issue => `${issue.path}: ${issue.message}`).join("; ")}`);
    return;
  }
  const oldRuleset = compilation.value;
  try {
    applyRulesetSnapshot(set.ruleset, {clearUndo: false});
    Blockly.Events.fire(new RulesetPatchEvent(oldRuleset, set.ruleset));
    toast(set.note ? `Changed by agent · ${set.note}` : "Changed by agent · Undo restores the prior ruleset");
  } catch (error) {
    applyRulesetSnapshot(oldRuleset, {clearUndo: false});
    appendMessage("Studio", `Patch rejected: ${error.message}`);
  }
};

window.link.onStatus(health => {
  const chip = document.getElementById("bridge-chip");
  chip.className = `chip ${health.bridgeConnected ? "chip-ok" : "chip-off"}`;
  chip.lastChild.textContent = health.bridgeConnected ? "Bridge live" : "Not connected";
});

function toast(message) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 2600);
}

boot();
