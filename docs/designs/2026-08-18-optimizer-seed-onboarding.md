# Optimizer-seed onboarding: sugarscape-mixin and getting-started infrastructure

**Status:** Approved 2026-08-18 (James). Implementation in progress.

## Problem and goal

The Observatory's sugarscape page points new users at this repo, but there is
no onboarding path: no getting-started doc, no agent-facing skills, and the
platform's generic participation guide knows nothing about SugarLang, the
three leagues, or the Ruleset Studio. A new user with a coding agent should be
able to go from the Observatory page to a working, submitted policy in one
guided session.

The fix is three coordinated deliverables:

1. **`Metta-AI/sugarscape-mixin`** (new public repo) — an optimizer-seed
   mixin conforming to the seed's `games/_template/` contract, giving a
   seed-based coding agent everything game-specific: bindings, a Ruleset
   Studio skill, a starter policy scaffold, agent-oriented docs, and an
   extended first-session interview.
2. **`coworld-sugarscape` additions** — human-facing getting-started and
   SugarLang tutorial docs, fresh-clone reproducibility, and manifest fixes.
3. **Metta-side pointers** (separate worktree; the `~/coding/metta` checkout
   is never modified) — a sugarscape branch in the participation guide and an
   updated Getting Started section on the sugarscape page.

## Background: the optimizer-seed ecosystem

The seed lives at `Metta-AI/optimizer-seed` (**public** as of 2026-08-18).
A user clones it once; it becomes their optimizer agent's constitution
(`AGENTS.md`), memory files, 13 core game-agnostic skills, and harness
wiring. Per-game knowledge arrives via mixin repos installed with
`tools/add_game.sh <mixin-repo-url>`, which clones the mixin repo wholesale
into `games/<slug>/` and stamps provenance. Six mixins exist
(`heartleaf-mixin` is the minimal reference; `paintbot-mixin` the flagship);
`sugarscape-mixin` will be the seventh. Local reference checkouts:
`~/coding/optim-compare/seeds/`.

Contract essentials (from `games/_template/`):

- `MIXIN.md` — identity (game, coworld, league ids, source of truth),
  untouched `{{MIXIN_REPO_URL}}`/`{{COMMIT}}`/`{{DATE}}` placeholders for the
  installer, a skill manifest declaring each required binding **filled** or a
  **gap**, an Additional Skills table ("an unlisted skill is an
  undiscoverable one"), and a "what else this mixin provides" section.
- Five required binding skills: `ab`, `survey`, `replay-inspection`,
  `eval-design`, `diagnosis` — each specializes a core seed skill with
  game knowledge. Core skills never contain game conditionals; mixins never
  modify core files.
- Lab `AGENTS.md` (loaded on top of the seed's), `META.md` (dated field
  snapshot), working-memory files, `players/` with a version-logged reference
  policy, `tools/build.sh`, `experiments/_template.md`.

### Why sugarscape inverts the content conventions

Every existing mixin was written for real-time multi-agent games where local
scoring is a lying proxy and rivals are unrunnable. Sugarscape:

- Solo-ladder and commonwealth episodes seat **one policy, no opponents**;
  score is a pure function of ruleset × scenario × seed.
- The **actual scoring function runs locally**: in-process `run_episode()`
  scores a full 1000-tick episode in ~5 s on the pinned interpreter,
  reproducibly (`PYTHONHASHSEED=0`).
- The policy makes **one decision** (emit a ruleset), then the world runs
  without player I/O.

**Approved doctrine decision (James, 2026-08-18):** the mixin's `ab` and
`eval-design` bindings declare local paired sweeps over the 80-scenario pool
**admissible verdict evidence** for solo/commonwealth score claims at the
pinned ref, with one hosted confirmation required before any league submit.
This deliberately stretches the seed's non-negotiable #1 ("the live field is
the only oracle" — a doctrine born where local scoring lied); MIXIN.md carries
a one-line note flagging the tension. Live-only remains: version skew against
the deployed build, duo opponents, league aggregation/EWMA, and the
commonwealth qualifier.

## Deliverable 1: `sugarscape-mixin`

Developed at `~/coding/coworlds/sugarscape-mixin`; pushed to a new **public**
`Metta-AI/sugarscape-mixin` (creation confirmed with James at that step).
Authored by copying `games/_template/` verbatim, then filling — and
`diff -rq` against the template before shipping (contract drift is the
ecosystem's known failure mode; there is no propagation mechanism).

**Audience rule (James):** everything in the mixin is written for a coding
agent — clear, succinct, scannable; contracts, commands, decision rules,
failure vocabularies. No narrative polish. Human-facing tutorial content
lives in `coworld-sugarscape/docs/` and the mixin links to it when a human
should be sent somewhere.

### MIXIN.md

- Identity: Sugarscape v3; coworld `cow_049e7dc0-f4b5-49f8-81df-59ea73493b6a`,
  manifest in `Metta-AI/coworld-sugarscape` (public — usable as source of
  truth). Leagues:
  - Solo (targeted generation): `league_620a74a7-eb1f-4386-b386-0e7246be4eb6`
  - Duos (targeted generation): `league_d5b48dfe-5e08-499f-80f1-63f14720c50c`
  - Commonwealth (handcrafted): `league_dac00450-027a-45e6-9f6b-c9bda7ddd61d`
- All five bindings declared filled. Additional Skills: `ruleset-studio`.
- `eval_defaults.yaml` row resolved explicitly (not shipped; prose in
  `eval-design` — the de facto ecosystem standard).
- One-line local-oracle doctrine note (see above).

### Lab AGENTS.md (agent-terse)

- Game in one paragraph: one declarative SugarLang law, 1000 unattended
  ticks. Never framed as real-time control.
- Scoring and what actually ranks: per-league scoring
  (`w1-hyperbolic/1` distribution match for solo/duo; `wellness-sum/1`
  maximize for commonwealth), EWMA aggregation, and the behavioral fork as a
  hard rule: **target kind `maximize` → emit the fixed constitution;
  `distribution` → generate conditioned on world + target.**
- Platform specifics: commonwealth qualifier (3 two-seat self-play episodes,
  `rulesets_identical == true` on every one; a nondeterministic generator
  passes upload and dies at the gate), `players_per_user: 1`, linux/amd64
  images only, `PYTHONHASHSEED=0` reproducibility contract.
- Mechanics ground truth: `Metta-AI/coworld-sugarscape` docs (RULES.md is
  test-enforced against the implementation), with a version-skew caveat.
- CLI pointers: `Metta-AI/coworld` (public), specifically `COOKBOOK.md` as
  the first stop for every `coworld` CLI/API task.
- Loop-specialization table: Understand row mandates the extended interview
  (below); Build row redirects the seed's real-time policy patterns to
  "how does the generator produce a valid ruleset inside the submission
  window"; Verify row: always pre-score locally before upload — it's free.

### The five bindings

- **`ab`** — metrics per league: `w1-hyperbolic/1` score plus raw W1 as
  mechanism evidence; commonwealth `wellness-sum/1` decomposed into survivor
  count × mean window wellness (population is the dominant lever).
  Decompositions: per-scenario (`scenario_index`), per-target-family,
  per-mechanic-pack, per-league — a pooled ladder score hides
  "combat-pack scenarios score 0.2". Taint: `submitted:false`,
  `empty_measurement:true`, infra failures; a low score on a hard scenario is
  never taint. Local paired comparisons (same scenarios, same seeds, both
  arms) are the workhorse; N-floors **measured** during authoring from
  per-seed score SD, not copied as provisional numbers. Hosted-confirmation
  minimum before submit stated explicitly.
- **`survey`** — a batch overview is a scenario × score matrix (score, raw
  W1, extinction/empty-measurement flags, endpoint population); "interesting"
  = extinction, empty measurement, score cliffs concentrated on one pack, a
  duo episode where the other seat visibly reshaped the world, a commonwealth
  run that found or fumbled a documented degeneracy.
- **`replay-inspection`** — reframed gap: replay = consequence trace of the
  constitution; point of view = the observation conditioned on + the ruleset
  emitted; diagnosis lives between the author's model of the world and the
  world. Centers rule attribution: "rule exists ≠ rule ever matched." Names
  the rule-fire trace as a build-first lab instrument. Shared clock = tick;
  version coupling = pinned interpreter + `PYTHONHASHSEED=0`.
- **`eval-design`** — the three-tier oracle ladder: (1) local sweep, full
  80-scenario pool × k seeds via `run_episode()` in minutes; (2) hosted
  smoke for plumbing + version skew; (3) league for ranking, EWMA, and the
  qualifier. Pool-selection mechanics documented
  (`scenario_pool[seed % 80]`; players never see seed or pool at episode
  time). Explicitly disclaims the seed's slow-batch pacing guidance.
- **`diagnosis`** — generation-shaped failure vocabulary: null-ruleset,
  validation-reject (256 nodes / depth 16 / 32 KB), extinction,
  empty-measurement, wrong-bin mass, pack-blindness, constitution drift
  (commonwealth DQ), degeneracy misfire. Cheapest-first triage from results
  scalars.

### `skills/ruleset-studio/` (additional skill)

- The Studio is the **default human-facing surface**: for any session where
  the user is shaping a ruleset — commonwealth hand-crafting especially —
  launch it and hand the user the URL unprompted, gated on their recorded
  studio-vs-terminal preference.
- Operational facts as agent instructions: launch
  (`.venv/bin/python -m tools.ruleset_studio` in the game repo checkout),
  the printed `link-bridge.mjs watch` command, one-reply watch re-armed after
  every reply, metta checkout prerequisite. All marked **handle silently** —
  never narrate bridge mechanics to the user.
- Consent gate (paintbot-campaign precedent): the submit decision record
  names the canonical `ruleset_sha256` the user approved on canvas; the agent
  never submits a constitution whose sha the user hasn't seen.
- Documents `/api/run` (press Play → live scored episode, baseline in other
  seats) as it lands on the game repo's main.

### `players/baseline/` (starter scaffold; approved bar: baseline strength)

One policy, majority naming convention. Thin connector (read observation →
dispatch → submit → exit) reusing the game repo's target-aware dispatch
logic, restructured for editability: a `library/` of rulesets keyed by target
family, a generic fallback, and the commonwealth branch emitting a
byte-canonical constitution file (no RNG, no generation-time
nondeterminism). README states measured local scores and repeats the
version-log rule at point of use; real `VERSION_LOG.md` with a
vendored-provenance row; rows record the `ruleset_sha256` of what changed.
`_VERSION_LOG_template.md` kept. `tools/build.sh [--ref] [--tag]` clones
`coworld-sugarscape` at a pinned SHA (rationale inline), builds linux/amd64.

### Mixin docs (agent-oriented)

`docs/game.md` (condensed model + pointers to the game repo's human docs),
`docs/leagues.md` (targeted-generation vs handcrafted-commonwealth split, the
policy fork, the three documented degeneracies as day-one meta),
`docs/observatory.md` (upload / XP requests / submit / results / game logs /
per-agent player-logs raw route / rivals-403 rule; `COOKBOOK.md` pointers),
`docs/strategy.md`, and `docs/first-session.md` — an overlay of
**substitutions to the seed's getting-started arc**, never a fork of it:

- Speed-stance answer reshaped: always pre-score locally (it's free and
  strictly dominates).
- The local-first oracle ladder replaces roster design.
- The Studio launch point in beats 4–5.
- The league fork, teach-before-ask: one-sentence league structure first,
  then the choice, with the recommendation attached — commonwealth-in-Studio
  for first sessions.
- Anti-runaway rule: cheap eval is a reason to show the user more
  intermediate results and forks, not to take more unsupervised steps.

### Interview (extends the seed's Calibrate step; no new convention)

The seed already probes coworlds/softmax familiarity and coding-agent
familiarity. The lab adds: (b) sugarscape familiarity, (d) studio vs
terminal preference, (e) commonwealth-first vs targeted-generation-first.
All recorded verbatim, attributed, dated in the seed's root
`user_preferences.md` under a `## Sugarscape` heading (runtime writes are
that file's purpose — not a core-file modification); operational
consequences mirrored into the lab's `WORKING_CONTEXT.md`; never re-asked.

### META.md

Dated pre-campaign snapshot, explicitly labeled "analysis from docs and
standings, not earned campaign knowledge" (nightshift precedent). Freshness
window justified: the field moves on game releases, not rival version bumps.

### Authoring pitfall checklist (contract drift defenses)

1. Copy current template files verbatim, then fill; `diff -rq` before ship.
2. Never hand-fill `{{MIXIN_REPO_URL}}`/`{{COMMIT}}`/`{{DATE}}` (installer
   double-append bug).
3. A binding is filled when knowledge sections are real; absent tooling must
   say "no tooling yet — build as a lab instrument."
4. List every extra skill in Additional Skills.
5. `players/baseline/` naming; keep `_VERSION_LOG_template.md`; real
   VERSION_LOG with vendored-provenance row.
6. `tools/build.sh [--ref] [--tag]`, amd64, pin + rationale inline; resolve
   refs to commits.
7. Resolve the `eval_defaults.yaml` row explicitly.
8. META.md dated with justified freshness window; honest about unearned
   knowledge.
9. Repeat the version-log rule at point of use (most-failed mechanical check
   in seed-lab batteries).
10. Ship a "Version skew" section (deployed build vs pinned ref, what
    local-vs-hosted divergence means) — load-bearing given the local-oracle
    decision.
11. No build debris; `.gitignore` from day one.
12. Slug hygiene: binding frontmatter `name: sugarscape-<binding>`,
    `binding: <binding>`; repo name installs as `games/sugarscape/`.
13. Backstage rule: contract vocabulary ("binding", "gap", "lesson buffer")
    never appears in user-quotable doc prose.

## Deliverable 2: `coworld-sugarscape` additions

1. **Fresh-clone reproducibility.** The repo has no `pyproject.toml` /
   `requirements.txt`; docs assume a pre-built `.venv`. Add uv-managed
   project metadata and documented setup so a fresh clone can run tests, the
   server, and the Studio. Hard prerequisite for every mixin user.
2. **Human-facing docs** (James: full content here, not stubs pointing at
   the mixin): `docs/getting-started.md` (what the game is, the three
   leagues, local episode loop, Studio, joining a league — linked from
   README) and a SugarLang tutorial (`docs/sugarlang-tutorial.md`: how to
   reason from a target to a ruleset, worked examples, cross-linked with
   RULES.md as the normative reference, `rulesets/worked-example.json`, and
   the Studio).
3. **Manifest fixes:** add SCENARIOS.md to `game.docs.pages`; fix the stale
   "24 validated scenarios" description in the `solo-ladder` variant (and
   the same staleness note in `docs/designs/2026-08-17-duo-ladder.md`).
   **Deviation from the approved design (found during planning):** the
   `optimizer[]` slot stays empty — `coworld optimize` clones
   `repository_url` and hard-asserts a `package.json` workbench
   (`metta packages/coworld/src/coworld/optimizer/runtime.py:347-350`), so
   pointing it at the mixin would break the command. The mixin pointer
   lives in the README, getting-started doc, participation guide, and the
   sugarscape page instead.

Out of scope here: the studio-play `/api/run` merge (James is landing it
separately).

## Deliverable 3: Metta-side changes

In a dedicated worktree of a separate metta clone/worktree — never the
`~/coding/metta` checkout. PR to `Metta-AI/metta` (push/PR confirmed with
James before executing).

1. **`participation_guide.py`**: `_build_sugarscape_participation_guide`
   branch on the crewrift precedent — casts the agent as the user's guide;
   flow: clone `Metta-AI/optimizer-seed` →
   `tools/add_game.sh https://github.com/Metta-AI/sugarscape-mixin` → follow
   the seed's getting-started with the lab's `first-session.md` overlay.
   States "uploading is routine; league submission is the gate." Points at
   `Metta-AI/coworld` and specifically its `COOKBOOK.md` for all `coworld`
   CLI usage. Tests beside the crewrift ones in
   `test_participation_guide.py`.
2. **`web/softmax.com/src/app/sugarscape/page.tsx`**: replace the
   "Under construction" Getting Started copy — the agent path (existing
   `/sugarscape/play.md` participation-guide link, now serving the new
   content) becomes primary; the manual CLI block stays as the no-agent
   path; `RESOURCE_LINKS` gains `sugarscape-mixin` and `Metta-AI/coworld`.

## Validation

- **Mixin:** `diff -rq` against `games/_template/`; end-to-end rehearsal —
  fresh clone of public optimizer-seed, `add_game.sh` the mixin, walk
  `first-session.md` including a Studio launch and a local sweep;
  `tools/build.sh` builds; connector passes a `docker compose` smoke against
  the local game.
- **Game repo:** full pytest; fresh-clone setup rehearsal from the new
  instructions; documentation audit before commits.
- **Metta:** participation-guide tests green in the worktree; rendered guide
  read end-to-end.

## Sequencing

1. Game repo: reproducibility → human docs → manifest fixes.
2. Mixin authoring (pins SHAs from the settled game repo; GitHub repo
   creation confirmed with James).
3. Metta-side pointers (needs the mixin URL live).
4. End-to-end rehearsal.

## Decision log

- Separate public mixin repo (not in-repo) — James, 2026-08-18.
- Full implementation scope incl. metta-side — James, 2026-08-18.
- Plan for public seed + mixin; seed flipped public same day — James.
- Starter policy at clean-scaffold/baseline strength — James.
- Local paired sweeps admissible with hosted confirmation — James.
- Human docs in game repo, agent docs in mixin; AGENTS.md agent-terse —
  James.
- Commonwealth league live: `league_dac00450-027a-45e6-9f6b-c9bda7ddd61d`.
