# DTL sync: CI and implementation status

The upstream sync automation is being built in reviewed phases. Currently,
CI, read-only detection, disposable candidate preparation, and independent
Docker verification are implemented. Codex evaluation, PR publication, alerts,
and scheduled dispatch are not implemented or enabled.
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

The test job initializes submodules, uses Python 3.13.5 and uv 0.12.13, runs
`uv sync`, and sets `PYTHONHASHSEED=0`. PyYAML 6.0.3 is a development dependency
for the structural tests; it is not a game runtime dependency. Workflow `'on'`
keys are quoted so PyYAML's safe loader preserves them as strings.

## Local checks

From an initialized clone, with Python 3.13.5 and uv 0.12.13:

```sh
git submodule update --init
uv sync
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -n auto
```

If your installed uv is a different version, `uvx --from uv==0.12.13 uv sync`
runs the pinned version without replacing a global installation. `uv.lock` is
local generated state and must not be committed as part of this work.

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
future sync service. No CI step pushes the image.

## Detect upstream changes

`tools/dtl_sync.py` is synchronous and uses only Python's standard library.
It requires Git and an authenticated GitHub CLI (`gh`) with read access to
the named repository. It performs no GitHub mutations and never commits,
pushes, checks out the upstream tree, or imports upstream Python.

The input checkout's `origin` must be the intended repository. Detection
fetches `origin/main` into a new scratch bare repository, captures its commit
and `src/sugarscape` gitlink, and reads the blob identity of
`tools/dtl_sync/PROMPT.md` from that commit. Both files must exist on main.
The prompt is added in a later phase, so this CLI is currently qualified with
offline fixtures; it is not yet ready to run against the repository's present
remote main. There is no fallback to a local prompt or another pin.

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
same-repository `dtl-sync/` head. Multiple matching PRs fail. A selected PR's
missing, malformed, duplicate, or oversized state block fails rather than
discarding its delivery history.

The command writes a closed version-1 `meta.json` and prints one mode:

| Mode | Meaning |
|---|---|
| `new-pr` | No open sync PR; evaluation is needed |
| `update-pr` | Existing PR differs from the last successful publication, or force was requested |
| `noop` | Target is already on main, or the live publication tuple is unchanged |
| `retry-alerts` | Publication tuple is unchanged but at least one recorded channel is pending/failed |

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

The initial detection state is JSON between `<!-- dtl-sync-state` followed
by a newline and the closing newline plus `-->`. Its closed version-1 fields
are `schema_version`, `last_publication`, `deliveries`, and `open_questions`.
Questions contain a unique stable lowercase slug `id` and nonempty `question`.
Publication
identity contains main/target/prompt SHAs and the outgoing `published_head_sha`.
Detection compares that stored identity with the **live** PR head, so human
changes cannot take the unchanged-head shortcut. A null last publication
never counts as evaluated.

Deliveries are keyed by target SHA and channel (`assignment`, `discord`,
`asana`), with `status`, nullable `remote_id`, `attempts`, and nullable
`last_error`. A delivered receipt requires an ID. Any pending or failed
receipt triggers retry-alerts when no new evaluation is needed. This initial
state reader will be extended with the publication body, question resolution, and
telemetry in P5b; it is not a live external integration yet.

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
is left uncommitted; it is input for the future publisher's tree construction.
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

After editing/testing the disposable candidate in the future evaluation step:

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

## Later phases

This runbook will grow with implemented commands for dispatch, red PR review,
credential rotation, and week-one operations. Until those phases are complete,
use the design as a proposal, not an operational command reference.

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
its own process output. Publication and workflow artifact provenance checks
arrive in later phases; verification alone does not publish anything.

Studio integration tests skip with explicit reasons when their external
prerequisites are absent: discovery requires the Metta link app files and Node,
and launcher subprocess tests require Node on PATH. They retain their original
assertions and run on hosts with those prerequisites. Container logs list these
skips separately from the nested Docker acceptance skips. Neither a Metta
checkout nor a host home is mounted into verification containers.
