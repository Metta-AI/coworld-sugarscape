#!/bin/sh
set -eu

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
