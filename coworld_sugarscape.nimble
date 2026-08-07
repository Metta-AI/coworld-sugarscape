version = "0.1.0"
author = "Metta-AI"
description = "High-performance, behaviorally identical Nim port of DTL Sugarscape"
license = "Unlicense"
srcDir = "src"
bin = @["sugarscape", "sugarscape_coworld"]

requires "nim >= 2.2.0"
requires "bitworld >= 0.1.0"
requires "mummy >= 0.4.7"
requires "curly >= 1.1.1"
requires "checksums >= 0.2.2"
requires "zippy >= 0.10.19"

task test, "Run native compatibility tests":
  for test in [
    "py_random",
    "configuration",
    "environment",
    "agents",
    "simulation",
    "replay",
    "py_json",
    "log_parity",
  ]:
    exec "nim c -r --path:src --nimcache:/tmp/coworld-sugarscape-" &
      test & " -o:/tmp/coworld-sugarscape-test-" & test &
      " tests/nim/test_" & test & ".nim"
