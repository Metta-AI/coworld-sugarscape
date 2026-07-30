#!/bin/sh
# The compatibility suites: everything that proves this port is byte-identical to
# the pinned Python oracle. These depend on nothing outside the Nim distribution
# (std/* plus the bundled `checksums`), which is why they are split out — CI can
# run them on a stock toolchain, without the private `bitworld` package that the
# Coworld edge needs.
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
    --nimcache:"${TMPDIR:-/tmp}/coworld-sugarscape-$test" \
    -o:"${TMPDIR:-/tmp}/coworld-sugarscape-test-$test" \
    "tests/nim/test_$test.nim"
done
