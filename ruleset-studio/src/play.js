const DEFAULT_RUN_ORIGIN = "http://localhost:4324";
const RUN_ID = /^[0-9a-f]{32}$/;
const ACTIVE_STATES = new Set(["compiling", "running", "cancelling"]);
const TERMINAL_STATES = new Set(["done", "error", "cancelled", "expired"]);

function loopbackOrigin(value, label) {
  let url;
  try { url = new URL(value); } catch { throw new Error(`${label} must be an absolute URL`); }
  const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost";
  if (url.protocol !== "http:" || !loopback || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${label} must be a loopback HTTP origin`);
  }
  return url.origin;
}

export function readRunOrigin(location = globalThis.location) {
  const value = new URLSearchParams(location?.search || "").get("run") || DEFAULT_RUN_ORIGIN;
  return loopbackOrigin(value, "run origin");
}

export function runViewerUrl(runOrigin, runId, {canonical = false} = {}) {
  if (!RUN_ID.test(runId)) throw new Error("invalid studio run id");
  const base = `${loopbackOrigin(runOrigin, "run origin")}/runs/${runId}/client/replay`;
  return canonical ? `${base}?replay=/runs/${runId}/replay.bin` : base;
}

export const STUDIO_SETTINGS_VERSION = 1;
export const STUDIO_SETTINGS_KEY = "coworld.ruleset-studio.play-settings";

export class PlaySettings {
  constructor(catalog, {storage = globalThis.localStorage} = {}) {
    this.catalog = catalog;
    this.storage = storage;
    this.state = this.#normalize(this.#read());
  }

  get lastRunSeed() { return this.state.lastRunSeed; }

  snapshot() {
    const variant = this.variant();
    return {
      ...this.state,
      kind: variant.kind,
      scenarios: variant.scenarios.map(scenario => ({...scenario})),
      derivedScenario: this.derivedScenario(),
      isDefault: this.isDefault(),
    };
  }

  variant() {
    return this.catalog.variants.find(variant => variant.id === this.state.variantId);
  }

  setVariant(variantId) { return this.update({variantId}); }
  setMode(mode) { return this.update({mode}); }

  setContext(contextId) {
    for (const variant of this.catalog.variants) {
      if (variant.context_id === contextId) return this.update({variantId: variant.id, mode: "fixed"});
      const scenario = variant.scenarios.find(entry => entry.context_id === contextId);
      if (scenario) return this.update({variantId: variant.id, mode: "exploration", scenarioId: scenario.id});
    }
    return this.snapshot();
  }

  update(patch) {
    this.state = this.#normalize({...this.state, ...patch});
    this.#persist();
    return this.snapshot();
  }

  rememberRunSeed(seed) {
    if (typeof seed === "string" && /^(0|[1-9][0-9]*)$/.test(seed)) {
      this.state = {...this.state, lastRunSeed: seed};
      this.#persist();
    }
  }

  useLastRunSeed() {
    return this.lastRunSeed ? this.update({seedMode: "fixed", fixedSeed: this.lastRunSeed}) : this.snapshot();
  }

  derivedScenario() {
    const variant = this.variant();
    if (variant.kind !== "pooled" || this.state.mode !== "ranked-preview") return null;
    if (this.state.seedMode !== "fixed" || !this.validFixedSeed()) return null;
    return variant.scenarios[Number(BigInt(this.state.fixedSeed) % BigInt(variant.scenarios.length))]?.id || null;
  }

  contextId() {
    const variant = this.variant();
    if (this.state.mode === "exploration") {
      return variant.scenarios.find(scenario => scenario.id === this.state.scenarioId)?.context_id || null;
    }
    if (this.state.mode === "ranked-preview") {
      const scenarioId = this.derivedScenario();
      return variant.scenarios.find(scenario => scenario.id === scenarioId)?.context_id || null;
    }
    return variant.context_id;
  }

  validFixedSeed() { return /^(0|[1-9][0-9]*)$/.test(this.state.fixedSeed); }

  isDefault() {
    return this.state.variantId === this.catalog.default_variant
      && this.state.mode === "ranked-preview"
      && this.state.seedMode === "auto"
      && this.state.timesteps === null;
  }

  runOptions() {
    if (this.state.seedMode === "fixed" && !this.validFixedSeed()) {
      throw new Error("Fixed seed must be canonical decimal digits with no sign or leading zeroes.");
    }
    const options = {
      variant: this.state.variantId,
      mode: this.state.mode,
      seed: this.state.seedMode === "fixed" ? this.state.fixedSeed : null,
    };
    if (this.state.mode === "exploration") options.scenario = this.state.scenarioId;
    if (this.state.mode !== "ranked-preview" && this.state.timesteps !== null) options.timesteps = this.state.timesteps;
    return options;
  }

  #read() {
    try {
      const stored = JSON.parse(this.storage?.getItem(STUDIO_SETTINGS_KEY) || "null");
      return stored?.version === STUDIO_SETTINGS_VERSION ? stored : null;
    } catch { return null; }
  }

  #normalize(candidate) {
    const variants = this.catalog.variants;
    const variantId = variants.some(variant => variant.id === candidate?.variantId)
      ? candidate.variantId : this.catalog.default_variant;
    const variant = variants.find(entry => entry.id === variantId);
    const pooled = variant.kind === "pooled";
    const mode = pooled && ["ranked-preview", "exploration"].includes(candidate?.mode)
      ? candidate.mode : pooled ? "ranked-preview" : "fixed";
    const scenarioIds = variant.scenarios.map(scenario => scenario.id);
    const scenarioId = mode === "exploration" && scenarioIds.includes(candidate?.scenarioId)
      ? candidate.scenarioId : mode === "exploration" ? scenarioIds[0] : null;
    const seedMode = candidate?.seedMode === "fixed" ? "fixed" : "auto";
    const fixedSeed = typeof candidate?.fixedSeed === "string" ? candidate.fixedSeed : "";
    const lastRunSeed = typeof candidate?.lastRunSeed === "string" && /^(0|[1-9][0-9]*)$/.test(candidate.lastRunSeed)
      ? candidate.lastRunSeed : null;
    const rawTimesteps = candidate?.timesteps;
    const timesteps = mode !== "ranked-preview" && Number.isInteger(rawTimesteps)
      && rawTimesteps >= 1 && rawTimesteps <= 2000 ? rawTimesteps : null;
    return {version: STUDIO_SETTINGS_VERSION, variantId, mode, scenarioId, seedMode, fixedSeed, lastRunSeed, timesteps};
  }

  #persist() { this.storage?.setItem(STUDIO_SETTINGS_KEY, JSON.stringify(this.state)); }
}

export class RunController {
  constructor(api, runOrigin, {pollInterval = 500, timers = globalThis} = {}) {
    this.api = api;
    this.runOrigin = runOrigin;
    this.pollInterval = pollInterval;
    this.timers = timers;
    this.listeners = new Set();
    this.frameListeners = new Set();
    this.timer = null;
    this.generation = 0;
    this.state = {phase: "idle", run: null, status: null, message: "Ready to compile."};
  }

  subscribe(listener) { this.listeners.add(listener); listener(this.snapshot()); return () => this.listeners.delete(listener); }
  onFrame(listener) { this.frameListeners.add(listener); return () => this.frameListeners.delete(listener); }
  snapshot() { return {...this.state}; }
  isActive() { return ACTIVE_STATES.has(this.state.phase); }

  async start(ruleset, options) {
    if (this.isActive()) throw new Error("a run is already in progress");
    this.#cancelPoll();
    const generation = ++this.generation;
    this.#set({phase: "compiling", run: null, status: null, message: "Compiling ruleset…"});
    try {
      const run = await this.api.startRun(ruleset, options);
      if (generation !== this.generation) return null;
      this.#set({phase: "running", run: {...run, mode: options.mode}, status: null, message: `Running · tick 0/${run.timesteps}`});
      this.#showFrame(runViewerUrl(this.runOrigin, run.run_id));
      try { await this.api.setDisplayedRun(run.run_id); } catch (error) {
        if (generation === this.generation) this.#set({...this.state, message: `Running · history pin unavailable · ${error.message}`});
      }
      if (generation !== this.generation) return null;
      this.#schedulePoll(generation, 0);
      return run;
    } catch (error) {
      if (generation === this.generation) this.#set({phase: "error", run: null, status: null, message: error.message || "Run could not start."});
      throw error;
    }
  }

  async cancel() {
    if (!this.state.run || !["running", "cancelling"].includes(this.state.phase)) return;
    this.#set({...this.state, phase: "cancelling", message: "Stopping… waiting for the engine."});
    try { this.#acceptStatus(await this.api.cancelRun(this.state.run.run_id)); }
    catch (error) { this.#set({...this.state, message: error.message || "Stop request failed."}); }
  }

  async showEditor() {
    try { if (this.state.run) await this.api.setDisplayedRun(null); }
    finally { this.#showFrame(null); }
  }

  async reopen() {
    if (!this.state.run) return;
    try { await this.api.setDisplayedRun(this.state.run.run_id); }
    catch (error) {
      if (error.response?.status === 404 || error.status === 404) {
        this.#set({...this.state, phase: "expired", message: "This run expired. Press Play to build it again."});
        this.#showFrame(null);
        return;
      }
      throw error;
    }
    const canonical = TERMINAL_STATES.has(this.state.phase);
    this.#showFrame(runViewerUrl(this.runOrigin, this.state.run.run_id, {canonical}));
  }

  async openCanonical() {
    if (!this.state.run || this.state.phase !== "done") return;
    await this.api.setDisplayedRun(this.state.run.run_id);
    this.#showFrame(runViewerUrl(this.runOrigin, this.state.run.run_id, {canonical: true}));
  }

  #schedulePoll(generation, delay = this.pollInterval) {
    this.#cancelPoll();
    this.timer = this.timers.setTimeout(() => void this.#poll(generation), delay);
  }

  async #poll(generation) {
    this.timer = null;
    const runId = this.state.run?.run_id;
    if (!runId || generation !== this.generation) return;
    try {
      const status = await this.api.getRun(runId);
      if (generation !== this.generation) return;
      this.#acceptStatus(status);
      if (!TERMINAL_STATES.has(this.state.phase)) this.#schedulePoll(generation);
    } catch (error) {
      if (generation !== this.generation) return;
      if (error.response?.status === 404 || error.status === 404) {
        this.#set({...this.state, phase: "expired", message: "This run expired. Press Play to build it again."});
      } else {
        this.#set({...this.state, message: `Status unavailable · ${error.message}`});
        this.#schedulePoll(generation);
      }
    }
  }

  #acceptStatus(status) {
    const phase = this.state.phase === "cancelling" && status.state === "running" ? "cancelling" : status.state;
    const messages = {
      running: `Running · tick ${status.tick}/${status.total}`,
      cancelling: "Stopping… waiting for the engine.",
      done: `Completed · ${status.tick}/${status.total} ticks`,
      cancelled: `Cancelled after tick ${status.tick}/${status.total}`,
      error: status.error || "Run failed.",
    };
    const transport = status.transport_error ? " · live preview unavailable; canonical replay is unaffected" : "";
    this.#set({...this.state, phase, status, message: `${messages[phase] || this.state.message}${transport}`});
  }

  #showFrame(url) { for (const listener of this.frameListeners) listener(url); }
  #set(state) { this.state = state; for (const listener of this.listeners) listener(this.snapshot()); }
  #cancelPoll() { if (this.timer !== null) this.timers.clearTimeout(this.timer); this.timer = null; }
}
