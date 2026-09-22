import std/[json, os, unittest]

import ../sugarscape_native

proc initialSnapshot(): JsonNode =
  let fixture = parseFile(currentSourcePath.parentDir / "fixtures" / "python_random_1729.json")
  %*{
    "schemaVersion": 2,
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
    "deaths": [],
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

  test "starvation clears occupancy before later agents move":
    var node = initialSnapshot()
    node["width"] = %2
    node["liveOrder"] = %*[20, 10]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "occupantId": 20},
    ]
    node["agents"] = %*[
      {
        "id": 10, "seat": 0, "x": 0, "y": 0, "sugar": 1, "age": 4,
        "sugarMetabolism": 2, "vision": 1, "movement": 1, "maxAge": -1,
        "lookaheadFactor": 0,
      },
      {
        "id": 20, "seat": 1, "x": 1, "y": 0, "sugar": 10, "age": 2,
        "sugarMetabolism": 1, "vision": 1, "movement": 1, "maxAge": -1,
        "lookaheadFactor": 0,
      },
    ]
    node["orderedCandidates"] = %*[[[1, 1]], [[0, 1]]]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 1
    check world.agents[0].id == 20
    check world.agents[0].x == 0
    check world.agents[0].age == 3
    check world.liveOrder == @[20'i64]
    check world.deaths.len == 1
    check world.deaths[0].id == 10
    check world.deaths[0].age == 4
    check world.deaths[0].cause == "starvation"
    check world.cells[0].occupantId == 20
    check world.cells[1].occupantId == -1

  test "aging death occurs after metabolism and age increment":
    var node = initialSnapshot()
    node["agents"][0]["maxAge"] = %1
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 0
    check world.liveOrder.len == 0
    check world.deaths.len == 1
    check world.deaths[0].id == 10
    check world.deaths[0].age == 1
    check world.deaths[0].cause == "aging"
    check world.cells[1].occupantId == -1

  test "stepping stops when the population becomes extinct":
    var node = initialSnapshot()
    node["agents"][0]["maxAge"] = %1
    var world = loadWorld(node)
    check world.step(10) == 1
    check world.timestep == 1
