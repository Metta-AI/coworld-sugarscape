# Archive boundary

The implementation under `archived/v1/` is **archival only**. Do not extend,
release, or treat it as the current Sugarscape implementation. Changes there
should be limited to preservation, security, or reproducibility fixes that are
explicitly requested.

The repository root is reserved for a from-scratch successor. Add new game
code outside `archived/`, with its own architecture and behavioral contract.
Before any platform-facing work, read
[docs/what-is-a-coworld.md](docs/what-is-a-coworld.md) — the coworld platform
contract, current conventions, the experimental Arena (WASM) contract, and
the open v2 design decisions.

Read `archived/v1/AGENTS.md` only when working on the archived implementation.
