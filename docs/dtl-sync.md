# DTL sync: CI and implementation status

CI and the four-job sync workflow are implemented locally: detection, sandboxed
Codex evaluation, independent Docker verification, validated tree publication,
PR state, and alert delivery. Hosted acceptance, credential provisioning, and
activation remain pending. Scheduled runs require `DTL_SYNC_ENABLED=true`.
The intended system is described in the
[upstream sync design](designs/2026-09-10-dtl-upstream-sync.md).

## CI

[ci.yml](../.github/workflows/ci.yml) runs on pull requests targeting `main`
and pushes to `main`. It declares read-only repository permissions, persists
no checkout credentials, and uses pinned action commits. It does not publish
images or request service secrets.

The jobs are:

| Job/check name | Runs | What it checks |
|---|---|---|
| `tests` | PRs and main pushes | Python suite, including parsed workflow invariants |
| `workflow-lint` | PRs and main pushes | actionlint on workflow files |
| `image-smoke` | Every PR | Game image build and headless DTL import |

These are the job names to verify when configuring required status checks;
`ci.yml` is a filename, not a check name. Branch protection and hosted execution
have not been configured or validated by the local implementation work.

The test job runs functional tests in parallel (`-m "not perf"`) and then
performance tests serially (`-m perf`, no `-n`) in separate steps. Both remain
required within the same `tests` job; performance assertions are unchanged.
This avoids the ranking-ratio flake observed under parallel host CPU load.
The test job initializes submodules, uses Python 3.13.5 and uv 0.12.13, runs
`uv sync`, and sets `PYTHONHASHSEED=0`. PyYAML 6.0.3 is a development dependency
for the structural tests; it is not a game runtime dependency. Workflow `'on'`
keys are quoted so PyYAML's safe loader preserves them as strings.

## Local checks

From an initialized clone, with Python 3.13.5 and uv 0.12.13:

```sh
git submodule update --init
uv sync
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -n auto -m "not perf"
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -m perf
```

If your installed uv is a different version, `uvx --from uv==0.12.13 uv sync`
runs the pinned version without replacing a global installation. `uv.lock` is
local generated state and must not be committed.

Install actionlint 1.7.12 into ignored `build/tools/`. On macOS arm64:

```sh
mkdir -p build/tools
curl --fail --silent --show-error --location \
  https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_darwin_arm64.tar.gz \
  --output build/tools/actionlint.tar.gz
echo 'aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f  build/tools/actionlint.tar.gz' | shasum -a 256 --check
# Extract only after the checksum succeeds.
tar -xzf build/tools/actionlint.tar.gz -C build/tools actionlint
build/tools/actionlint
```

The CI workflow contains the corresponding Linux amd64 URL and checksum.
For another platform, verify its archive against the
[actionlint release checksums](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)
before extraction. A successful actionlint run prints nothing and exits zero.

With Docker running, check the existing game image:

```sh
docker build --tag sugarscape-ci --file Dockerfile .
docker run --rm --network none sugarscape-ci python -c \
  "import sys; import coworld.dtl; assert 'tkinter' not in sys.modules"
```

The import smoke catches missing submodule contents that a Docker `COPY` alone
would not detect. It does not certify a complete hosted game or exercise the
hosted sync service. No CI step pushes the image.

## Detect upstream changes

`tools/dtl_sync.py` is synchronous and uses only Python's standard library.
It requires Git and an authenticated GitHub CLI (`gh`) with read access to
the named repository. It performs no GitHub mutations and never commits,
pushes, checks out the upstream tree, or imports upstream Python.

The input checkout's `origin` must be the intended repository. Detection
fetches `origin/main` into a new scratch bare repository, captures its commit
and `src/sugarscape` gitlink, and reads the blob identity of
`tools/dtl_sync/PROMPT.md` from that commit. Both files must exist on main.
The prompt is implemented locally at `tools/dtl_sync/PROMPT.md`; it and the
controller must reach main before hosted detection can run. Local qualification
uses offline fixtures. There is no fallback to a local prompt or another pin.

Once those prerequisites are in place, a manual invocation has this form:

```sh
mkdir -p build/dtl-sync
.venv/bin/python tools/dtl_sync.py detect \
  --checkout "$PWD" \
  --scratch build/dtl-sync/detect-123-1 \
  --output build/dtl-sync/meta.json \
  --repository Metta-AI/coworld-sugarscape \
  --app-login 'YOUR-SYNC-APP[bot]' \
  --run-id 123 --run-attempt 1
```

Replace the App login with the actual bot login. Run IDs and attempts must be
positive decimal strings; use the GitHub run/attempt values in a workflow.
The scratch directory must be new for each invocation, and the output parent
must exist. The input checkout and its Git refs/index remain unchanged;
fetches write only beneath scratch. Remove only the scratch directory you
created when it is no longer needed.

`--upstream-ref` accepts `master` (default) or a unique lowercase hexadecimal
commit abbreviation of 4–40 characters reachable from upstream master.
Ambiguous, unavailable, and non-commit identities fail. Master moving between
advertisement and fetch also fails rather than silently changing the target.
The command fetches the upstream commit graph and checks ancestry:

- Normally the target must descend from main's pin.
- `--replay` permits a historical target but is refused while a sync PR is open.
- `--force` bypasses both the unchanged-publication and already-pinned shortcuts.

PR discovery is paginated and accepts only an open PR in the named repository
with main as its base, the configured App author, `dtl-sync` label, and a
same-repository `dtl-sync/` head. Multiple matching PRs fail. An otherwise matching App PR without the label
but containing the state marker requires retained-publication reconciliation;
it is not silently ignored as an unrelated PR. A selected PR's
missing, malformed, duplicate, or oversized state block fails rather than
discarding its delivery history.

The command writes a closed version-1 `meta.json` and prints one mode:

| Mode | Meaning |
|---|---|
| `new-pr` | No open sync PR; evaluation is needed |
| `update-pr` | Existing PR differs, force was requested, or an authorized question resolution needs reevaluation |
| `noop` | Target is already on main, or the live publication tuple is unchanged |
| `retry-alerts` | Publication tuple is unchanged but a channel is pending/failed or the design label needs repair |

Modes are decisions only: the detector does not evaluate, publish, or retry
alerts. New branch names include the target prefix, run ID, and attempt. If
that generated branch already exists, detection refuses to overwrite or
reuse it without reconciliation.

## Detection artifacts

`meta.json` records `schema_version`, `repository`, `run_id`, `run_attempt`,
`main_sha`, `main_pin`, `target_sha`, `prompt_version`, nullable `pr_number`
and `pr_head_sha`, `branch`, `mode`, `compare_url`, `force`, and `replay`.
The prompt version is its Git blob SHA. All identities are full hashes;
unknown fields, inconsistent PR/mode pairs, invalid types, duplicate JSON
keys, and artifacts over 64 KiB are rejected.

The publication state is JSON between `<!-- dtl-sync-state` followed
by a newline and the closing newline plus `-->`. Its closed version-1 fields
are `schema_version`, `last_publication`, `deliveries`, `open_questions`,
`outcome`, `classification`, `cause`, `recent_runs`, `previous_report_artifact`,
`telemetry`, `resolved_questions`, `accepted_resumes`, `summary`, and `reasoning`.
Questions contain a unique stable lowercase slug `id` and nonempty `question`.
Publication
identity contains main/target/prompt SHAs and the outgoing `published_head_sha`.
Detection compares that stored identity with the **live** PR head, so human
changes cannot take the unchanged-head shortcut. A null last publication
never counts as evaluated.

Deliveries are keyed by target SHA and channel (`assignment`, `discord`,
`asana`), with `status`, nullable `remote_id`, `attempts`, and nullable
`last_error`. A delivered receipt requires an ID. Any pending or failed
receipt triggers retry-alerts when no new evaluation is needed. The complete
state is validated before writes; unknown fields are rejected. There is no
compatibility reader for intermediate build-phase schemas; no hosted state has
been created during this implementation.

External command errors report only tool name and exit status, or timeout,
without echoing arguments, stdin, or stderr that might contain credentials.
Inspect the relevant tool installation/authentication and scratch repository
when diagnosing an error; do not paste credentials into logs. Every command
has a timeout, and GitHub response/state parsing has size limits.

## Prepare a disposable candidate

After detection returns `new-pr` or `update-pr`, preparation creates a new
checkout from the captured identities. Both the candidate directory and the
artifact output directory must be new. For example, after the detection
prerequisites above are deployed:

```sh
.venv/bin/python tools/dtl_sync.py prepare inputs \
  --meta build/dtl-sync/meta.json \
  --checkout "$PWD" \
  --directory build/dtl-sync/candidate \
  --output build/dtl-sync/inputs \
  --app-login 'YOUR-SYNC-APP[bot]'
```

This fetches main and the recorded PR head into the disposable checkout,
rechecks the PR identity, and merges captured main when necessary. The merge
is left uncommitted; it is input for the publisher's tree construction.
The target upstream commit is fetched into that checkout's `src/sugarscape`
and its gitlink is staged before any later tests. The source checkout and its
submodule remain untouched. No candidate Python or agent is executed by this
command, and no branch is pushed.

It prints `ready` and exits 0, or records/prints `needs-human` and exits 2
when a merge conflict, an unapproved head change, or unsupported PR edits
prevent preparation. Other errors exit 1. `prepare.json` contains captured
identities, outcome, and reason. A needs-human checkout is diagnostic state;
do not use it for evaluation or patch publication.

Inputs include the complete `upstream.diff`, `upstream.log`, and a filtered
diff excluding upstream `plots/`, `data/`, `examples/`, and `README`. For an
existing PR, `previous-pin.diff` is the incremental upstream difference and
`wrapper.diff` contains cumulative wrapper edits relative to captured main.
Input logs/diffs exceeding 1 MiB fail instead of silently dropping context.

Optional `--previous-report PATH` copies a bounded JSON report to
`previous-report.json`. A missing/expired report does not block preparation:
`context-notes.json` records its absence and preserves the open questions
from PR state. The report and upstream text are data, not instructions.

An unexpected PR head pauses automation even if its author string resembles
the bot. To resume allowlisted human changes, a maintainer posts
`resume-sync FULL_CURRENT_PR_HEAD_SHA` on that PR, then supplies
`--resume-comment-id COMMENT_ID`. Preparation verifies the comment's PR URL,
exact head binding, author, and current write/maintain/admin permission through
GitHub. A stale or unauthorized comment cannot resume. PR changes outside
the allowed paths (other than the upstream gitlink) stay paused until merge,
even with an authorized resume. Main-only changes are excluded from that
branch-specific check.

## Build the complete candidate patch

After editing/testing the disposable candidate inside the evaluation sandbox:

```sh
.venv/bin/python tools/dtl_sync.py prepare patch \
  --meta build/dtl-sync/meta.json \
  --directory build/dtl-sync/candidate \
  --output build/dtl-sync/patch
```

The new output directory must be outside the candidate checkout. The command
does not run tests or Codex. It constructs a temporary index from main and
the current working files, including previous PR commits, staged/unstaged
changes, new nonignored files, and deletions. The candidate's real index is
unchanged. The complete patch is relative to captured main, not merely to the
last PR commit. Renames are represented as deletion and addition so both paths
are validated.

Allowed paths are `src/coworld/`, `tests/`, `tools/`, `docs/`, `README.md`,
and `AGENTS.md`, except `tests/test_dtl.py`, `tests/conftest.py`, and all
`tools/dtl_sync*` paths. Upstream files and `.github/` are also protected.
Archive, target-catalog, dependency, lockfile, and Git-metadata changes are
never included. Paths must be canonical relative names; symlinks (including
parent-directory symlinks), nonregular files, binary changes, and patches over
2 MiB are rejected. Changed file contents must be UTF-8 without NUL bytes;
candidate Git attributes cannot override this binary check.
Existing excluded archival symlinks are inspected as link text, never followed,
and retained from main; they are not candidate patch entries.

Other outside-allowlist edits are dropped and listed in `report-notes.json`.
An agent `cause` of `new-feature` escalates only when the agent's own
classification is `needs-design`; on a `mechanical` or `no-impact` proposal
it is treated as `none` (the first hosted acceptance run escalated an
unreached GUI change because of exactly that inconsistency).
Protected edits force a `needs-design` note with cause `protected-path-edit`;
the protected bytes are never shipped in the patch. A dirty upstream tree or
clean upstream checkout at the wrong SHA is also recorded as a protected edit.
This note is not independent verification; the verifier must fetch and
measure the intended upstream itself.

Outputs:

- `candidate.patch`: full allowlisted change, excluding the gitlink.
- `candidate.json`: version, main/target identities, patch SHA-256, complete
  candidate tree ID, changed paths, protected edits, and dropped edits.
- `report-notes.json`: captured identities/digest, dropped/protected paths,
  and any forced classification/cause.

The tree ID includes the target gitlink and main's contents outside the
allowlist, including main-only Dockerfile and protected tooling updates.
The command prints that tree ID on success. Generated Git objects stay in the
disposable candidate repository; this is not a commit or publication.

## Rollout status

The operator procedures below are implemented contracts and an unexecuted
rollout checklist. Hosted acceptance, credential provisioning, activation, and
remote writes require explicit authorization. Local workflow tests do not prove
real GitHub, Codex, Discord, or Asana delivery.

## Independent verification

Build the verifier image from the trusted main checkout before executing any
candidate code. It installs Python 3.13.5, Git, uv 0.12.13, and the development
and runtime dependencies from that checkout's `pyproject.toml`. It does not
build the candidate or install candidate dependencies. PyYAML remains a dev
requirement; the verifier runs the workflow structural tests too.

```bash
docker build -f tools/dtl_sync/verify.Dockerfile -t dtl-sync-verifier .
docker image inspect dtl-sync-verifier --format '{{.Id}}'
docker run --rm --network=none --entrypoint cat dtl-sync-verifier /opt/dependencies.txt
DTL_SYNC_REQUIRE_DOCKER=1 PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -ra tests/test_dtl_sync_isolation.py
```

Retain the build log (including the resolved Python base digest), image ID,
and `/opt/dependencies.txt` with the run artifacts. Dependency versions are
resolved at image build time, then all three measurements use that exact image
ID. Rebuild from each captured main in automation. Docker must be running;
missing Docker or a missing image returns a setup error naming the build command.
There is no unisolated fallback.

The real host acceptance above requires Docker and the prepared image. In the
ordinary offline suite, these infrastructure tests explicitly skip when Docker
is unavailable. Inside a measurement container they always skip with the reason
that there is no Docker socket. The suite's `-ra` output records these skips;
host acceptance is a separate required check and cannot be replaced by them.

After `prepare patch`, run from the trusted controller checkout:

```bash
.venv/bin/python tools/dtl_sync.py verify \
  --meta build/dtl-sync/meta.json \
  --candidate build/dtl-sync/patch/candidate.json \
  --patch build/dtl-sync/patch/candidate.patch \
  --checkout . \
  --directory build/dtl-sync/measurements \
  --output build/dtl-sync/verification \
  --image dtl-sync-verifier
```

Both directory arguments must be new. The verifier fetches captured main and
the target independently into fresh self-contained repositories. It checks the
main gitlink, patch size/digest, allowed paths, regular modes, UTF-8 text,
changed-file list, target gitlink, and reconstructed tree. Forbidden received
patches fail; they are never filtered into publishable evidence.

The stock measurement uses only main's wrapper, trajectory test, and conftest
with the target upstream. The controller parses the old hash constant without
importing Python code. A second container runs the candidate functional suite;
a third runs main's suite with main's original pin. Both container suites exclude
the registered `perf` marker (`-m "not perf"`), because timing ratios are not
meaningful under a CPU quota. This deliberately differs from the full host/CI
suite, which still runs performance assertions. `verify.json` records
`excluded_markers: ["perf"]`. Each suite records JUnit
XML and collection count. Completed failing tests and changed hashes remain
valid negative evidence. Empty collection, malformed/missing/truncated XML,
invalid counts, inconsistent exits, timeout, or missing probe output produce
incomplete evidence, never success.

Every container uses uid/gid 65534, a read-only root, no network, no Linux
capabilities, no privilege escalation, 2 CPUs, 4 GiB memory, and 256 PIDs. Only
its repository (including local Git metadata) and main's harness are mounted,
read-only. `/tmp` is a 1 GiB writable, executable tmpfs (the tests execute temporary fake
CLI scripts). Each disposable repository has an untracked `.venv` link to the
image's trusted `/opt/venv`; tests invoking `.venv/bin/python` use the same
installed environment as the harness. The suite harness adds the repository
root to Python's import path, matching `python -m pytest`. No controller/evidence directory,
baseline sibling, host home, credentials, or Docker socket is exposed. Ordinary
loopback socket tests can still run. Measurement output is bounded to 1 MiB and
the timeout is 15 minutes; cleanup forcibly removes the named container, including
remaining descendants. It also runs after output-limit or launch failures.

`verify.json` is written by the host controller after measurement. Its version-1
fields bind `main_sha`, `target_sha`, `patch_sha256`, and `candidate_tree`;
`pin_matches_target`, `patch_applied`, `hash_changed`, `hash_old`, and `hash_new`
are positive facts or null. `candidate_tests` and `baseline_tests` contain
`completed`, `exit_code`, `collected`, `passed`, `failed`, `errors`, `skipped`,
and `reason`. Missing facts are null with `completed: false`; `reason` explains
incomplete evidence. `image_id` identifies the actual measured image. Bounded
`stock.log`, `candidate_tests.log`, and `baseline_tests.log` retain completed
process output. The command returns 0 for complete evidence (including red
results), 1 for incomplete/invalid evidence. A malformed top-level input can
fail before an artifact is created; its absence is also a failure.

The write boundary protects trusted control files and independent baseline
measurements. It does not prove that arbitrary malicious code cannot falsify
its own process output. Git tree publication and PR delivery are separate
commands below. The workflow checks producer-specific artifact provenance before consumption;
verification alone does not publish anything.

Studio integration tests skip with explicit reasons when their external
prerequisites are absent: discovery requires the Metta link app files and Node,
and launcher subprocess tests require Node on PATH. They retain their original
assertions and run on hosts with those prerequisites. Container logs list these
skips separately from the nested Docker acceptance skips. Neither a Metta
checkout nor a host home is mounted into verification containers.

## Validated Git tree publication

Phase 5A implements `publish tree`: this command can push a branch to the source
checkout's origin. It does not create/update a PR, mutate its state block, mint
credentials, assign anyone, or send alerts. Delivery is a separate command
below. The local workflow implements provenance checks and publication routing;
hosted acceptance is pending. Local tests use temporary remotes and fake
GitHub/HTTP responses only.

Run from the captured trusted controller checkout, with captured artifacts and
an explicitly provisioned repository-scoped Git transport identity:

```bash
.venv/bin/python tools/dtl_sync.py publish tree \
  --meta build/dtl-sync/meta.json \
  --candidate build/dtl-sync/patch/candidate.json \
  --patch build/dtl-sync/patch/candidate.patch \
  --report build/dtl-sync/report.json \
  --verification build/dtl-sync/verification/verify.json \
  --checkout . \
  --directory build/dtl-sync/publication-tree \
  --output build/dtl-sync/publication \
  --app-login 'dtl-sync[bot]' \
  --app-email 'APP_USER_ID+dtl-sync[bot]@users.noreply.github.com'
```

Replace the App identity placeholders with the configured bot identity. Both
output directories must be new. The source checkout and its index remain
unchanged; the data checkout is disposable. The command returns 0 on a pushed,
reconciled, or unchanged result and 1 on invalid evidence, stale inputs, failed
reconstruction, or rejected push. It writes `publication.json` only after the
operation succeeds. Missing publication output is never a success receipt.

### Report contract

`tools/dtl_sync/REPORT_SCHEMA.json` is the closed JSON schema for the agent's
report. Trusted stdlib validation also checks identity bindings, duplicates,
text limits/hygiene, and exact coverage against the independently fetched
upstream diff. All fields are required:

- `classification`: `mechanical`, `no-impact`, or `needs-design` (a proposal).
- `cause`: `semantic-change`, `new-feature`, `compat-defect`, `baseline-failure`,
  `protected-path-edit`, `incomplete-verification`, or `none` (a proposal).
- `summary`: nonempty text, up to 1,000 characters.
- `upstream_range`: exactly `{"from": MAIN_PIN, "to": TARGET_SHA}`, full SHAs.
- `reachability`: up to 100 items, each exactly `path`, `symbol`, `reached`,
  and `reason`. Paths are canonical upstream-relative paths; symbols identify
  functions, configuration keys, or module-level changes. `reached` is a real
  boolean. Reasons explain reachability, not just whether a file was imported.
  Paths/symbols are limited to 500 characters, reasons to 2,000. Duplicate
  path/symbol pairs are rejected. A directory `path` ends in `/` and must use
  `symbol: "*"`; its reason and reached value cover every changed descendant.
  File entries cover one exact changed path. No file may be covered twice, even
  through different symbols or overlapping directories. Empty directory coverage
  and entries outside the changed set are rejected.
- `design_questions`: up to 100 unique stable slug `id`/`question` pairs;
  IDs are at most 100 characters, questions at most 2,000.
- `reasoning`: nonempty text up to 8,000 characters.

The complete report is bounded to 64 KiB. Its inventory must cover exactly
all changed upstream files, including both sides of renames. An empty inventory
is valid only when the independently checked upstream diff has no changed
files (for example a forced reevaluation of the same pin). File coverage does
not mechanically prove per-function reachability or semantic judgement; those
remain reviewable agent reasoning, alongside the independent measurements.

### Verification and classification

The publisher accepts only the closed version-1 `Verification` contract,
including an immutable image ID and exactly `excluded_markers: ["perf"]`.
Main/target/patch/tree bindings must match. Pin and patch facts must be exactly
true; both hashes must be valid and agree with `hash_changed`. Both suites must
be complete with positive collection, consistent exit codes, and nonnegative
integer counts. Passed + failed + errors + skipped must equal collected; skips
are never counted as passes or failures. All-skipped evidence does not establish
an executed measurement. Missing, null, inconsistent, or unknown fields reject
the publication, even with an empty patch. No bare-pin fallback exists.

For complete evidence, the script computes the class/cause in this order:

1. Changed stock hash: `needs-design` / `semantic-change`.
2. Recorded protected edit: `needs-design` / `protected-path-edit`.
3. Failing baseline: `needs-design` / `baseline-failure`.
4. Failing candidate with a green baseline: `needs-design` / `compat-defect`.
5. Agent-reported new feature: `needs-design` / `new-feature`.
6. Open state questions, report questions, or an agent `needs-design` proposal:
   `needs-design` / `none` when no measured cause above applies.
7. Otherwise, a nonempty wrapper patch or a reached upstream change is
   `mechanical` / `none`; an empty patch with only unreachable upstream changes
   is `no-impact` / `none`.

A red measured result is valid publication evidence. It pushes the exact
verified tree for later human review; it never updates the trajectory constant.
Authorized resolution is checked through PR comments before classification;
publication of the resulting body and receipts is described below.

### Git tree, races, retries, and unchanged results

The publisher reconstructs the entire tree from captured main, reapplies the
validated patch, independently fetches upstream, and sets the target gitlink.
It requires the exact verifier tree. Thus prior new files survive cumulative
patches, and main's Dockerfile/protected tooling updates cannot be replaced by
stale PR content. The commit's first parent is the previous PR head, or main
for a new PR; main is also a second parent when it is not already an ancestor
of the existing PR head.

It checks main, branch, PR identity/state, and PR head before reconstruction,
then checks the observed Git/GitHub state again immediately before a normal
fast-forward push. A concurrent divergent update rejects the push; no force
push is used. The App is the author/committer. The subject starts
`dtl-sync: CLASSIFICATION: SUMMARY_FIRST_SENTENCE`, and the body includes the
captured metadata and full report as JSON.

Commit dates are deterministically the first parent's commit time plus one
second. Together with the full input identity in the body, this makes the
expected commit reproducible after a push-success/delivery-failure split. A
retry using the same captured artifacts accepts only that exact outgoing SHA;
it never adopts a branch merely because its name or author looks right. This
works before PR creation and after an existing PR's branch has advanced. Use
new scratch/output paths when retrying. Detect still refuses an occupied new
branch; delivery orchestration must resume from the retained captured metadata
rather than inventing a new evaluation for that collision.

When the validated candidate tree equals the captured parent tree, the command
creates no commit or new branch. It still writes fresh evidence, so a forced
reevaluation can update an existing PR's evidence without an empty
commit. `publication.json` records `outcome` (`pushed`, `reconciled`, or
`unchanged`), main/target/prompt identities, outgoing head, tree and patch digest,
computed classification/cause, the full verified measurements, and a SHA-256
of the report serialized as sorted-key JSON. An unchanged new-PR evaluation
records main as its outgoing head; it does not mean a PR should be created.

## Controller modules

The trusted tool has three sibling modules, all covered by the protected
`tools/dtl_sync` path prefix:

| Module | Responsibility |
|---|---|
| `tools/dtl_sync.py` | CLI, detection, Git preparation, independent verification, and tree publication |
| `tools/dtl_sync_contracts.py` | Shared dataclasses, closed validators, identifier/JSON helpers, and path policy |
| `tools/dtl_sync_delivery.py` | PR state/rendering, GitHub discovery and authorization, publication-head reads, alerts, receipts, and failure notification |

Keep these files together in the captured trusted checkout. The CLI imports
its sibling modules explicitly; delivery uses the injected command runner and
has no runtime import of the controller. The test loader presents the combined
namespace used by existing tests. This extraction changes no command, argument,
artifact name, state schema, or delivery behavior. The workflow sources all three
files from captured trusted main, never candidate patches. The default-branch
workflow commit supplies the bootstrap controller when metadata is absent.

## PR state and delivery

Phase 5B implements these commands locally. They can perform real remote
writes when given real credentials; local acceptance uses only injected fake
services. No credential provisioning, hosted dispatch, PR, or alert has been
performed by the local implementation work. Run the controller from captured trusted main, never
from the candidate checkout. The workflow verifies each artifact's expected
producer, repository, workflow, run, and producer attempt before introducing
publication credentials.

After `publish tree`, pass its retained receipt and matching input artifacts:

```bash
.venv/bin/python tools/dtl_sync.py publish deliver \
  --meta /tmp/dtl-meta.json \
  --candidate /tmp/dtl-patch/candidate.json \
  --report /tmp/dtl-report.json \
  --verification /tmp/dtl-verify/verify.json \
  --publication /tmp/dtl-publication/publication.json \
  --checkout "$PWD" --output /tmp/dtl-delivery \
  --app-login 'dtl-sync[bot]' --james-login jamesboggs \
  --discord-user-id "$DTL_SYNC_DISCORD_USER_ID" \
  --asana-project-gid "$DTL_SYNC_ASANA_PROJECT_GID"
```

Supply `GH_TOKEN` as the repository-scoped App token, `DISCORD_BOT_TOKEN` as
the agent bot token, and `ASANA_PAT` as the project-authorized token through the
trusted job environment. The script does not mint credentials. The names and
IDs above are examples/configuration inputs, not a claim that access is set up.
Optional `--telemetry FILE` accepts the closed telemetry object below;
`--report-artifact-id DECIMAL_ID` records the retained report artifact ID.
`--resume-comment-id ID` records an accepted head-bound resume.

Delivery checks the meta/candidate/report/verification bindings, the publication
receipt's report digest, and live main/branch/PR identities. It uses the receipt's
outgoing head, never the incoming head, for `last_publication`. For a new PR,
the first create request includes the complete body and state atomically.
There is no body-less PR creation step. An unchanged new-PR tree creates no PR;
an unchanged existing-PR tree can receive updated evidence.

The body contains summary, reachability, independent test counts (including
skips), reasoning, open questions, telemetry, and run/artifact/compare links.
Public text escapes HTML and mentions; JSON escapes HTML comment delimiters.
Reachability display is capped at 12 KiB, with a pointer to the full report.
The whole body is capped at 48 KiB; human text can be shortened, but state is
never truncated or silently discarded. If complete state leaves no room for a
summary, delivery stops for manual archival/reconciliation. State replacement
on retry/failure also refuses oversize bodies. Humans should use PR comments;
the body is machine-owned.

### Questions, resume, and labels

Use an exact PR comment `resolved: question-id`. The script accepts repository
`write`, `maintain`, or `admin` permission, or the configured `--james-login`.
Other users and bots cannot resolve questions. A receipt stores `id`, the
question text, and `comment_id`; the same comment cannot resolve a later,
different question reusing that ID. Unresolved questions persist across
reports. Detection notices newly authorized resolutions and requests evaluation
even when the successful publication tuple is unchanged. Resolution alone
cannot override a changed stock hash, failed tests, protected edits, a new
feature, or a fresh conservative report classification.

Human edits to the PR head still require the existing P3 comment
`resume-sync FULL_CAPTURED_HEAD_SHA`. Pass its ID to `prepare inputs` and
`publish deliver` via `--resume-comment-id`; both reuse the same permission and
head checks. `detect`, `prepare inputs`, and `publish tree` also accept optional
`--james-login` for the configured owner exception. Accepted resumes record
`comment_id` and `head_sha` in state. Resume does not permit protected-path
edits, conflicts, stale heads, or automatic force-pushes.

Every successful delivery restores `dtl-sync`; `needs-design` follows the
current evidence and unresolved questions. Notification failure never removes
it. A label mismatch wakes `retry-alerts`, including failed removal of an old
red label after a positively green evaluation.

### State details and alert recovery

`recent_runs` retains the last ten distinct run-ID/attempt pairs and outcomes.
`previous_report_artifact` is a nullable positive decimal artifact ID; omission
on delivery preserves the prior pointer. Full reports belong in retained
artifacts. State keeps only the latest `summary` (first 500 characters) and
`reasoning` (first 1500 characters), so alert retries need no report artifact.
Both are required bounded strings in the closed schema, empty before any
publication. `resolved_questions` and `accepted_resumes` hold the
authorization receipts above. `telemetry` has exactly:

- `requested_model`, `actual_model`, `codex_version`: nullable strings.
- `action_sha`: nullable full commit SHA.
- `elapsed_seconds`: nullable finite nonnegative number.
- `token_usage`: null or nonnegative integer `input_tokens`, `output_tokens`,
  and `total_tokens`, with total equal to input plus output.
- `unavailable_reason`: required nonempty explanation when any fact is null.

Omitted telemetry defaults to null facts with an explicit unavailable reason;
requested model is never substituted for actual model. The workflow records
`requested_model: "action default"`, the pinned action SHA, elapsed action time,
and the measured `codex --version` when available. The pinned action exposes
no actual-model or token-usage output; these remain null with an explicit reason.

For every needs-design target, delivery initializes assignment, Discord, and
Asana receipts. It saves the pending attempt before each side effect, then saves
success with its returned ID (or a sanitized failure) before proceeding to the
next channel. Assignment checks the API's returned assignees; its receipt is
`owner/repo#PR:login`. Discord stores the message ID; Asana stores the task GID.
A failed channel does not erase successful receipts. A receipt persistence
failure stops further deliveries.

Retry with fresh detection metadata and a new output directory:

```bash
.venv/bin/python tools/dtl_sync.py publish retry-alerts \
  --meta /tmp/dtl-retry-meta.json --output /tmp/dtl-retry-delivery \
  --app-login 'dtl-sync[bot]' --james-login jamesboggs \
  --discord-user-id "$DTL_SYNC_DISCORD_USER_ID" \
  --asana-project-gid "$DTL_SYNC_ASANA_PROJECT_GID"
```

This requires `mode: retry-alerts`, the matching successful tuple, and live PR
state. It needs no patch, candidate, report, verification, publication artifact,
or Git checkout. It repairs labels and retries only non-delivered channels,
including pending targets from earlier publications. `delivery.json` contains
the final state. Exit 1 and printed `retry-alerts` indicate pending/failed
channels; the successful publication remains recorded. Otherwise exit is 0.
A command/persistence failure can occur before the output file is written;
retained PR state remains the recovery source.

If the Git push succeeded but PR delivery failed, rerun `publish deliver` with
the same retained artifacts and new output path. It searches paginated **all**
PR history for the exact App-owned same-repository branch and outgoing head,
including an unlabeled partial create. It requires matching initial state and
refuses ambiguous, closed, foreign, or stale PRs. It never reopens a closed PR.
A new detector run refuses an unlabeled state-bearing App PR so it cannot
silently create a second sync PR. Reconcile the retained publication first.
If the publication receipt itself was lost before PR creation, rerun
`publish tree` from retained evaluation inputs to recover its exact commit.
Expired or missing captured evidence requires operator review, not guessed
artifacts or adoption based only on author/branch names.

Delivery is **at-least-once**, not exactly-once. A crash or uncertain response
between a remote side effect and receipt persistence may repeat it. Asana
lists project tasks in pages of 100 and reuses a task whose notes contain the
exact line `dtl-sync:FULL_TARGET_SHA`; it follows only the returned offset,
never a returned URL, and refuses pagination cycles or more than 100 pages.
Both alert channels carry classification/cause, a summary excerpt (up to 500
characters), and up to five open question IDs with text (up to 300 characters
each), plus PR and run links. Asana notes also contain a reasoning excerpt (up
to 1500 characters) and the marker. Excerpts use the PR body's HTML/mention
escaping. Question clipping is marked; Discord messages are kept below 2000
characters with an explicit truncation notice. Retry-only delivery uses the
latest persisted excerpts and questions, including when retrying an older
target's failed channel. Assignment is naturally
repeatable; an uncertain Discord send can produce a duplicate DM. Receipts are
per target, per channel, rather than per evaluation run.

Discord/Asana use synchronous stdlib HTTP, 10-second request timeouts and at
most three attempts for 429, 5xx, or transport errors. `Retry-After` seconds or
HTTP dates are capped at five seconds; transport backoff is one then two
seconds. Permanent 4xx failures are not retried. All redirects are refused,
credentials are attached only to fixed service hosts, responses are bounded,
and errors omit tokens/response bodies. Discord disables mention parsing.
GitHub uses checked, timed `gh api` calls with JSON on stdin.

The API contracts are [GitHub PR creation](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request),
[Discord Create DM](https://docs.discord.com/developers/resources/user#create-dm),
[Asana project task listing](https://developers.asana.com/reference/gettasksforproject),
and [Asana task creation](https://developers.asana.com/reference/createtask).

### Failure without candidate evidence

The finalizer can notify from trusted workflow context even if `meta.json`
does not exist:

```bash
.venv/bin/python tools/dtl_sync.py publish failure \
  --repository owner/repository --run-id 123 --run-attempt 1 \
  --outcome operational-failure --discord-user-id "$DTL_SYNC_DISCORD_USER_ID" \
  --output /tmp/dtl-failure
```

Allowed failures are `needs-human`, `incomplete-verification`, and
`operational-failure`. This path performs no Git writes and consumes no
candidate artifacts. With valid `--meta FILE` naming a PR and `--app-login`,
it updates that owned open PR's outcome/recent run and adds a run-linked
comment, preserving the last successful publication tuple and all deliveries.
Otherwise it sends a Discord DM naming only the trusted repository and run;
it does not invent target or PR identities. `failure.json` records the outcome,
run URL, and PR number or Discord message ID. Exit 0 means the failure was
reported, not that evaluation succeeded. The workflow preserves a failing job
result after notification. Its finalizer wiring is tested locally; real service
acceptance remains pending.

## Sync workflow

[dtl-sync.yml](../.github/workflows/dtl-sync.yml) implements four separate jobs.
It is locally tested and has not been dispatched or enabled by this work.

| Job | Timeout | Execution and credentials |
|---|---|---|
| `detect` | 10 minutes | Trusted Git/stdlib only; read-only repository, PR, and Actions access |
| `evaluate` | 30 minutes | Trusted dependency setup; candidate code runs only inside the pinned Codex sandbox; read-only GitHub access and the selected OpenAI key |
| `verify` | 60 minutes | Trusted Docker build/controller; separate isolated stock, candidate, and baseline containers; read-only contents/Actions access |
| `publish` | 10 minutes | Trusted controller only; validates evidence before minting a repository-scoped App token; PR/alert delivery through existing commands |

All jobs require `refs/heads/main`, repository default branch `main`, and the
workflow path on that branch. This check precedes secret-bearing steps, including
manual dispatch. No checkout persists credentials. Actions use the immutable
SHAs selected in the implementation plan; Python is 3.13.5, uv is 0.12.13, and
Codex is 0.154.0. The static concurrency group is `dtl-upstream-sync` with
`cancel-in-progress: false`. No candidate cache is restored into trusted jobs.

The schedule is `0 13 * * *` (13:00 UTC daily) and runs only when repository
variable `DTL_SYNC_ENABLED` is exactly `true`. Manual dispatch bypasses that
schedule gate but still requires the trusted main-branch checks.

### Dispatch inputs

These inputs are implemented; live use requires separate rollout authorization
and the workflow/controller/prompt already present on main.

| Input | Default | Meaning |
|---|---|---|
| `upstream_ref` | `master` | Upstream master or a unique reachable commit prefix |
| `force` | `false` | Bypass unchanged-publication and already-pinned shortcuts |
| `replay` | `false` | Permit a historical target only when no sync PR is open |
| `exercise` | `none` | `needs-design` forces evaluation and overlays a synthetic design question on the real report |
| `test_invalid_key` | `false` | Select only the dedicated invalid key; requires manual dispatch and explicit `force=true` |

The exercise uses stable question ID `exercise-needs-design` and prefixes the
summary with `EXERCISE:`. It does not alter the patch, verification, measured
hashes, or classification precedence, and creates no artificial empty commit.
An authorized operator must resolve the exercise question before merging.
The invalid-key action is mutually exclusive with the normal action; an empty
invalid key never falls back to the working key. Use an intentionally invalid
string for that dedicated secret, never an old working credential.

### Sandbox prerequisites on the runner

Before the Codex action runs, `evaluate` installs `bubblewrap` and applies the
Ubuntu 24.04 AppArmor user-namespace settings from the Codex sandboxing
documentation (`bwrap-userns-restrict` profile, then
`kernel.apparmor_restrict_unprivileged_userns=0`). This is trusted setup that
runs no candidate code. Without it the action's bundled bubblewrap fallback
hung on the first sandboxed command in hosted acceptance (run 35013438187,
cancelled by the job timeout with its log discarded). Both Codex steps carry a
20-minute step timeout so a hang fails the step and keeps its log; the
evaluate job timeout stays 30 minutes. A complete local evaluation of the
three pending upstream commits took about two minutes and 128k tokens.

The action is pinned to v1.11 (`7c168a233489ca36cb495409e8f1fba7b522bb40`), not the newer v1.12. Two open
upstream defects in v1.12 match the wedges seen in hosted acceptance: the
action waits on its child's stream close and hangs until the job timeout when
any descendant keeps stdout open after Codex finishes (issue #150, fix PR #151
unmerged), and its `drop-sudo` step chmods root-owned sockets under `/run`,
which breaks D-Bus and `systemd-resolved` and makes the runner lose contact
with GitHub, so no log is uploaded and cancellation waits out the grace period
(issue #160). v1.11 has neither. Both Codex steps also pass
`--disable code_mode_host`, the helper process known to outlive `codex exec`.
Re-check those issues before moving the pin forward.

The agent's own test run is advisory and deliberately small: the prompt asks
for a bounded, serial run of `tests/test_dtl.py`, `tests/test_ruleset_agent.py`,
and `tests/test_episode.py` only. Two hosted runs wedged the runner for the
full 30-minute job timeout, with the step timeout unable to interrupt and no
log uploaded, after the agent started the full parallel suite inside the
sandbox; the same evaluation completed locally in two minutes, and both the
OpenRouter endpoint and the action's proxy were reproduced locally without
stalling. The verifier job runs the complete functional suite independently,
so the agent does not need to.

### Configuration and secret boundaries

| Repository setting | Consumer |
|---|---|
| Variable `DTL_SYNC_ENABLED` | Schedule gate only |
| Variables `DTL_SYNC_APP_ID`, `DTL_SYNC_APP_LOGIN`, `DTL_SYNC_APP_EMAIL` | App token, bot ownership, and Git author identity |
| Variable `DTL_SYNC_JAMES_LOGIN` | Assignment and authorized human resolution |
| Variables `DTL_SYNC_DISCORD_USER_ID`, `DTL_SYNC_ASANA_PROJECT_GID` | Fixed alert destinations |
| Variable `DTL_SYNC_ASANA_TAG_GID` (optional) | Tag applied to every created Asana task |
| Secret `OPENROUTER_API_KEY` | Normal Codex evaluation only; the action's proxy forwards it as the bearer token to the OpenRouter Responses endpoint (workflow env `CODEX_RESPONSES_ENDPOINT`) for model `CODEX_MODEL` |
| Secret `DTL_SYNC_INVALID_OPENAI_API_KEY` | Explicit authentication-failure exercise only |
| Secret `DTL_SYNC_APP_PRIVATE_KEY` | Publish job App-token minting only |
| Secrets `DISCORD_BOT_TOKEN`, `ASANA_PAT` | Publish delivery/retry; failure-only fallback needs Discord |

No credentials were provisioned or accessed for local acceptance. Use the
project's token-broker-first policy when a separately authorized operator
provisions these settings. The App installation token is explicitly scoped to
this repository, with contents, pull requests, and issues write permissions.
No App token is minted for a no-op. Notification-only paths with no validated
owned PR use trusted run context and Discord without an App token.

The trusted [prompt](../tools/dtl_sync/PROMPT.md),
[report schema](../tools/dtl_sync/REPORT_SCHEMA.json), and
[Codex config](../tools/dtl_sync/codex-home/config.toml) come from captured main.
The action runs in the disposable `candidate/`, never the controller. Before
it runs, dependencies are installed with `uv sync --project controller`, and
`candidate/.venv` links to that environment so sandboxed subprocess tests use
the same dependencies. Trusted setup does not import candidate Python.

The config disables automatic project-document loading and web search; setup
marks the candidate project untrusted so candidate project config cannot supply
hooks or MCP servers. The action uses `permission-profile: :workspace`,
`safety-strategy: drop-sudo`, `output-schema-file`, and `output-file`. Candidate
source and review context are data under the trusted task. Git hooks and
filesystem monitors are disabled for controller Git operations. The
[pinned action contract](https://github.com/openai/codex-action/blob/7c168a233489ca36cb495409e8f1fba7b522bb40/action.yml)
is verified structurally; actual hosted sandbox behavior still requires rollout
acceptance.

### Artifact provenance and reruns

Each producer uploads a flat archive named
`dtl-sync-{detect|evaluate|verify}-{run_id}-{producer_attempt}`, retained for
30 days, and exposes its exact artifact ID and attempt through job outputs.
Consumers query the artifact and the corresponding workflow run attempt before
downloading that single ID. They require the expected repository, run, producer
name/attempt, workflow path, workflow SHA, main branch, allowed event, and an
unexpired artifact. Detection metadata must additionally match the captured
main SHA and detection attempt. A consumer's current attempt is not substituted
for a successful producer's earlier attempt on a failed-job rerun.

Downloads explicitly bind repository/run and fail on digest mismatch. Routing
requires both successful provenance validation and successful download; residual
files from a failed download cannot authorize publication. These checks use the
[GitHub artifact API](https://docs.github.com/en/rest/actions/artifacts) and the
[pinned download implementation](https://github.com/actions/download-artifact/blob/3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c/src/download-artifact.ts).

Evaluation's collector accepts only fixed regular-file names: report, telemetry,
candidate metadata/patch, preparation notes, and diff/context logs. JSON files
are bounded to 64 KiB, patches to 2 MiB, and logs to 1 MiB. It rejects symlinks,
nonregular files, and oversized files, retaining other valid files while marking
the collection failed. It never uploads a candidate checkout, environment, or
arbitrary executable. Verification retains its closed result and three bounded
measurement logs. Publication retains publication/delivery/failure receipts.

Prior report context uses the saved evaluate artifact ID and independently
validates its original run/attempt. Missing or expired context is recoverable:
preparation records the loss and retains questions from PR state, the full
main-to-target upstream diff, and cumulative wrapper changes. Such prior
artifacts never substitute for current publication evidence.

Before an App token is minted, publication preflight uses the same independent
Git reconstruction, report/verification bindings, exact inventory, protected-path
checks, deterministic commit, and stale-head checks as `publish tree`. It never
pushes and writes only a preflight receipt. `publish tree` repeats the checks
with the write identity. A failed-job rerun can reconcile the exact already-pushed
commit and an initial PR whose state was atomically created before label/alert
completion; both head and publication tuple must match. A fresh detection run
still refuses an unlabeled state-bearing PR and requires retained-publication
reconciliation. It does not adopt arbitrary branches or PRs.

### Outcome routing and workflow helpers

Publish has job-level `always()` so failed or skipped dependencies reach its
trusted finalizer. It first loads bootstrap code from the default-branch workflow
commit; only validated metadata selects the captured-main controller.

| Input outcome | Publish behavior |
|---|---|
| Disabled schedule | All jobs skipped |
| `noop` | No evaluation, verification, publication, or alert work |
| `retry-alerts` | Existing PR state drives only unfinished deliveries; no candidate artifacts required |
| Preparation `needs-human` | Preserve successful publication and notify the owned PR |
| Failed detection/evaluation or invalid publication evidence | Operational failure; no candidate publication |
| Failed/incomplete verification | Incomplete-verification notification; no candidate publication |
| Complete evidence, including completed red tests | Independently classify, publish measured tree, then call `publish deliver` |
| Tree/PR/alert delivery failure | Preserve receipts and report failure; keep the job failed |

The first PR body and state are still created atomically by `publish deliver`.
If that command creates a PR and then fails, the finalizer can recover its
identity only from the trusted publication receipt, exact live head, App
ownership, and matching saved publication tuple. Failure comments use the
current attempt, while the original detection metadata remains unchanged.
With missing metadata or no validated PR, the fallback Discord message names
only the trusted repository and run. Successful notification does not make the
failed evaluation green. Runner loss or a killed finalizer cannot guarantee a
notification; hosted acceptance must exercise ordinary failure paths.

The synchronous `workflow` CLI subcommands support this wiring:
`inputs`, `artifact`, `check-meta`, `context`, `previous`, `report`, `collect`,
`route`, and `failure-context`. Use `python tools/dtl_sync.py workflow NAME --help`
for exact arguments; the workflow supplies their trusted context and output
paths. `route` performs read-only publication preflight; `failure-context`
performs read-only PR reconciliation and writes notification metadata. Neither
helper sends alerts or pushes Git. Structural and offline fake-service tests
are in `tests/test_dtl_sync_orchestration.py`; they cover new/update/no-op/red
and missing-artifact paths without contacting production services.

## Required checks for rollout

Require `tests`, `workflow-lint`, and `image-smoke` on pull requests to main.

Require one independent human review and keep bypass disabled for the sync App.
Confirm these exact job contexts appear on a real PR before configuring branch
protection; the workflow filename is not a check context. Image smoke runs on
PRs only, while tests and workflow lint also run on main pushes. A red semantic
sync PR must become green through an explained human change before merge.

## Operator patch policy

The following table is checked against the controller constants. Protected
entries take precedence over allowed entries; everything outside the allowlist
is excluded. The controller alone stages the target upstream gitlink.

| Policy | Paths |
|---|---|
| Allowed directories | `src/coworld/`, `tests/`, `tools/`, `docs/` |
| Allowed files | `README.md`, `AGENTS.md` |
| Protected files | `tests/test_dtl.py`, `tests/conftest.py` |
| Protected prefixes | `src/sugarscape/`, `tools/dtl_sync`, `.github/` |

A prefix is literal: `tools/dtl_sync` also protects the contracts and delivery
sibling modules. Binary and symlink changes are rejected. Protected human edits
pause preparation even after an authorized resume; protected automation edits
cannot enter the published patch. Inspect dropped/protected paths in the
retained notes rather than assuming the working checkout is the published tree.

## Manual dispatch examples

These commands perform remote actions. Run only after rollout authorization,
from the intended repository, with the workflow and trusted tools on main.
Inspect the selected repository before dispatch. The historical target must be
an actual reachable upstream commit; replay requires no open sync PR.

```sh
# Normal upstream evaluation (or quiet no-op).
gh workflow run dtl-sync.yml --ref main -f upstream_ref=master
# Forced reevaluation, including an unchanged target.
gh workflow run dtl-sync.yml --ref main -f upstream_ref=master -f force=true
# Replace HISTORICAL_SHA with an explicitly selected reachable commit.
gh workflow run dtl-sync.yml --ref main -f upstream_ref=HISTORICAL_SHA -f replay=true
# Real evaluation plus a synthetic design question and escalation.
gh workflow run dtl-sync.yml --ref main -f upstream_ref=master -f exercise=needs-design
# Authentication failure using only the dedicated invalid secret.
gh workflow run dtl-sync.yml --ref main -f upstream_ref=master -f force=true -f test_invalid_key=true
```

Use the resulting Actions run to read each job result and retained artifacts;
dispatch acceptance alone does not prove completion. These flags follow the
[GitHub CLI dispatch contract](https://cli.github.com/manual/gh_workflow_run).
For alert-only recovery, dispatch normally after restoring the failed service:
detection selects `retry-alerts` when the publication tuple is unchanged and a
receipt is unfinished. Do not force reevaluation just to retry a delivered PR's
alerts. See the existing `publish retry-alerts` command for retained local
metadata; it writes to services and needs the same authorization.

## Provisioning and rotation

This procedure is for a separately authorized operator. Nothing in the local
build provisioned credentials. Keep `DTL_SYNC_ENABLED` unset or `false` during
setup. Confirm the intended owner/repository, App installation, James's login,
Discord recipient, and Asana project before writing settings. The broker's
Asana bot user must be a member of that project, or task creation returns
"You do not have access to this project"; `DTL_SYNC_ASANA_TAG_GID` names an
existing tag in the same workspace.

Provision every variable and secret in the [configuration table](#configuration-and-secret-boundaries),
including `DTL_SYNC_APP_LOGIN`, `DTL_SYNC_APP_EMAIL`, `DTL_SYNC_JAMES_LOGIN`, and
`DTL_SYNC_INVALID_OPENAI_API_KEY`. Verify the App's bot login and numeric user ID
rather than deriving them from its display name; set its Git author email to
`BOT_USER_ID+BOT_LOGIN@users.noreply.github.com`. The App installation is limited
to this repository and the three documented write permissions. Create the
`dtl-sync` and `needs-design` labels before acceptance.

The service-secret provisioning scopes are:

| GitHub secret | Broker scope | Handling |
|---|---|---|
| `OPENROUTER_API_KEY` | `openrouter.inference` | Dedicated agent key with a hard spend limit; confirm remaining budget before acceptance |
| `DISCORD_BOT_TOKEN` | `discord.post` | Approval-tier request must explicitly name persistent Actions provisioning |
| `ASANA_PAT` | `asana.rw` | Confirm project access and intended Actions use |

Read the current Metta `devops/tf/token-broker/lambda/broker/AGENTS.md` and scope
catalog before provisioning. Use the stdlib client from a verified Metta path;
reading the client from the primary checkout is allowed, but never modify that
checkout. Every broker call must set `TOKEN_BROKER_SESSION_ID` from this session's
`CODEX_SESSION_ID`. Do not use the shared-session fallback. The broker audits
provisioning; it does not audit every later Actions use of the stored secret.
Confirm the credential lifetime supports this use before storing it.

Example for one authorized OpenRouter provisioning operation, using a verified
client path and explicit repository. The secret passes directly from the
broker-injected child environment to `gh` stdin, never into a shell argument,
log, or intermediate file:

```sh
DTL_SYNC_REPOSITORY=owner/repository
DTL_SYNC_BROKER_CLIENT=/absolute/path/to/metta/scripts/token_broker_client.py
export DTL_SYNC_REPOSITORY
TOKEN_BROKER_SESSION_ID="${CODEX_SESSION_ID:?session ID required}" python3 "$DTL_SYNC_BROKER_CLIENT" exec \
  --scope openrouter.inference --reason "Provision the OpenRouter key into the authorized Sugarscape repository Actions secret for scheduled DTL evaluation" -- \
  python3 -c 'import os,subprocess; subprocess.run(["gh","secret","set","OPENROUTER_API_KEY","--repo",os.environ["DTL_SYNC_REPOSITORY"]], input=os.environ["OPENROUTER_API_KEY"], text=True, check=True)'
```

Apply the same stdin pattern separately for the other two scopes/secrets, with
a reason naming each intended operation. For approval-tier scope requests, the
broker reason is the permission request; do not separately request the same
approval in chat. Never print a credential to obtain it. GitHub encrypts secrets
locally before upload through [`gh secret set`](https://cli.github.com/manual/gh_secret_set).
Confirm secret names through metadata, then confirm actual access in the hosted
acceptance sequence; secret presence alone does not prove access.

For the App private key, the operator generates a key in the App's settings and
stores it as `DTL_SYNC_APP_PRIVATE_KEY` through a protected stdin/file upload;
never commit it or put its contents in command arguments. This is App-owner key
management, not a reason to fetch service credentials directly from a backing
store. If a broker-managed per-user App key exists, use that scope instead.
Record the key fingerprint, creation date, owner, and rotation due date without
its value. Rotation follows [GitHub's App key procedure](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps):
add the new key, replace the Actions secret, validate minting in an authorized
run, then delete the old App key. Do not leave obsolete keys active.

For a service rotation, pause schedules, rotate the source credential with its
owner, update its broker backing entry through the authorized process, vend it
with a session-scoped reason, and replace the corresponding Actions secret.
Verify the relevant service and pending receipts before revoking any retained
old credential and restoring schedules. Some service rotations invalidate old
credentials immediately; plan that interruption with the service owner. Record
broker request IDs and acceptance run links, never values. Keep the intentionally
invalid exercise secret separate throughout; it is not a storage location for
revoked working credentials.

## Reviewing and recovering a sync PR

Read the full report, measured stock hashes, candidate and baseline counts,
patch/protected-path notes, and open questions before deciding what to change.
A completed red measurement is useful review evidence; incomplete verification
is a failure to establish evidence. Baseline failures are shown separately and
must not be misreported as regressions introduced by the target.

For a real semantic change, decide its effect on SugarLang, targets, scoring,
and public behavior. A human may update `EXPECTED_TRAJECTORY_HASH` in the
protected test only with an explanation and appropriate tests/docs, then bring
all required PR checks green. Automation never updates that constant. Human
protected edits pause automation until merge; merge under normal protection,
without bypassing a red check or approving one's own work.

For resolved design questions, post `resolved: QUESTION_ID` as an authorized
maintainer or the configured James login. Detection notices the receipt and
reevaluates; a comment does not override independent red evidence. For
allowlisted human edits, post `resume-sync FULL_CURRENT_PR_HEAD_SHA`; the
workflow discovers that comment and checks current permissions. A stale head
or protected edit remains paused. Keep human explanations in comments because
the PR body and state block are machine-owned.

| Condition | Operator action |
|---|---|
| Stale main/head | Inspect intervening changes, then dispatch fresh detection; never reuse stale artifacts to overwrite them |
| Merge conflict or unsupported human edit | Resolve through a reviewed human change; use head-bound resume only for allowlisted edits, otherwise finish the human PR and merge |
| Closed PR | Do not reopen or reuse it automatically; inspect why it closed and begin a fresh detection after reconciling any retained branch work |
| Multiple matching sync PRs | Have the owner choose the intended PR and reconcile the others; automation refuses ambiguity |
| Push/create succeeded, later delivery failed | Prefer failed-job rerun with retained producer artifacts; exact publication/head/state reconciliation is required |
| Unlabeled state-bearing initial PR | Reconcile using that run's retained evidence; fresh detection intentionally refuses it |
| Missing/expired prior report | Retain questions/state and inspect the recorded context-loss note; current evidence still must be complete |
| Malformed/oversized PR state or missing current artifacts | Stop publication and archive/reconcile with a human; do not erase state to make validation pass |
| Discord/Asana failure | Restore service access, inspect persisted receipts, then normal dispatch retries unfinished channels |

Alert delivery is at least once: a send accepted remotely but not saved locally
can duplicate on retry. Asana uses its deterministic marker and pagination to
reconcile tasks; Discord cannot promise exact deduplication in this window.
Inspect receipts before deleting suspected duplicates. Never reset successful
channel receipts merely to retry another channel.

## Hosted acceptance and week-one checks

All items below remain pending until an authorized operator records live proof.
Before activation, land the reviewed local work on main, configure required
checks and the App/settings above, and leave schedules disabled. Record the
exact deployed main/workflow SHA and the selected upstream target for each run.

1. Run a selected no-impact historical target with no open sync PR and replay
   enabled. Verify the report, unchanged stock hash, complete evidence, App-owned
   PR, and actual CI checks triggered by the App push/PR events.
2. Run the synthetic needs-design exercise on a real candidate. Verify the
   explicit exercise label in the report, stable question, unchanged genuine
   verification facts, assignment, real Discord DM ID, and real Asana task GID.
   Read back the actual message/task contents and the per-channel saved receipts.
3. Repeat normal dispatch for the same successful tuple. Verify no extra commit,
   message, or task. Exercise a failed channel and confirm recovery retries only
   unfinished deliveries, preserving successful IDs and the publication tuple.
4. Run the explicit invalid-key exercise with force. Verify evaluation fails,
   candidate publication does not occur, the finalizer reports the failure,
   and the working OpenAI secret remains unchanged. Confirm a later normal run
   works without replacing the normal key.
5. Resolve the exercise question with an authorized comment, confirm reevaluation
   and label/state behavior, and finish any PR through independent review and
   normal protection. An unchanged new-PR tree legitimately creates no PR; use
   a selected differing target to test actual initial creation.
6. Confirm artifact ID/producer/attempt links, 30-day retention, skip counts,
   action/CLI versions, elapsed time, and explicit unknown model/token usage.
   Configure an OpenAI budget alert; do not infer a hard spending cap from it.
7. Only after all evidence is accepted, set `DTL_SYNC_ENABLED=true`. During week
   one, inspect daily schedule/run history, no-op behavior, failures/finalizer
   receipts, PR check events, unresolved questions, credentials, and usage.
   Recheck schedule enablement after inactivity; missing runs are not no-ops.

For rollback, set `DTL_SYNC_ENABLED=false` (or unset it) and confirm subsequent
scheduled jobs skip. This gate does not cancel a running workflow or prohibit
manual dispatch; separately stop active work if required. Preserve artifacts,
PR state, and receipts for recovery. Revert an unwanted merged game change only
through an independently reviewed PR; disabling sync alone changes no game pin.
Do not restore schedules until the failure has an explained fix and fresh
acceptance evidence. No activation, cancellation, rotation, or merge was
performed as part of the local P1–P7 build.
