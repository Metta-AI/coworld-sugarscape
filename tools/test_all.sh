#!/bin/sh
set -eu

# src/sugarscape/viewer.html is generated from viewer/ and embedded into the
# binary with staticRead, so a stale checkout ships a stale broadcast.
python3 tools/build_viewer.py --check

# The byte-parity suites. Split into their own script because they need nothing
# but a stock Nim distribution, so CI can run them without the private
# `bitworld` package (see .github/workflows/ci.yml).
sh tools/test_simulation.sh

# The Coworld protocol and hosted-embed assertions - socket derivation under the
# proxy prefix, no external sub-resource, replay-server lifetime, late-joiner
# backlog. These are the checks that stand between a working hosted replay and a
# black box, so they belong in the suite rather than in a README command.
nim c -d:release --opt:speed \
  --nimcache:"${TMPDIR:-/tmp}/coworld-sugarscape-coworld-bin" \
  --path:src -o:"${TMPDIR:-/tmp}/coworld-sugarscape-coworld" src/sugarscape_coworld.nim
node tools/smoke_coworld.mjs "${TMPDIR:-/tmp}/coworld-sugarscape-coworld"
