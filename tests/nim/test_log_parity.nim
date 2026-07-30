import std/[os, unittest]

import sugarscape/configuration
import sugarscape/simulation

suite "DTL base log compatibility":
  test "native JSON log is byte-identical to the pinned Python oracle":
    let
      configPath = "tests/fixtures/base_small.json"
      oraclePath = "tests/fixtures/base_small.oracle.json"
      outputPath = getTempDir() / "coworld-sugarscape-base-native.json"
      config = loadConfiguration(configPath)
    if fileExists(outputPath):
      removeFile(outputPath)
    var simulation = initSimulation(config)
    simulation.runSimulation(outputPath)
    check readFile(outputPath) == readFile(oraclePath)
    removeFile(outputPath)
