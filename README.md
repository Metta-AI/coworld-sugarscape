> [!WARNING]
> **ARCHIVAL ONLY.** The original Sugarscape implementation is frozen under
> [`archived/v1/`](archived/v1/README.md). Do not extend or release it as the
> current game.

# Coworld Sugarscape

The repository root is reserved for a from-scratch successor. The complete
previous implementation—including source, tests, tools, manifests, replay
viewer, bundled player, and pinned Python reference—is retained in
[`archived/v1/`](archived/v1/) for historical reference and reproducibility.

New implementation work belongs outside `archived/`.

Start with [`docs/what-is-a-coworld.md`](docs/what-is-a-coworld.md) — the
platform contract, current conventions, and an assessment of v1 — before
touching platform-facing code.

## Credits

This project is based on the **Digital Terraria Lab (DTL) Sugarscape**
implementation — [`nkremerh/sugarscape`](https://github.com/nkremerh/sugarscape),
maintained by Nate Kremer-Herman and contributors, released into the public
domain under the Unlicense. The archived v1 is a native Nim port of the DTL
model, with the pinned upstream source preserved as its behavioral oracle at
[`archived/v1/reference/dtl-python/`](archived/v1/reference/dtl-python/)
(full contributor list in its `CREDITS` file). The DTL model itself builds on
*Growing Artificial Societies* (Epstein & Axtell, 1996).
