import std/[json, os, unittest]

import ../sugarscape_native

proc initialSnapshot(): JsonNode =
  let fixture = parseFile(currentSourcePath.parentDir / "fixtures" / "python_random_1729.json")
  %*{
    "schemaVersion": 1,
    "sourcePin": "585282e9ce7b22a33b89abb0d777917bd5887d1a",
    "timestep": 0,
    "width": 3,
    "height": 1,
    "sugarRegrowRate": 1,
    "maxCellDistance": 1,
    "rng": fixture["rng"],
    "liveOrder": [10],
    "cells": [
      %*{"sugar": 1, "maxSugar": 4, "occupantId": 10},
      %*{"sugar": 4, "maxSugar": 4, "occupantId": newJNull()},
      %*{"sugar": 2, "maxSugar": 4, "occupantId": newJNull()},
    ],
    "agents": [
      %*{
        "id": 10, "seat": 0, "x": 0, "y": 0, "sugar": 5, "age": 0,
        "sugarMetabolism": 2, "vision": 1, "movement": 1, "maxAge": -1,
        "lookaheadFactor": 0,
      },
    ],
    "orderedCandidates": [
      [[1, 1], [2, 1]],
      [[0, 1], [2, 1]],
      [[1, 1], [0, 1]],
    ],
  }

suite "native fixed-population world":
  test "snapshot resumes exactly":
    var direct = loadWorld(initialSnapshot())
    direct.step(5)
    var resumed = loadWorld(initialSnapshot())
    resumed.step(2)
    resumed = loadWorld(resumed.snapshot())
    resumed.step(3)
    check direct.snapshot() == resumed.snapshot()

  test "movement harvest metabolism and growback are deterministic":
    var world = loadWorld(initialSnapshot())
    world.stepOne()
    check world.timestep == 1
    check world.agents[0].x == 1
    check world.agents[0].sugar == 7
    check world.cells[0].sugar == 2
    check world.cells[1].sugar == 0
    check world.cells[2].sugar == 3
