# Optimizer-Seed Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full onboarding path from the Observatory sugarscape page to a working submitted policy: human docs + reproducibility in coworld-sugarscape, a new public `Metta-AI/sugarscape-mixin` conforming to the optimizer-seed contract, and metta-side participation-guide/page pointers.

**Architecture:** Three phases in dependency order — game repo first (docs the mixin links to, pinned SHA), then the mixin (agent-facing), then metta pointers (need the mixin URL). A final end-to-end rehearsal validates the whole path.

**Tech Stack:** Python 3.13 / uv (game repo), Markdown + bash (mixin, per optimizer-seed contract), Python + TypeScript/React (metta app_backend + softmax.com).

**Spec:** `docs/designs/2026-08-18-optimizer-seed-onboarding.md` (this repo). The spec is the authority on content; this plan sequences and pins the mechanics.

## Global Constraints

- League ids: solo `league_620a74a7-eb1f-4386-b386-0e7246be4eb6`, duos `league_d5b48dfe-5e08-499f-80f1-63f14720c50c`, commonwealth `league_dac00450-027a-45e6-9f6b-c9bda7ddd61d`. Coworld `cow_049e7dc0-f4b5-49f8-81df-59ea73493b6a`.
- CLI pointers always name `Metta-AI/coworld` and specifically its root `COOKBOOK.md`.
- Mixin prose is agent-terse; human tutorial content lives only in coworld-sugarscape `docs/`.
- Mixin scaffolding comes from a **fresh clone of the public `Metta-AI/optimizer-seed`** (not the possibly-stale `~/coding/optim-compare` copy, which stays read-only reference).
- `~/coding/metta` is never modified; metta work happens in a fresh clone.
- Manifest `optimizer[]` stays empty (breaks `coworld optimize` otherwise — see spec deviation note).
- Outward-facing acts (GitHub repo creation, any push, any PR) are confirmed with James first.
- Game repo tests: `.venv/bin/python -m pytest` must stay green after every task.
- The three backstage terms "binding", "gap", "lesson buffer" never appear in mixin `docs/` prose (agent-only files `MIXIN.md`/`AGENTS.md`/`SKILL.md` may use them).

---

## Phase A — coworld-sugarscape (branch `james/optimizer-seed-onboarding`)

### Task A1: Fresh-clone reproducibility (pyproject + setup docs)

**Files:**
- Create: `pyproject.toml`
- Modify: `README.md` (setup paragraph), `AGENTS.md` (setup command)

**Interfaces:**
- Produces: `uv sync`-able project; `[dependency-groups] dev` includes pytest + pytest-xdist; runtime dep `websockets==17.0.1` (matches both Dockerfiles' pin).

- [ ] Write `pyproject.toml`: name `coworld-sugarscape`, `requires-python = ">=3.13"`, `dependencies = ["websockets==17.0.1"]`, dev group `["pytest>=8", "pytest-xdist>=3"]`, `[tool.uv] package = false` (the repo is run via `PYTHONPATH=src`, not installed).
- [ ] Rehearse fresh setup in scratchpad: `git clone . <scratch>/fresh-clone && cd <scratch>/fresh-clone && uv sync && uv run --no-project python -m pytest` — wait: run as the README will document it (`uv sync; PYTHONPATH=src uv run pytest` or symlink-free equivalent). Whatever invocation the rehearsal proves is what README/AGENTS.md get. Expect full suite green (~152 tests; server socket tests may need permission — note as documented caveat if they fail in sandbox).
- [ ] Update README.md and AGENTS.md with the proven setup + test commands (keep existing `.venv/bin/python -m pytest` working note).
- [ ] Run `.venv/bin/python -m pytest` in the main checkout (unchanged behavior).
- [ ] Commit: `Add uv project metadata so a fresh clone can run the suite`.

### Task A2: Human getting-started doc

**Files:**
- Create: `docs/getting-started.md`
- Modify: `README.md` (link it prominently, near the top of the v3 section)

Content requirements (human-facing, per spec Deliverable 2.2): what the game is (one law, 1000 unattended ticks); the three leagues incl. the targeted-generation vs handcrafted-commonwealth split and that a dual-league policy branches on target kind; local loop (clone, uv sync, run an episode, `docker compose up`); the Ruleset Studio (launch command, what it is, agent chat pane); joining leagues (uv + coworld CLI block mirroring the Observatory page's commands, all three league ids); "working with a coding agent" section pointing at optimizer-seed + sugarscape-mixin and the participation guide URL; pointers to RULES.md / TARGETS.md / SCENARIOS.md / `Metta-AI/coworld` COOKBOOK.md.

- [ ] Write `docs/getting-started.md`; link from README.
- [ ] Verify every command in it against the repo (launcher module path, compose service names, league/coworld ids) — each command either run locally or checked against source.
- [ ] Commit: `Add the human getting-started guide`.

### Task A3: SugarLang tutorial

**Files:**
- Create: `docs/sugarlang-tutorial.md`
- Modify: `docs/RULES.md` (one cross-link line at top: normative reference vs tutorial), `rulesets/worked-example.json` untouched but cited.

Content requirements: reasoning path from a target to a ruleset (pick `wealth.skewed-gini-0.5`: what the target asks, which features matter, building the movement list + traits step by step, the worked-example ruleset as the destination); a second shorter commonwealth example (constitution mindset, wellness components, degeneracies pointer); budget discipline (256 nodes / depth 16 / 32 KB); how to validate (Studio or `coworld.ruleset.validate_ruleset`); Studio as the visual editor for all of this.

- [ ] Write the tutorial; every JSON fragment in it must pass `parse_ruleset`/`validate_ruleset` — validate via a throwaway scratchpad script importing `src/coworld/ruleset.py`.
- [ ] Add the RULES.md cross-link (keep RULES.md's test-enforced sections untouched; run `pytest tests/test_rules_documentation.py`).
- [ ] Run full pytest.
- [ ] Commit: `Add the SugarLang tutorial`.

### Task A4: Manifest + stale-doc fixes

**Files:**
- Modify: `coworld_manifest.json` (`game.docs.pages` + `variants[solo-ladder].description`), `docs/designs/2026-08-17-duo-ladder.md` (stale "24" note)

- [ ] Add a `scenarios` page to `game.docs.pages` (`id: "scenarios"`, `title: "Ladder scenario catalog"`, uri `https://github.com/Metta-AI/coworld-sugarscape/blob/main/docs/SCENARIOS.md`) — same shape as the existing `rules`/`targets` entries.
- [ ] Fix `solo-ladder` variant description: "24 validated scenarios" → "80 scenarios (12 base worlds × mechanic packs)". Grep the manifest for any other "24" staleness.
- [ ] Add a dated update note to `2026-08-17-duo-ladder.md` correcting "24 validated worlds" to the 80-pool (design docs are living documents; don't rewrite history, append the correction).
- [ ] Run `pytest tests/test_packaging.py` then full suite.
- [ ] Commit: `Surface SCENARIOS.md in manifest docs and fix stale 24-scenario text`.

---

## Phase B — sugarscape-mixin (new repo at `~/coding/coworlds/sugarscape-mixin`)

### Task B1: Scaffold from the live template

- [ ] `git clone https://github.com/Metta-AI/optimizer-seed <scratch>/optimizer-seed` (fresh; record its HEAD SHA in the mixin's initial commit message).
- [ ] `mkdir ~/coding/coworlds/sugarscape-mixin && cp -R <scratch>/optimizer-seed/games/_template/. ~/coding/coworlds/sugarscape-mixin/` then `git init`, add `.gitignore` (`__pycache__/`, `.pytest_cache/`, `.DS_Store`, `*.pyc` — drift pitfall #11).
- [ ] `diff -rq` against the template = only intended-to-fill files; leave `{{MIXIN_REPO_URL}}`/`{{COMMIT}}`/`{{DATE}}` placeholders untouched everywhere.
- [ ] Initial commit: `Scaffold from optimizer-seed games/_template at <sha>`.

### Task B2: MIXIN.md

- [ ] Fill Identity (game, coworld id + manifest repo, all three league ids, source of truth = `Metta-AI/coworld-sugarscape` public, RULES.md test-enforced), skill manifest (five bindings **filled**), Additional Skills (`ruleset-studio`), "what else" (docs list, `players/baseline`, `tools/build.sh`), local-oracle doctrine note, `eval_defaults.yaml` row resolved as "not shipped; defaults in prose in eval-design".
- [ ] Diff section headers against the template's (`diff <(grep '^#' MIXIN.md) <(grep '^#' _template/MIXIN.md)` — same skeleton).
- [ ] Commit.

### Task B3: Lab AGENTS.md + META.md + working files

- [ ] AGENTS.md per spec (agent-terse; the six template sections; hard fork rule maximize→constitution / distribution→generate; qualifier mechanics; COOKBOOK.md pointer; loop table with interview/Build/Verify rows).
- [ ] META.md: dated, "pre-campaign analysis from docs and standings, not earned knowledge", freshness window 14 days justified by release-driven field movement; standings snapshot from `coworld results <solo league id>` if reachable, else marked unobserved.
- [ ] WORKING_CONTEXT.md / TENTATIVE_LESSONS.md / best_practices.md / closed_levers.md: template state with lab identity filled in.
- [ ] Commit.

### Task B4: The five bindings

**Files:** `skills/{ab,survey,replay-inspection,eval-design,diagnosis}/SKILL.md`, frontmatter `name: sugarscape-<binding>`, `binding: <binding>`.

- [ ] Before writing `ab`: measure real N-floors — scratchpad script over the game repo's `run_episode` (3 scenarios × 10 seeds, per-seed score SD for one target) and put the measured numbers + the measurement recipe in the SKILL.md.
- [ ] Write the five files per spec content requirements (paired local sweeps admissible + hosted confirmation; scenario×score matrix; rule-attribution framing + rule-fire trace named as build-first instrument; three-tier oracle ladder + `scenario_pool[seed % 80]`; generation-shaped failure vocabulary + cheapest-first triage). Version-skew section in `eval-design` (pitfall #10).
- [ ] Cross-check each against its core-skill counterpart in the fresh seed clone (specializes, never contradicts, no game conditionals pushed upstream).
- [ ] Commit per skill or as one reviewed unit.

### Task B5: ruleset-studio skill

- [ ] `skills/ruleset-studio/SKILL.md` (no `binding:` key — additional skill): default-surface rule gated on recorded preference; launch runbook (game repo checkout prerequisite, `.venv/bin/python -m tools.ruleset_studio`, metta checkout for link-server, printed `link-bridge.mjs watch`, re-arm per reply) all marked handle-silently; sha consent gate; `/api/run` documented per the game repo's main at implementation time (if studio-play hasn't landed, describe local `run_episode` scoring instead and leave a dated TODO-free "as of" note).
- [ ] Commit.

### Task B6: Mixin docs

- [ ] `docs/game.md`, `docs/leagues.md`, `docs/observatory.md`, `docs/strategy.md`, `docs/first-session.md` per spec content requirements (agent-oriented; observatory.md carries the CLI/API table incl. per-agent player-logs raw route and rivals-403; first-session.md is substitutions-to-the-seed-arc incl. teach-before-ask league fork and the anti-runaway rule).
- [ ] Grep docs/ for the three backstage terms — zero hits.
- [ ] Commit.

### Task B7: players/baseline + tools/build.sh

- [ ] `players/baseline/`: `player.py` connector (vendored from game repo baseline, restructured: `library/` of per-target-family ruleset JSON files exported from `choose_ruleset` logic + commonwealth constitution file + dispatch that loads by target), `Dockerfile` (amd64, `websockets==17.0.1`, `PYTHONHASHSEED=0`), `README.md` (measured local scores via a pool spot-check; version-log rule repeated), `VERSION_LOG.md` (vendored-provenance row citing game repo SHA; rows record `ruleset_sha256`), keep `_VERSION_LOG_template.md`.
- [ ] Every library ruleset validates against the game repo's `validate_ruleset`; constitution file byte-identical to what the game repo's baseline emits for `wellness.max`.
- [ ] `tools/build.sh [--ref <game-ref>] [--tag <image-tag>]`: clones coworld-sugarscape at pinned SHA (Phase-A tip; rationale inline), overlays the mixin player, `docker build --platform linux/amd64`, prints tag.
- [ ] Smoke: `tools/build.sh` builds; run the image against the game repo's `docker compose up` game service, confirm ack + non-null submitted ruleset in results.
- [ ] Commit.

### Task B8: Conformance + publish gate

- [ ] Final `diff -rq` vs template; pitfall checklist pass (all 13 items from the spec); fresh-eyes read of MIXIN.md.
- [ ] **CONFIRM WITH JAMES**, then `gh repo create Metta-AI/sugarscape-mixin --public`, push, verify `tools/add_game.sh https://github.com/Metta-AI/sugarscape-mixin` works from the fresh seed clone (provenance stamped once, no duplicate section).

---

## Phase C — metta-side (fresh clone, jamesboggs branch)

### Task C1: Working clone

- [ ] `git clone --filter=blob:none ~/coding/metta <scratch>/metta-onboarding && cd $_ && git remote set-url origin git@github.com:Metta-AI/metta.git && git fetch origin main && git checkout -b james/sugarscape-participation-guide origin/main`.

### Task C2: Participation guide branch

**Files:**
- Modify: `app_backend/src/metta/app_backend/v2/participation_guide.py` (add `_build_sugarscape_participation_guide` + dispatch on `coworld_ref == "sugarscape"` beside the crewrift branch)
- Modify: `app_backend/tests/test_participation_guide.py` (sugarscape cases beside the crewrift ones)

Content: agent-as-guide framing; clone `Metta-AI/optimizer-seed` → `tools/add_game.sh https://github.com/Metta-AI/sugarscape-mixin` → seed getting-started with the lab's `first-session.md` overlay; "uploading is routine; league submission is the gate"; `Metta-AI/coworld` + COOKBOOK.md pointer; the game repo's `docs/getting-started.md` as the human path; league-parameterized so all three sugarscape leagues render correctly.

- [ ] Write the failing tests first (assert sugarscape guide contains the mixin URL, the seed URL, COOKBOOK.md pointer, and does NOT render the generic build-your-player section), run to see them fail, implement, run app_backend's test command per its README/pyproject (use the repo's real toolchain; if the env needs Nix, use `nix develop` — do not bypass).
- [ ] Commit in metta style (read `git log` first).

### Task C3: Sugarscape page Getting Started

**Files:**
- Modify: `web/softmax.com/src/app/sugarscape/page.tsx` (Getting Started section + `RESOURCE_LINKS`)

- [ ] Replace "Under construction" copy: agent path primary (participation guide link unchanged), manual CLI block retained as the no-agent path; `RESOURCE_LINKS` gains `sugarscape-mixin` and `Metta-AI/coworld` COOKBOOK. Follow the page's existing copy voice; scoring copy still avoids exact formulas.
- [ ] Run the web checks the repo defines (lint/typecheck for `web/softmax.com`).
- [ ] Commit. **CONFIRM WITH JAMES** before push/PR (human-centered PR description; Graphite stack if applicable to metta flow).

---

## Phase D — End-to-end rehearsal

- [ ] Fresh `optimizer-seed` clone in scratchpad → `add_game.sh` the published mixin → verify install checklist output, provenance single-stamped, lab files present.
- [ ] Walk `docs/first-session.md` as the agent would: launch Studio from a game-repo checkout, run one local sweep command, confirm every referenced file/command exists.
- [ ] Report results + codebase-friction rating to James; hand off the pending confirmations (any not yet given).

## Self-review notes

- Spec coverage: A1–A4 = Deliverable 2; B1–B8 = Deliverable 1 (interview lives inside B3's AGENTS.md loop table + B6's first-session.md — no separate task needed); C1–C3 = Deliverable 3; D = Validation section. Decision log covered by spec.
- The spec's "hosted confirmation minimum" lands in B4 `ab`; the consent gate in B5; META.md honesty in B3.
- Sequencing honored: A before B (build.sh pins A's tip), B8 before C2 (guide names a live URL).
