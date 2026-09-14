# Archive boundary

Everything under `archived/` is **archival only**:

- `archived/v1/` — the frozen original implementation (a DTL port). Do not
  extend, release, or treat it as the current Sugarscape implementation.
  Changes there should be limited to preservation, security, or
  reproducibility fixes that are explicitly requested.
- `archived/v2/` — a complete-but-never-implemented design (backburnered
  2026-08-11 in favor of v3). Do not implement from it without explicitly
  reviving v2. See `archived/v2/README.md`.

The repository root is reserved for the from-scratch successor (v3). Add new
game code outside `archived/`, with its own architecture and behavioral
contract. Before any platform-facing work, read
[docs/what-is-a-coworld.md](docs/what-is-a-coworld.md) — the coworld platform
contract, current conventions, and the experimental Arena (WASM) contract.

Read `archived/v1/AGENTS.md` only when working on the archived
implementation.

## v3 layout

- `src/sugarscape/` is the upstream DTL Sugarscape git submodule
  (`nkremerh/sugarscape`), pinned by commit and never edited. `src/coworld/dtl.py`
  loads it and swaps the agent class; all new behavior belongs in `src/coworld/`.
  To bump: `git -C src/sugarscape checkout <commit>` then `git add src/sugarscape`;
  `tests/test_dtl.py` checks the pin and the stock trajectory hash.
- `src/coworld/` owns SugarLang, seats, simulation integration, measurement,
  scoring, replay, and the async-only server edge.
- `targets/` is the validated histogram catalog. Every target sharing a
  variable must use that variable's canonical support and bins.
- `players/baseline/` is the bundled one-shot player; `replay-viewer/` is a
  dependency-free static bundle.
- Setup from a fresh clone: `git submodule update --init`, then `uv sync`
  (creates `.venv` from `pyproject.toml`).
  Run `.venv/bin/python -m pytest` offline. Server socket tests need permission
  to bind a localhost port. Do not introduce async outside `server.py`.

Deterministic comparisons use `canonical_results_payload()`, which excludes
wall-clock timings. Cross-process replay assumes `PYTHONHASHSEED=0`. Never put
tokens or the drawn seed in player observations.

## CI checks

CI uses Python 3.13.5 and uv 0.12.13. Run `uv sync`, then
`PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -n auto`. PyYAML is dev-only
and supports `tests/test_dtl_sync_workflows.py`; quote workflow `'on'` keys.
After workflow edits, run `build/tools/actionlint` (installation and checksums
are in [docs/dtl-sync.md](docs/dtl-sync.md)). Keep action references pinned to
full commit SHAs and checkouts configured with `persist-credentials: false`.
Do not commit generated `uv.lock` during the sync implementation.

The current automation is CI only: `tests`, `workflow-lint`, and the PR-only
`image-smoke` jobs in `.github/workflows/ci.yml`. The upstream sync workflow
will arrive in a later phase; do not describe it as operational yet.

`tools/dtl_sync.py detect` resolves upstream and PR identities using scratch
bare repositories and read-only `gh api` calls. It does not modify the input
checkout or execute upstream code. See the runbook for required main-branch
files and CLI arguments. Keep GitHub/command transports injectable for offline
tests (`tests/test_dtl_sync.py`, `tests/dtl_sync_support.py`).

`prepare inputs` creates a new disposable checkout and stages the target
gitlink there; it never alters the source checkout. `prepare patch` writes a
complete main-to-candidate patch using a temporary index, preserving the
candidate's existing index. Keep patch output outside the candidate checkout.
See `tests/test_dtl_sync_prepare.py` for cumulative changes, main merges,
authorized resume, protected paths, and binary/symlink rejection.

`verify` reconstructs from captured main and runs stock, candidate, and baseline
measurements in separate nonroot Docker containers. Build the verifier from
trusted main with `docker build -f tools/dtl_sync/verify.Dockerfile -t dtl-sync-verifier .`.
Run mandatory host isolation acceptance with
`DTL_SYNC_REQUIRE_DOCKER=1 PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -ra tests/test_dtl_sync_isolation.py`.
Containers deliberately skip this nested infrastructure test with a printed
reason: they have no Docker socket. Never fall back to host execution when
Docker/image setup is missing. Keep the controller and final evidence outside
all mounted paths; only the current measurement and trusted harness are mounted,
read-only. The verifier harness and image files under `tools/dtl_sync/` must
come from captured main, never candidate patches.

The verifier runs the functional suite with `-m "not perf"` under its CPU quota
and records `excluded_markers: ["perf"]` in `verify.json`. Host/CI commands above
still run the registered `perf` tests. Studio integration tests explicitly skip
when external Metta link app files or Node are missing; do not remove assertions
or mount a host checkout to satisfy those prerequisites.

`publish tree` validates the closed report and verification contracts before
reconstructing and pushing the complete measured tree. It uses only Git and
read-only GitHub PR discovery; PR body/state updates and delivery are later
work. Tests in `tests/test_dtl_sync_publish.py` push only to temporary local
remotes. Never test this command against the real origin without authorization.
Keep `excluded_markers: ["perf"]` in the verification contract and count skips
separately. Preserve completed red results and reject incomplete artifacts
regardless of patch size. Retry reconciliation requires the exact deterministic
commit, not a branch name or author string. See the runbook for all CLI inputs,
report fields, stale-write checks, and unchanged-tree evidence.
