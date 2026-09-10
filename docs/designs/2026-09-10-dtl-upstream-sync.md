# DTL upstream sync: keeping the coworld wrapper current with `nkremerh/sugarscape`

Status: design approved in conversation 2026-09-10, not yet implemented.
Depends on: the `src/sugarscape` git submodule (branch `dtl-submodule`, commit
"Replace the vendored DTL copy with a pristine upstream submodule").

## Problem

The v3 coworld wraps the unmodified upstream DTL Sugarscape engine. Upstream
moves without us: as of 2026-09-10 it is three commits ahead of our pin. Every
upstream change can affect the wrapper in one of three ways: nothing we import
changed, something we import changed in a way the wrapper and docs can absorb
mechanically, or the engine grew a feature that needs a design decision about
how SugarLang, seats, targets, or scoring should expose it. Today nobody notices
any of these until someone bumps the pin by hand.

## Goals

- Detect upstream changes daily and on demand.
- Have a coding agent bump the submodule, adapt `src/coworld/` and the docs,
  and run the suite, producing a reviewable PR with an explicit written
  rationale.
- Alert James, with the agent's reasoning attached, whenever an upstream change
  needs design work rather than mechanical adaptation.
- Leave an auditable trail: every run's classification and reasoning is in the
  PR body, and every credential use is a repository secret sourced through the
  token broker.

## Non-goals

- Auto-merging anything. A human merges every sync PR.
- Regenerating the target catalog automatically. When engine semantics change
  the catalog may be stale, and deciding what to do about that is exactly the
  design work this system is meant to escalate.
- Tracking upstream branches other than `master`, or upstream tags (there are
  none).
- Running on a persistent machine. Everything runs on GitHub-hosted runners.

## Alternatives considered

- **Persistent EC2 box plus cron calling Codex.** Rejected: it adds a machine to
  keep alive, patched, and authenticated, for a job that is a few minutes a day
  and needs nothing a hosted runner lacks. `metta box new` can provision one if
  the agent ever needs a long-lived environment.
- **Dependabot `gitsubmodule` bumps plus a workflow on the PR.** Rejected:
  workflows triggered by Dependabot run with a read-only token and see only
  Dependabot secrets, not Actions secrets, so the Codex step would have no API
  key. The workflow does its own bump instead; it is one git command.
- **A Metta-AI fork carrying a patch branch.** Rejected with the submodule
  change: the wrapper needs no upstream patches, so a fork would only add a
  rebase step to every sync.

## Architecture

Two workflows and one script. The workflows are thin; the script holds every
decision so it can be unit-tested and run from a laptop.

```
.github/workflows/ci.yml          pytest on every PR and push to main (new; the repo has no CI today)
.github/workflows/dtl-sync.yml    schedule (daily) + workflow_dispatch
tools/dtl_sync.py                 detect | publish subcommands
tools/dtl_sync/PROMPT.md          the Codex task prompt, versioned with the repo
tools/dtl_sync/REPORT_SCHEMA.json the structured report Codex must write
tests/test_dtl_sync.py            unit tests for the script against a throwaway git repo
```

### `dtl-sync.yml` step order

1. `actions/checkout` with `submodules: true` and the app token (see
   Credentials) so later pushes trigger `ci.yml`.
2. `tools/dtl_sync.py detect` (see below). Emits `changed=true|false`,
   `branch`, `pr_number` (if an open sync PR exists), and writes the work
   directory `build/dtl-sync/` with `upstream.log`, `upstream.diff`,
   `pytest-before.txt`. Exits early when nothing changed unless dispatched with
   `force=true`.
3. `openai/codex-action` with `prompt-file: tools/dtl_sync/PROMPT.md`,
   `sandbox: workspace-write`, `effort: high`, default model,
   `output-file: build/dtl-sync/report.json`. The work directory files are
   referenced from the prompt by path.
4. `tools/dtl_sync.py publish`: validates `report.json` against the schema,
   commits Codex's changes with a message built from the report, pushes the
   branch, creates or updates the PR, applies labels, and fires alerts.
5. `ci.yml` runs on the pushed branch because the push used the app token.

Manual dispatch inputs: `upstream_ref` (default `master`; accepts a commit so a
specific upstream state can be targeted or a run replayed) and `force`
(default false; run even when the gitlink already matches).

### `detect`

- Fetch `upstream_ref` from `https://github.com/nkremerh/sugarscape` into the
  submodule.
- Read the pin from `git ls-files --stage src/sugarscape` on `main`. If it
  equals the fetched commit and `force` is false: no-op.
- Look for an open PR labeled `dtl-sync`. If one exists, check out its branch
  and bump onto it; the PR then always tracks upstream head (James's choice:
  one cumulative PR rather than a queue of small ones). Otherwise create
  `dtl-sync/<YYYY-MM-DD>-<short-sha>` from `main`.
- Check out the target commit in the submodule and stage the gitlink.
- Write `upstream.log` (`git log --stat` from the `main` pin to the target, so
  a cumulative PR always shows the full range) and `upstream.diff` (the full
  diff, excluding `plots/`, `data/`, `examples/`, and `README` to keep the
  agent's context on code that can matter; the log still lists them).
- Run `.venv/bin/python -m pytest -q -p no:cacheprovider` and save the output
  as `pytest-before.txt`. Failures here are expected input for Codex, not a
  workflow failure.

### The Codex task (`PROMPT.md`)

The prompt is the load-bearing artifact and is reviewed like code. Its
contract:

- Read `AGENTS.md`, `src/coworld/dtl.py`, `upstream.log`, `upstream.diff`, and
  `pytest-before.txt`.
- Never edit anything under `src/sugarscape/`. The workflow also rejects the
  run if the submodule tree is dirty after Codex finishes.
- Make the smallest change to `src/coworld/`, `tools/`, `tests/`, and docs that
  keeps the wrapper correct against the new upstream. Update docs in the same
  pass, following the repo's documentation rules.
- Rerun the suite. If `EXPECTED_TRAJECTORY_HASH` in `tests/test_dtl.py` no
  longer matches, do not simply update the constant: that is a semantics
  change and must be escalated (see Classification). Record the old and new
  hash in the report.
- Write `report.json` matching `REPORT_SCHEMA.json`:
  `classification`, `summary` (two or three sentences for the PR title and
  alert), `upstream_range`, `files_changed`, `tests` (`passed`, `failed`,
  `trajectory_hash_changed`), `design_questions` (list; required when
  `needs-design`), and `reasoning` (the full argument for the classification,
  written for James to read).

### Classification

The agent must choose exactly one, and the script enforces the first rule
mechanically:

- `needs-design` is forced by the script, regardless of the agent's choice,
  when `trajectory_hash_changed` is true or `tests.failed` is non-zero.
- `needs-design` should also be chosen by the agent when upstream adds or
  changes a configuration key, agent trait, decision model, ethics model,
  statistic, or mechanic that SugarLang, the seats layer, targets, scoring, or
  the replay format could expose or must account for. The test the prompt
  gives it: "would a maintainer need to decide *whether* and *how* players see
  this, not just *that* the code still runs?"
- `mechanical`: wrapper, tools, tests, or docs needed edits; the suite is green;
  the trajectory hash is unchanged.
- `no-impact`: upstream touched only files the wrapper never imports (GUI,
  plotting, README, examples, data scripts) and the suite is green with no
  wrapper edits.

### `publish`

- Validate `report.json`; a missing or invalid report is treated as
  `needs-design` with the raw Codex output attached, so a confused agent run
  still reaches James rather than vanishing.
- Refuse to continue if `git status --porcelain` inside `src/sugarscape` is
  non-empty.
- Commit: subject `dtl-sync: <classification>: <summary first sentence>`,
  body from the report, with the upstream range.
- Push with the app token. Create the PR if none exists, else update the body.
  The body is regenerated each run from the report: classification, summary,
  upstream range with a link to the upstream compare view, test results, the
  reasoning, design questions, and a run log (one line per run appended, so
  a cumulative PR keeps its history).
- Labels: always `dtl-sync`; plus `needs-design` when applicable. Remove
  `needs-design` only when a later run on the same PR reports otherwise and
  the trajectory hash matches `main` again.
- Alerts, only on `needs-design`, and only once per distinct upstream commit
  (recorded in the run log to avoid re-alerting on every daily run):
  - Assign James on the PR.
  - Discord DM through the agent bot: summary, design questions, PR link.
    Recipient snowflake is the repository variable `DTL_SYNC_DISCORD_USER_ID`.
  - Asana task in project `DTL_SYNC_ASANA_PROJECT_GID` (repository variable,
    to be provided by James): title from the summary, notes with the reasoning
    and PR link.

## Credentials

All three secrets are fetched once through the metta token broker (which logs
who asked and why) and stored as repository secrets. Broker scopes and the
secret names:

| Secret | Broker scope | Used by |
|---|---|---|
| `OPENAI_API_KEY` | `openai.inference` | `openai/codex-action` (`openai-api-key`) |
| `DISCORD_BOT_TOKEN` | `discord.post` (approval tier) | `publish` alert step |
| `ASANA_PAT` | `asana.rw` | `publish` alert step |

Plus a GitHub App installation token (preferred) or a fine-grained PAT with
`contents: write` and `pull-requests: write` on this repo, as
`DTL_SYNC_GITHUB_TOKEN`. The default `GITHUB_TOKEN` cannot be used for the push
because events it creates do not trigger other workflows, which would leave the
sync PR without CI.

Secrets are exposed only to the steps that need them. The Codex step receives
the OpenAI key through the action's proxy and nothing else.

## Security

- The repo is public. `dtl-sync.yml` runs only on `schedule` and
  `workflow_dispatch`, never on `pull_request`, so fork PRs cannot reach the
  secrets.
- The agent reads third-party code and commit messages, which is a
  prompt-injection surface. Mitigations: the action's sandbox, no git
  credential inside the Codex step, the script's hard refusal to publish a
  dirty submodule tree, human merge on every PR, and branch protection on
  `main` requiring one approving review and green `ci.yml`. Branch protection
  is set up as part of rollout; it does not exist today.
- The workflow's app token is scoped to this repository only.

## Testing

- `tests/test_dtl_sync.py` drives `detect` and `publish` against a temporary
  git repository with a fake "upstream" bare repo and a stubbed GitHub client:
  no-op when pinned at head; new branch when none is open; bump onto an
  existing open PR; forced `needs-design` on a changed trajectory hash and on
  failing tests; alert-once-per-upstream-commit; refusal on a dirty submodule.
- `actionlint` on both workflows, run in `ci.yml`.
- Acceptance: a manual dispatch against the three upstream commits pending on
  2026-09-10 (`2c77f4e`, `22b7350`, `585282e`: dark-mode GUI, an `exit()` in
  simulation shutdown, bar-chart plotting). Expected outcome: `no-impact` or
  `mechanical`, green suite, unchanged trajectory hash, no alert.

## Rollout

1. Merge the submodule PR.
2. Land `ci.yml` and enable branch protection on `main`.
3. Create the GitHub App (or PAT) and the four secrets; set the two repository
   variables (Discord user id, Asana project GID).
4. Land `dtl-sync.yml`, the script, prompt, schema, and tests.
5. Run the acceptance dispatch and review the PR it opens.
6. Enable the schedule (it is committed disabled behind a repository variable
   `DTL_SYNC_ENABLED=true` so the workflow file can land before the secrets).

## Open questions

- Asana project GID: James to provide.
- Daily schedule time: proposed 06:00 Pacific, so a PR is waiting at the start
  of the day. Not blocking.
- Whether `ci.yml` should also run the Docker image build. It is the hosted
  deployment path and the submodule makes it worth checking, but it roughly
  doubles CI time. Proposed: yes, on PRs only.
