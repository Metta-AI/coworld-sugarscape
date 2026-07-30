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
