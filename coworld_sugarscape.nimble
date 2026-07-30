version = "0.1.0"
author = "Metta-AI"
description = "High-performance, behaviorally identical Nim port of DTL Sugarscape"
license = "Unlicense"
srcDir = "src"
bin = @["sugarscape"]

requires "nim >= 2.2.0"

task test, "Run native compatibility tests":
  for test in [
    "py_random",
    "configuration",
    "environment",
    "agents",
    "simulation",
    "py_json",
    "log_parity",
  ]:
    exec "nim c -r --path:src --nimcache:/tmp/coworld-sugarscape-" &
      test & " -o:/tmp/coworld-sugarscape-test-" & test &
      " tests/nim/test_" & test & ".nim"
