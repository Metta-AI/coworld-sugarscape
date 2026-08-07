#!/bin/sh
# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
set -eu

for test in \
  py_random \
  configuration \
  environment \
  agents \
  simulation \
  replay \
  py_json \
  log_parity
do
  nim c -r \
    --path:src \
    --nimcache:"/tmp/coworld-sugarscape-$test" \
    -o:"/tmp/coworld-sugarscape-test-$test" \
    "tests/nim/test_$test.nim"
done
