# Ruleset Studio — visual SugarLang editor with a live agent bridge

**Status:** proposal (2026-08-18) — nothing implemented; iterating on design
**Date:** 2026-08-18
**Owner:** James Boggs

## Problem

Designing a SugarLang ruleset today means hand-writing nested JSON
s-expressions (`docs/RULES.md`), eyeballing the budgets (256 nodes, depth
16, 32 KiB), and round-tripping through a coding agent for every idea.
The DSL is small and tree-shaped — four scalar trait overrides plus an
ordered movement decision list — which makes it a near-perfect fit for a
Scratch-style block editor: expressions are pure trees, every value is a
number, and there is no control flow to model.

We want a local web tool a coding agent can open in the user's browser
that lets a person *see* and *drag* a ruleset into shape, while keeping
the agent one keystroke away for judgment calls ("why does this rule
never fire?", "tighten this toward the pareto target").

## Goals

- **Visual editor** in the Scratch idiom (nested snap-together blocks,
  not wire-graph nodes) covering 100% of the SugarLang v1 grammar.
- **Trait sliders** for the four traits (`aggression`, `trade`,
  `lending`, `fertility`), range-aware via `trait_ranges`, each
  individually toggleable (traits are optional — an un-overridden trait
  keeps the DTL-generated factor).
- **New / load / save** of rulesets as plain SugarLang JSON files —
  submission-ready bytes, no sidecar format.
- **Always-live feedback**: generated JSON preview, budget meters, and
  errors from the *real* repo validator as you edit.
- **Agent chat panel** wired to the launching coding-agent session, where the
  agent can both answer in prose and *patch the blocks on the canvas*.
- Openable by any coding agent working in this repo via one documented
  command.

## Non-goals

- Not a hosted/multi-user service. Localhost, one user, one session.
- No SugarLang grammar changes. The editor is a client of `docs/RULES.md`
  as it stands; grammar evolution updates the block set, not vice versa.
- No replacement for the replay viewer. Watching episodes stays there.
- Phase 1 does not run episodes (see Phase 2).

## Prior art consulted (research-before-building)

- **[Blockly](https://developers.google.com/blockly)** (Apache-2.0, npm
  `blockly`) — the industry-standard embeddable block editor; stewardship
  moved from Google to the **Raspberry Pi Foundation in Nov 2025** and it
  remains actively maintained. Custom blocks are defined in JSON, block
  workspaces serialize to JSON, value connections carry type checks, and
  custom generators walk the block tree — everything this tool needs is
  first-class.
- **scratch-blocks** (Scratch Foundation's Blockly fork) — the literal
  Scratch look, but heavyweight, coupled to scratch-vm, and not
  maintained as an embeddable library. Rejected.
- **React Flow / Rete.js / LiteGraph** — wire-graph ("node-and-cable")
  editors. Wrong idiom: SugarLang expressions are strictly nested trees,
  and the ask was explicitly Scratch-style nesting. Rejected.
- **Hand-rolled editor** — would re-implement drag/snap/serialize/undo
  that Blockly has spent a decade hardening. Rejected.
- **`ux.surface`** (metta `agent-plugins/ux`) — the in-house
  CLI↔browser↔live-session framework: zero-dep Node server, served
  `link-client.js` contract (`ask`/`applyPatch`/`submit`/heartbeat
  lifecycle), long-poll bridge answered by the launching agent session,
  predraft cache. This is exactly the chat-panel substrate; no external
  model, no credentials, auto-cleanup when the tab closes.

**Decision: Blockly for the editor, ux.surface plumbing for the agent
link, a small stdlib-Python API server (patterned on
`tools/serve_replay_viewer.py`) for mechanical operations.**

## Architecture

Three processes, one page:

```
┌───────────────────────────────  browser  ──────────────────────────────┐
│  Ruleset Studio (static app: Blockly canvas · sliders · JSON panel ·   │
│  chat panel)                                                          │
└──────┬──────────────────────────────────────────────┬──────────────────┘
       │ fetch (localhost, CORS)                      │ /link-client.js + bridge
┌──────▼──────────────────────┐          ┌────────────▼──────────────────┐
│ studio API server (Python,  │          │ ux.surface link-server (Node) │
│ stdlib http.server)         │          │ serves the static app + chat  │
│ list/load/save/validate     │          │ bridge + patch channel        │
│ imports src/coworld/        │          └────────────┬──────────────────┘
│ ruleset.validate_ruleset    │                       │ long-poll
└─────────────────────────────┘          ┌────────────▼──────────────────┐
                                         │ the launching agent session   │
                                         │ (bridge `watch` loop)         │
                                         └───────────────────────────────┘
```

**Division of labor — mechanical vs. judgment.** Everything
deterministic and latency-sensitive (file I/O, validation) goes to the
Python API server so it is instant and uses the *authoritative*
validator by import — no JS re-implementation to drift. Everything
requiring judgment (chat, "improve this ruleset") goes over the
ux.surface bridge to the live agent session. The agent is never in the
critical path of ordinary editing.

### Repo layout

```
ruleset-studio/
  src/                  # index.html, studio.js, blocks.js, style.css
  vendor/blockly/       # pinned blockly.min.js + license (vendored, no CDN)
  server.py             # studio API server (stdlib only)
rulesets/               # saved SugarLang JSON files (the load/save dir)
tools/ruleset_studio.py # launcher: starts both servers, prints agent runbook
docs/designs/2026-08-18-ruleset-studio.md   # this document
```

Vendoring matches the replay-viewer convention (no CDN, no build
framework). No bundler: `blocks.js`/`studio.js` are plain ES modules;
Blockly ships a browser UMD build.

### Launch story (how an agent opens it)

`python -m tools.ruleset_studio` starts the studio API server and the
ux.surface link-server (`LINK_APP_DIR=ruleset-studio/src`), which
auto-opens the user's browser. The launcher prints the exact
`link-bridge.mjs watch` runbook so the agent parks a watch loop and
answers chat. A short project skill (`.claude/skills/` entry, phase 1
deliverable) captures this so "open the ruleset studio" works in any
future session. Degraded mode is explicit: if no bridge watch is
running, the chat panel shows "agent not connected" (from
`link.onStatus`) while editing/validation/save remain fully functional —
the studio API server never depends on the agent.

## The block language (SugarLang ⇄ blocks, 1:1)

One block per grammar production; the mapping is total in both
directions, so **any** valid ruleset file loads into blocks and any
canvas compiles to valid-shaped JSON.

- **`movement` container** — a statement stack of *rule* blocks,
  evaluated top-to-bottom; drag to reorder.
- **rule block** — `when ⟨condition⟩ score ⟨expr⟩` and the variant
  `otherwise score ⟨expr⟩` (no `if`). Editor lint enforces the grammar's
  ordering rule: exactly one `otherwise` rule, last.
- **value blocks** (all connections typed Number): arithmetic
  `+ − × ÷ min max` (variadic, with a "+" affordance to add operands),
  `abs neg pow`, comparisons `< ≤ > ≥ = ≠`, logic `and or not`,
  `if ⟨c⟩ then ⟨e⟩ else ⟨e⟩`, and a numeric literal field.
- **feature blocks** — three dropdown getters (agent / cell / world)
  listing the exact `docs/RULES.md` vocabulary, with the doc's meaning
  string as hover help (e.g. `cell.welfare` explains it is DTL's
  pre-SugarLang welfare).
- **compiler / decompiler** — `blocks.js` walks the workspace to emit
  SugarLang JSON and, inversely, builds blocks from parsed JSON with
  auto-layout. Saved files are **pure SugarLang** — block positions are
  cosmetic and regenerated on load, so files stay hand- and
  agent-editable and directly submittable.

Traits deliberately live *outside* the canvas as sliders (better UX for
four scalars, and it visually separates traits from movement policy).
Slider ranges come from the active `trait_ranges` (default:
`config.json`'s), shown with the clamping semantics ("values clamp into
range at spawn"). An un-overridden trait shows the *value DTL would
generate* in the current context (the scenario's `agent*Factor` range;
DTL's internal default is `[0, 0]`), muted — not a vague "DTL default"
label. *(Vocabulary: the UI says **traits** everywhere,
matching the repo (`trait_ranges`, RULES.md "Traits") — confirmed by
James 2026-08-18.)*

## Liveness (what the page does before you ask it anything)

Per ux.surface's dead-form law, the page is a live instrument, not a
form:

1. **On open**: loads the most recent ruleset in `rulesets/` (or a
   starter template) and renders it as blocks. The compiled-JSON view
   lives in a disclosure collapsed by default (2026-08-18 iteration:
   the blocks are the primary representation; the JSON is one click
   away, not permanent screen real estate).
2. **On every edit** (debounced ~300 ms): recompiles to JSON; updates
   budget meters — node count /256, max depth /16, payload bytes /32768
   — computed client-side from the *spec'd formulas* in RULES.md;
   POSTs to `/api/validate` and renders real validator errors with their
   JSON paths mapped back to the offending block (click error → flash
   block).
3. **Structural lints inline**: missing final unconditional rule,
   unreachable rules after `otherwise`, trait value outside range.

## The agent chat (ux.surface bridge)

The top of the right-hand column (2026-08-18 iteration: docked there
permanently rather than a separate toggleable drawer — it sits above
the budget meters and validation, so one column carries all
agent/status content and the canvas keeps the width). A message log,
an input box, and a bridge-status pill (`link.onStatus`). The Agent,
Compiled-ruleset, and Budgets panes are individually collapsible
disclosures; a collapsed Budgets header keeps a one-line
`nodes/256 · depth · bytes` summary so the meters never disappear
entirely. Expanded panes flex to fill the column's height — the JSON
view grows into whatever is left (all of it when chat is collapsed;
a 1:2 minority share against an open chat) — so the column never
strands empty space while any pane is open.

- **User → agent**: each message goes out as
  `link.ask(text, null, context)` where `context` carries the current
  compiled ruleset, active file path, validation state, and the
  selected block's subtree — the agent sees exactly what the user sees.
- **Agent → canvas**: replies may carry a patch
  `{set: {ruleset: <SugarLang JSON>, note: "..."}}`. The page's
  `window.linkApplyPatch` decompiles it onto the canvas as a normal
  undoable edit, with a "changed by agent" toast. This is the headline
  feature: *"make the low-TTL rule prefer spice"* → the blocks visibly
  rearrange.
- **Session side**: the launcher runbook has the agent keep
  `link-bridge.mjs watch` parked and re-armed. Saving is **not** a
  bridge submit — save is a repeated mechanical op via the API server;
  the ux.surface submit/`done` lifecycle is unused (a legitimate
  no-submit shape per the skill).

## Studio API server contract

`ruleset-studio/server.py`, stdlib `http.server` like
`tools/serve_replay_viewer.py`, localhost only,
`Access-Control-Allow-Origin` pinned to the link-server origin.

| Route | Method | Behavior |
|---|---|---|
| `/api/rulesets` | GET | List `rulesets/*.json` with mtime + validity summary |
| `/api/rulesets/{name}` | GET | Raw SugarLang JSON |
| `/api/rulesets/{name}` | PUT | Validate, then atomic write (tmp+rename); never writes invalid JSON silently — invalid saves require `?force=1` and return the errors either way |
| `/api/validate` | POST | Body = candidate ruleset; returns `validate_ruleset` errors with JSON paths |
| `/api/context` | GET | `trait_ranges` + scenario list (from `config.json` / `coworld_manifest.json`) for slider ranges and the scenario picker |

Filenames are validated against a `[A-Za-z0-9._-]+\.json` allowlist and
resolved strictly inside `rulesets/` (trust boundary: browser input).

## Phase 2 (explicitly deferred)

- **Test-run scoring**: an `/api/run` that executes a short local
  episode (chosen scenario + seed) with the working ruleset and returns
  score + measured-vs-target histogram overlay. This closes the
  design→score loop and is the biggest payoff, but it drags in episode
  orchestration, progress streaming, and dataviz — worth its own design
  pass once the editor exists.
- **Duo-ladder awareness** (second seat / opponent context).
- **Workspace niceties**: block search palette, keyboard-first editing.

## Visual design

Ink & Print per the ux.setup house methodology (read
`agent-plugins/default/skills/ux.ify/references/{principles,design-system}.md`
before implementation): warm near-black on near-white, typography-led
hierarchy, no decorative cards. Blockly gets a custom theme (category
colors drawn from the house palette, house typeface for block labels) so
the canvas doesn't read as stock-Google. Post-build conformance pass via
`/ux.ify` with screenshots, per the standing rule.

## Validation & testing

- **Round-trip property tests** (Node, patterned on
  `tools/test_viewer.mjs`): for a corpus of rulesets — every doc
  example, the 24 scenario-pool probes' rulesets if available, and
  generated trees — `decompile → compile` is byte-identical modulo key
  order, and compiled output passes `validate_ruleset`.
- **API server pytest**: routes, path-traversal rejection, atomic-save
  and `force` semantics, validator parity.
- **Budget-meter parity test**: client-side node/depth/byte counters
  agree with the Python validator's counts on the corpus.
- **Look-by-running**: drive the live page (Playwright tools),
  screenshot open/edit/error/chat-patch states — required by both
  ux.surface and the house UI rule.

## Risks

- **Blockly variadic operators** need `mutator` blocks (the "+ add
  operand" gear); this is standard Blockly but the fiddliest part of the
  block set. Fallback: fix arity at 2 and let users nest — grammar-legal,
  slightly noisier canvases.
- **Two servers, two ports** adds a CORS seam and a launcher that must
  supervise both. Accepted for validator authority + instant mechanical
  ops; the launcher owns lifecycle (child processes, shared shutdown).
- **Bridge latency/absence**: chat depends on a watching session.
  Mitigated by the explicit degraded mode and status pill.
- **ux.surface API drift**: the skill is versioned (0.6.x) and evolving;
  the studio uses only the stable served contract (`/link-client.js`,
  bridge CLI). The launcher pins the metta path and fails loudly if the
  contract file is missing.

## Open questions (for iteration)

1. **`rulesets/` location** — repo-root `rulesets/` (proposed) vs
   `build/rulesets/` (gitignored)? Proposal assumes rulesets are worth
   committing/sharing.
2. **Phase 2 in or out of the first build** — is the editor useful
   enough without test-run scoring, or is `/api/run` the actual MVP?
3. **Scenario picker scope** — phase 1 uses scenarios only to source
   `trait_ranges`/target names for context; is that enough, or should
   the target histogram render in-studio from day one (cheap: static
   render from `targets/*.json`)?
4. **Launcher home** — `tools/ruleset_studio.py` + a project skill, or
   should this eventually be a `ux.*` skill in metta so other coworlds
   can reuse the pattern?
