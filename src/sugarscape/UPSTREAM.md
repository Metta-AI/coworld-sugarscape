# Vendored DTL Sugarscape

This directory vendors the Python Sugarscape implementation from
[`nkremerh/sugarscape`](https://github.com/nkremerh/sugarscape) at commit
`a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8` (2026-07-01):

> Removes agent references for any other agent encountered in an agent social
> network; modifies agent social networks to retain object references only for
> trades, loans, mates, and friends; removes an erroneous exit from simulation
> shutdown; updates GUI trade rendering.

The snapshot came from a fresh clone of upstream at the pinned commit
(2026-08-11) and is released under the Unlicense. `LICENSE` and `CREDITS` are preserved here. New Sugarscape
v3 behavior belongs in `src/coworld/`; do not extend this fork when an existing
subclass or factory seam can carry the change.

## Local changes

The upstream delta is intentionally limited to:

1. `sugarscape.py`: use package-relative imports for the five vendored modules.
2. `ethics.py`: use a package-relative import for `agent`.
3. `sugarscape.py`: accept an optional `agent_factory`, retain `Agent` as the
   default, and use the factory at the existing initial/replacement construction
   site. Births continue through the upstream `spawnChild` seam.
4. `sugarscape.py`: make the already-lazy GUI import package-relative. Headless
   construction still does not import or require Tkinter.
5. `__init__.py`: mark the vendor as an importable package and expose the pin.

No model mechanics, candidate generation, activation order, random-number use,
or statistics calculations are changed.

## Determinism boundary

Hosted and cross-process deterministic runs set `PYTHONHASHSEED=0` before the
Python interpreter starts. Setting it from inside a running interpreter does
not change that interpreter's hash seed. The v3 server entry point must verify
the setting and re-execute itself when necessary; the game Dockerfile must set
it directly.

DTL contains a few unordered structures. The v3 integration preserves them
rather than patching upstream. No simulation-order dependency on set iteration
is currently known; if one is found, record the exact path here before deciding
whether an upstream edit is justified.

## Updating the vendor

1. Stage a clean upstream snapshot and record its commit.
2. Replace the vendored upstream files wholesale.
3. Reapply only the package-import and `agent_factory` edits above.
4. Update the commit in this file and `__init__.py`.
5. Run the vendor-diff allowlist and stock trajectory-hash tests.
