# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[os, unittest]

import sugarscape/configuration
import sugarscape/simulation

suite "DTL base log compatibility":
  proc checkOracle(name: string) =
    let
      configPath = "tests/fixtures/" & name & ".json"
      oraclePath = "tests/fixtures/" & name & ".oracle.json"
      outputPath = getTempDir() / ("coworld-sugarscape-" & name & ".json")
      config = loadConfiguration(configPath)
    if fileExists(outputPath):
      removeFile(outputPath)
    var simulation = initSimulation(config)
    simulation.runSimulation(outputPath)
    check readFile(outputPath) == readFile(oraclePath)
    removeFile(outputPath)

  test "base JSON log is byte-identical to the pinned Python oracle":
    checkOracle("base_small")

  test "dual-resource JSON log is byte-identical to the pinned Python oracle":
    checkOracle("spice_small")
