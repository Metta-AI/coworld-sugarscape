> [!WARNING]
> **ARCHIVAL ONLY.** Everything under `archived/` is frozen: the original
> implementation at [`archived/v1/`](archived/v1/README.md), and the
> complete-but-never-implemented v2 design at
> [`archived/v2/`](archived/v2/README.md). Do not extend, release, or
> implement from either.

# Coworld Sugarscape

The repository root is reserved for the from-scratch successor (v3). Two
prior generations are retained for reference:

- [`archived/v1/`](archived/v1/) — the complete previous implementation:
  source, tests, tools, manifests, replay viewer, bundled player, and the
  pinned Python reference.
- [`archived/v2/`](archived/v2/) — a full redesign (agent-level player
  control, phased timestep, negotiation protocols) that reached
  design-complete but was backburnered on 2026-08-11 before implementation.

New implementation work belongs outside `archived/`.

Start with [`docs/what-is-a-coworld.md`](docs/what-is-a-coworld.md) — the
platform contract, current conventions, and an assessment of v1 — before
touching platform-facing code.

## Sugarscape v3

The current implementation is a Python coworld in `src/coworld/` backed by a
minimally patched, pinned DTL simulation in `src/sugarscape/`. Each seat receives
one target distribution and submits one declarative SugarLang ruleset; the world
then runs without player I/O and scores how closely the measured outcome matches
the target.

Ranked play uses a deterministic pool of 24 curated scenarios spanning all
seven targets and six mechanical families, forcing rulesets to adapt to the
observed world. `solo-ladder` assigns one policy one target; `duo-ladder` seats
two policies in the same world with different global targets and independent
scores. See [`docs/SCENARIOS.md`](docs/SCENARIOS.md) for the catalog, selection
rule, regeneration workflow, and per-scenario reachability gate.

Run the offline suite with `.venv/bin/python -m pytest`. For local container
development, `docker compose up` starts the one-seat config in `config.json` and
the bundled target-aware baseline. Protocol, language, and target references are
in `docs/PROTOCOL.md`, `docs/RULES.md`, and `docs/TARGETS.md`.

Reproducibility assumes `PYTHONHASHSEED=0`; both Dockerfiles set it, and the
server re-executes itself with that value when necessary. A recorded results or
replay seed reproduces an episode on the pinned interpreter.

## Credits

This project is based on the **Digital Terraria Lab (DTL) Sugarscape**
implementation — [`nkremerh/sugarscape`](https://github.com/nkremerh/sugarscape),
maintained by Nate Kremer-Herman and contributors, released into the public
domain under the Unlicense. The archived v1 is a native Nim port of the DTL
model, with the pinned upstream source preserved as its behavioral oracle at
[`archived/v1/reference/dtl-python/`](archived/v1/reference/dtl-python/)
(full contributor list in its `CREDITS` file). The DTL model itself builds on
*Growing Artificial Societies* (Epstein & Axtell, 1996).
