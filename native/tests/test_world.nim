import std/[json, os, unittest]

import ../sugarscape_native

proc initialSnapshot(): JsonNode =
  let fixture = parseFile(currentSourcePath.parentDir / "fixtures" / "python_random_1729.json")
  %*{
    "schemaVersion": 4,
    "sourcePin": "585282e9ce7b22a33b89abb0d777917bd5887d1a",
    "configurationSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "rulesetSha256": [
      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    ],
    "timestep": 0,
    "width": 3,
    "height": 1,
    "sugarRegrowRate": 1,
    "spiceRegrowRate": 0,
    "maxCellDistance": 1,
    "rng": fixture["rng"],
    "liveOrder": [10],
    "cells": [
      %*{"sugar": 1, "maxSugar": 4, "spice": 0, "maxSpice": 0, "occupantId": 10},
      %*{"sugar": 4, "maxSugar": 4, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
      %*{"sugar": 2, "maxSugar": 4, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
    ],
    "agents": [
      %*{
        "id": 10, "seat": 0, "x": 0, "y": 0, "sugar": 5, "spice": 0, "age": 0,
        "sugarMetabolism": 2, "spiceMetabolism": 0,
        "sugarMetabolismModifier": 0, "spiceMetabolismModifier": 0,
        "vision": 1, "movement": 1, "visionModifier": 0, "movementModifier": 0,
        "maxAge": -1, "lookaheadFactor": 0,
        "aggressionFactor": 0, "aggressionFactorModifier": 0,
        "fertilityFactor": 0, "fertilityFactorModifier": 0,
        "depressed": false, "happinessUnit": 1, "maxFriends": 0,
        "friendlinessModifier": 0, "happinessModifier": 0,
      },
    ],
    "orderedCandidates": [
      [[1, 1], [2, 1]],
      [[0, 1], [2, 1]],
      [[1, 1], [0, 1]],
    ],
    "deaths": [],
  }

suite "native world":
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
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
    ]
    node["agents"] = %*[
      {
        "id": 10, "seat": 0, "x": 0, "y": 0, "sugar": 1, "spice": 0, "age": 4,
        "sugarMetabolism": 2, "spiceMetabolism": 0,
        "sugarMetabolismModifier": 0, "spiceMetabolismModifier": 0,
        "vision": 1, "movement": 1, "visionModifier": 0, "movementModifier": 0,
        "maxAge": -1, "lookaheadFactor": 0,
        "aggressionFactor": 0, "aggressionFactorModifier": 0,
        "fertilityFactor": 0, "fertilityFactorModifier": 0,
        "depressed": false, "happinessUnit": 1, "maxFriends": 0,
        "friendlinessModifier": 0, "happinessModifier": 0,
      },
      {
        "id": 20, "seat": 1, "x": 1, "y": 0, "sugar": 10, "spice": 0, "age": 2,
        "sugarMetabolism": 1, "spiceMetabolism": 0,
        "sugarMetabolismModifier": 0, "spiceMetabolismModifier": 0,
        "vision": 1, "movement": 1, "visionModifier": 0, "movementModifier": 0,
        "maxAge": -1, "lookaheadFactor": 0,
        "aggressionFactor": 0, "aggressionFactorModifier": 0,
        "fertilityFactor": 0, "fertilityFactorModifier": 0,
        "depressed": false, "happinessUnit": 1, "maxFriends": 0,
        "friendlinessModifier": 0, "happinessModifier": 0,
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

  test "spice-weighted Cobb-Douglas welfare flips the movement winner":
    var sugarOnlyNode = initialSnapshot()
    sugarOnlyNode["sugarRegrowRate"] = %0
    sugarOnlyNode["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 9, "maxSugar": 9, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
      {"sugar": 4, "maxSugar": 4, "spice": 4, "maxSpice": 4, "occupantId": newJNull()},
    ]
    sugarOnlyNode["agents"][0]["sugar"] = %1
    sugarOnlyNode["agents"][0]["spice"] = %1
    sugarOnlyNode["agents"][0]["sugarMetabolism"] = %1
    sugarOnlyNode["agents"][0]["spiceMetabolism"] = %0
    var sugarOnly = loadWorld(sugarOnlyNode)
    sugarOnly.stepOne()
    check sugarOnly.agents[0].x == 1

    var spiceWeightedNode = initialSnapshot()
    spiceWeightedNode["sugarRegrowRate"] = %0
    spiceWeightedNode["cells"] = sugarOnlyNode["cells"].copy()
    spiceWeightedNode["agents"][0]["sugar"] = %1
    spiceWeightedNode["agents"][0]["spice"] = %1
    spiceWeightedNode["agents"][0]["sugarMetabolism"] = %1
    spiceWeightedNode["agents"][0]["spiceMetabolism"] = %3
    var spiceWeighted = loadWorld(spiceWeightedNode)
    spiceWeighted.stepOne()
    check spiceWeighted.agents[0].x == 2

  test "both resources grow back to their independent caps":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %2
    node["spiceRegrowRate"] = %3
    node["agents"][0]["movement"] = %0
    node["cells"] = %*[
      {"sugar": 1, "maxSugar": 4, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 4, "maxSugar": 4, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
      {"sugar": 3, "maxSugar": 4, "spice": 1, "maxSpice": 2, "occupantId": newJNull()},
    ]
    var world = loadWorld(node)
    world.stepOne()
    check world.cells[2].sugar == 4
    check world.cells[2].spice == 2

  test "exact-zero spice after metabolism causes starvation":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["agents"][0]["movement"] = %0
    node["agents"][0]["sugar"] = %10
    node["agents"][0]["spice"] = %1
    node["agents"][0]["sugarMetabolism"] = %0
    node["agents"][0]["spiceMetabolism"] = %1
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 0
    check world.deaths.len == 1
    check world.deaths[0].cause == "starvation"
    check world.deaths[0].age == 0

  test "post-depression base traits survive snapshot round trips":
    var node = initialSnapshot()
    node["agents"][0]["depressed"] = %true
    node["agents"][0]["movement"] = %4
    node["agents"][0]["sugarMetabolism"] = %6
    node["agents"][0]["spiceMetabolism"] = %6
    node["agents"][0]["aggressionFactor"] = %1.145
    node["agents"][0]["happinessUnit"] = %0.5763
    node["agents"][0]["maxFriends"] = %3
    let world = loadWorld(node)
    let restored = loadWorld(world.snapshot())
    check restored.agents[0].depressed
    check restored.agents[0].movement == 4
    check restored.agents[0].sugarMetabolism == 6
    check restored.agents[0].spiceMetabolism == 6
    check restored.agents[0].aggressionFactor == 1.145
    check restored.agents[0].happinessUnit == 0.5763
    check restored.agents[0].maxFriends == 3

  test "infection modifiers clamp effective traits at action time":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["agents"][0]["sugar"] = %5
    node["agents"][0]["spice"] = %0
    node["agents"][0]["sugarMetabolism"] = %1
    node["agents"][0]["sugarMetabolismModifier"] = %2
    node["agents"][0]["spiceMetabolism"] = %1
    node["agents"][0]["spiceMetabolismModifier"] = %(-2)
    node["agents"][0]["movementModifier"] = %(-10)
    node["agents"][0]["visionModifier"] = %5
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 1
    check world.agents[0].x == 0
    check world.agents[0].sugar == 3
    check world.agents[0].spice == 0
    check world.agents[0].age == 1
