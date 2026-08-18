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

- `src/sugarscape/` is the pinned DTL vendor. Keep changes on the documented
  `UPSTREAM.md` allowlist; new behavior belongs elsewhere.
- `src/coworld/` owns SugarLang, seats, simulation integration, measurement,
  scoring, replay, and the async-only server edge.
- `targets/` is the validated histogram catalog. Every target sharing a
  variable must use that variable's canonical support and bins.
- `players/baseline/` is the bundled one-shot player; `replay-viewer/` is a
  dependency-free static bundle.
- Setup from a fresh clone: `uv sync` (creates `.venv` from `pyproject.toml`).
  Run `.venv/bin/python -m pytest` offline. Server socket tests need permission
  to bind a localhost port. Do not introduce async outside `server.py`.

Deterministic comparisons use `canonical_results_payload()`, which excludes
wall-clock timings. Cross-process replay assumes `PYTHONHASHSEED=0`. Never put
tokens or the drawn seed in player observations.
