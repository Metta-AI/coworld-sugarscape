#!/bin/sh
set -eu

# src/sugarscape/viewer.html is generated from viewer/ and embedded into the
# binary with staticRead, so a stale checkout ships a stale broadcast.
python3 tools/build_viewer.py --check

for test in \
  py_random \
  configuration \
  environment \
  agents \
  simulation \
  py_json \
  log_parity
do
  nim c -r \
    --path:src \
    --nimcache:"/tmp/coworld-sugarscape-$test" \
    -o:"/tmp/coworld-sugarscape-test-$test" \
    "tests/nim/test_$test.nim"
done

# The Coworld protocol and hosted-embed assertions - socket derivation under the
# proxy prefix, no external sub-resource, replay-server lifetime, late-joiner
# backlog. These are the checks that stand between a working hosted replay and a
# black box, so they belong in the suite rather than in a README command.
nim c -d:release --opt:speed \
  --nimcache:/tmp/coworld-sugarscape-coworld-bin \
  --path:src -o:/tmp/coworld-sugarscape-coworld src/sugarscape_coworld.nim
node tools/smoke_coworld.mjs /tmp/coworld-sugarscape-coworld
