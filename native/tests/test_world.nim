import std/[json, os, unittest]

import ../sugarscape_native

proc initialSnapshot(): JsonNode =
  let fixture = parseFile(currentSourcePath.parentDir / "fixtures" / "python_random_1729.json")
  %*{
    "schemaVersion": 7,
    "sourcePin": "585282e9ce7b22a33b89abb0d777917bd5887d1a",
    "configurationSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "rulesetSha256": [
      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    ],
    "rulesets": [newJNull(), newJNull()],
    "timestep": 0,
    "worldGini": 0,
    "worldMeanWealth": 0,
    "width": 3,
    "height": 1,
    "sugarRegrowRate": 1,
    "spiceRegrowRate": 0,
    "maxCellDistance": 1,
    "maxCombatLoot": 0,
    "maxTribes": 1,
    "inheritancePolicy": "none",
    "nextAgentId": 21, "depressionPercentage": 0,
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
        "tags": newJNull(), "tribe": newJNull(), "tagging": false,
        "tradeFactor": 0, "marginalRateOfSubstitution": 1, "tradeVolume": 0,
        "sugarPrice": 0, "spicePrice": 0, "lastTradeTimestep": -1,
        "lastTradePartners": 0, "diseaseProtectionChance": 0,
        "immuneSystem": newJNull(), "diseases": [],
        "born": 0, "startingSugar": 5, "startingSpice": 0, "sex": "female",
        "fertilityAge": 10, "infertilityAge": 20, "inheritancePolicy": "none",
        "lendingFactor": 0, "baseInterestRate": 0, "loanDuration": 0,
        "sugarMeanIncome": 1, "spiceMeanIncome": 1,
        "startingImmuneSystem": newJNull(), "racialTags": newJNull(),
        "fatherId": newJNull(), "motherId": newJNull(), "childrenIds": [], "mateIds": [],
        "lastMovedTimestep": -1, "lastReproducedTimestep": -1, "lastMates": 0,
        "lastLendedTimestep": -1, "lastLoans": 0, "creditorLoans": [], "debtorLoans": [],
        "friends": [], "lastCombatTimestep": -1, "conflictHappiness": 0,
        "familyHappiness": 0, "healthHappiness": 0, "socialHappiness": 0,
        "wealthHappiness": 0, "happiness": 0,
      },
    ],
    "orderedCandidates": [
      [[1, 1], [2, 1]],
      [[0, 1], [2, 1]],
      [[1, 1], [0, 1]],
    ],
    "orderedNeighbors": [[2, 1, 1, 2], [0, 2, 2, 0], [1, 0, 0, 1]],
    "diseases": [], "remainingDiseaseIds": [],
    "creditorTombstones": [],
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

  test "nullable sex round trips and disables reproduction":
    var node = initialSnapshot()
    node["agents"][0]["sex"] = newJNull()
    let world = loadWorld(node)
    check not world.agents[0].hasSex
    check world.snapshot()["agents"][0]["sex"].kind == JNull

  test "relation IDs must be unique and nonnegative":
    var duplicate = initialSnapshot()
    duplicate["agents"][0]["childrenIds"] = %*[20, 20]
    expect AssertionDefect:
      discard loadWorld(duplicate)
    var negative = initialSnapshot()
    negative["agents"][0]["mateIds"] = %*[-1]
    expect AssertionDefect:
      discard loadWorld(negative)

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
        "tags": newJNull(), "tribe": newJNull(), "tagging": false,
        "tradeFactor": 0, "marginalRateOfSubstitution": 1, "tradeVolume": 0,
        "sugarPrice": 0, "spicePrice": 0, "lastTradeTimestep": -1,
        "lastTradePartners": 0, "diseaseProtectionChance": 0,
        "immuneSystem": newJNull(), "diseases": [],
        "born": 0, "startingSugar": 5, "startingSpice": 0, "sex": "female",
        "fertilityAge": 10, "infertilityAge": 20, "inheritancePolicy": "none",
        "lendingFactor": 0, "baseInterestRate": 0, "loanDuration": 0,
        "sugarMeanIncome": 1, "spiceMeanIncome": 1,
        "startingImmuneSystem": newJNull(), "racialTags": newJNull(),
        "fatherId": newJNull(), "motherId": newJNull(), "childrenIds": [], "mateIds": [],
        "lastMovedTimestep": -1, "lastReproducedTimestep": -1, "lastMates": 0,
        "lastLendedTimestep": -1, "lastLoans": 0, "creditorLoans": [], "debtorLoans": [],
        "friends": [], "lastCombatTimestep": -1, "conflictHappiness": 0,
        "familyHappiness": 0, "healthHappiness": 0, "socialHappiness": 0,
        "wealthHappiness": 0, "happiness": 0,
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
        "tags": newJNull(), "tribe": newJNull(), "tagging": false,
        "tradeFactor": 0, "marginalRateOfSubstitution": 1, "tradeVolume": 0,
        "sugarPrice": 0, "spicePrice": 0, "lastTradeTimestep": -1,
        "lastTradePartners": 0, "diseaseProtectionChance": 0,
        "immuneSystem": newJNull(), "diseases": [],
        "born": 0, "startingSugar": 5, "startingSpice": 0, "sex": "female",
        "fertilityAge": 10, "infertilityAge": 20, "inheritancePolicy": "none",
        "lendingFactor": 0, "baseInterestRate": 0, "loanDuration": 0,
        "sugarMeanIncome": 1, "spiceMeanIncome": 1,
        "startingImmuneSystem": newJNull(), "racialTags": newJNull(),
        "fatherId": newJNull(), "motherId": newJNull(), "childrenIds": [], "mateIds": [],
        "lastMovedTimestep": -1, "lastReproducedTimestep": -1, "lastMates": 0,
        "lastLendedTimestep": -1, "lastLoans": 0, "creditorLoans": [], "debtorLoans": [],
        "friends": [], "lastCombatTimestep": -1, "conflictHappiness": 0,
        "familyHappiness": 0, "healthHappiness": 0, "socialHappiness": 0,
        "wealthHappiness": 0, "happiness": 0,
      },
    ]
    node["orderedCandidates"] = %*[[[1, 1]], [[0, 1]]]
    node["orderedNeighbors"] = %*[[1, 1, 1, 1], [0, 0, 0, 0]]
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
    node["agents"][0]["tags"] = %*[0]
    node["agents"][0]["tribe"] = %0
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

  test "combat caps each loot resource and records the victim":
    var node = initialSnapshot()
    node["maxCombatLoot"] = %2
    node["maxTribes"] = %2
    node["sugarRegrowRate"] = %0
    node["liveOrder"] = %*[20, 10]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
    ]
    var attacker = node["agents"][0].copy()
    attacker["sugar"] = %10
    attacker["spice"] = %10
    attacker["sugarMetabolism"] = %0
    attacker["aggressionFactor"] = %1
    attacker["tags"] = %*[0]
    attacker["tribe"] = %1
    var prey = attacker.copy()
    prey["id"] = %20
    prey["seat"] = %1
    prey["x"] = %1
    prey["sugar"] = %4
    prey["spice"] = %3
    prey["aggressionFactor"] = %0
    prey["tags"] = %*[1]
    prey["tribe"] = %0
    node["agents"] = %*[attacker, prey]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 1
    check world.agents[0].id == 10
    check world.agents[0].x == 1
    check world.agents[0].sugar == 12
    check world.agents[0].spice == 12
    check world.deaths.len == 1
    check world.deaths[0].id == 20
    check world.deaths[0].cause == "combat"

  test "tagging preserves duplicate neighbor draws and recomputes tribe":
    var node = initialSnapshot()
    node["width"] = %2
    node["maxTribes"] = %2
    node["liveOrder"] = %*[20, 10]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
    ]
    var tagger = node["agents"][0].copy()
    tagger["movement"] = %0
    tagger["sugarMetabolism"] = %0
    tagger["tags"] = %*[0]
    tagger["tribe"] = %1
    tagger["tagging"] = %true
    var target = tagger.copy()
    target["id"] = %20
    target["seat"] = %1
    target["x"] = %1
    target["tags"] = %*[1]
    target["tribe"] = %0
    target["tagging"] = %false
    node["agents"] = %*[tagger, target]
    node["orderedCandidates"] = %*[[[1, 1]], [[0, 1]]]
    node["orderedNeighbors"] = %*[[1, 1, 1, 1], [0, 0, 0, 0]]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents[1].tags == @[0]
    check world.agents[1].tribe == 1

  test "reproduction creates and harvests one child with parent costs":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["liveOrder"] = %*[10, 20]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
      {"sugar": 2, "maxSugar": 2, "spice": 3, "maxSpice": 3, "occupantId": newJNull()},
    ]
    var mother = node["agents"][0].copy()
    mother["movement"] = %0
    mother["sugarMetabolism"] = %0
    mother["sugar"] = %10
    mother["spice"] = %10
    mother["startingSugar"] = %10
    mother["startingSpice"] = %10
    mother["age"] = %10
    mother["fertilityAge"] = %10
    mother["infertilityAge"] = %20
    mother["fertilityFactor"] = %1
    mother["sex"] = %"female"
    mother["lastTradePartners"] = %2
    var father = mother.copy()
    father["id"] = %20
    father["seat"] = %1
    father["x"] = %1
    father["sex"] = %"male"
    node["agents"] = %*[mother, father]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 3
    check world.nextAgentId == 22
    check world.agents[2].id == 21
    check world.agents[2].born == 1
    check world.agents[2].age == 0
    check world.agents[2].lastMovedTimestep == 1
    check world.agents[2].lastTradePartners == 0
    check world.agents[2].sugar == 12
    check world.agents[2].spice == 13
    check world.agents[0].sugar == 5
    check world.agents[1].sugar == 5

  test "children inheritance clamps and transfers holdings on aging death":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["liveOrder"] = %*[10, 20]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
    ]
    var parent = node["agents"][0].copy()
    parent["movement"] = %0
    parent["sugarMetabolism"] = %0
    parent["sugar"] = %8
    parent["spice"] = %4
    parent["maxAge"] = %1
    parent["inheritancePolicy"] = %"children"
    parent["childrenIds"] = %*[20]
    var child = parent.copy()
    child["id"] = %20
    child["seat"] = %1
    child["x"] = %1
    child["sugar"] = %10
    child["spice"] = %10
    child["maxAge"] = %(-1)
    child["inheritancePolicy"] = %"none"
    child["childrenIds"] = %*[]
    node["agents"] = %*[parent, child]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents.len == 1
    check world.agents[0].id == 20
    check world.agents[0].sugar == 18
    check world.agents[0].spice == 14

  test "lending originates mirrored interest-bearing records":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["liveOrder"] = %*[10, 20]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
    ]
    var lender = node["agents"][0].copy()
    lender["movement"] = %0
    lender["sugarMetabolism"] = %0
    lender["spiceMetabolism"] = %0
    lender["sugar"] = %20
    lender["spice"] = %20
    lender["startingSugar"] = %10
    lender["startingSpice"] = %10
    lender["fertilityAge"] = %0
    lender["infertilityAge"] = %20
    lender["fertilityFactor"] = %0
    lender["lendingFactor"] = %1
    lender["baseInterestRate"] = %0.1
    lender["loanDuration"] = %5
    var borrower = lender.copy()
    borrower["id"] = %20
    borrower["seat"] = %1
    borrower["x"] = %1
    borrower["sugar"] = %5
    borrower["spice"] = %5
    borrower["lendingFactor"] = %0
    borrower["sugarMeanIncome"] = %10
    borrower["spiceMeanIncome"] = %10
    node["agents"] = %*[lender, borrower]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents[0].debtorLoans.len == 1
    check world.agents[1].creditorLoans.len == 1
    check world.agents[0].debtorLoans[0].sugarLoan == 5.5
    check world.agents[0].sugar == 15
    check world.agents[1].sugar == 10


    var mismatched = world.snapshot()
    mismatched["agents"][1]["creditorLoans"].add(
      mismatched["agents"][1]["creditorLoans"][0].copy())
    expect AssertionDefect:
      discard loadWorld(mismatched)

    var negativeLoan = world.snapshot()
    negativeLoan["agents"][1]["creditorLoans"][0]["sugarLoan"] = %(-1)
    expect AssertionDefect:
      discard loadWorld(negativeLoan)

  test "dead creditor debt transfers to living children at maturity":
    var node = initialSnapshot()
    node["sugarRegrowRate"] = %0
    node["liveOrder"] = %*[10, 20]
    node["cells"] = %*[
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 10},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": 20},
      {"sugar": 0, "maxSugar": 0, "spice": 0, "maxSpice": 0, "occupantId": newJNull()},
    ]
    var debtor = node["agents"][0].copy()
    debtor["movement"] = %0
    debtor["sugarMetabolism"] = %0
    debtor["spiceMetabolism"] = %0
    debtor["lastMovedTimestep"] = %0
    debtor["creditorLoans"] = %*[
      {"creditorId": 5, "debtorId": 10, "sugarLoan": 4, "spiceLoan": 2,
       "loanDuration": 1, "loanOrigin": 0},
    ]
    var heir = debtor.copy()
    heir["id"] = %20
    heir["seat"] = %1
    heir["x"] = %1
    heir["creditorLoans"] = %*[]
    node["agents"] = %*[debtor, heir]
    node["creditorTombstones"] = %*[
      {"id": 5, "inheritancePolicy": "children", "childrenIds": [20]},
    ]
    var world = loadWorld(node)
    world.stepOne()
    check world.creditorTombstones.len == 0
    check world.agents[0].creditorLoans.len == 1
    check world.agents[0].creditorLoans[0].creditorId == 20
    check world.agents[0].creditorLoans[0].duration == 1
    check world.agents[1].debtorLoans == world.agents[0].creditorLoans

    node["creditorTombstones"][0]["inheritancePolicy"] = %"none"
    var cancelled = loadWorld(node)
    cancelled.stepOne()
    check cancelled.creditorTombstones.len == 0
    check cancelled.agents[0].creditorLoans.len == 0
    check cancelled.agents[1].debtorLoans.len == 0

  test "stale dead-debtor records survive snapshots and are removed":
    var node = initialSnapshot()
    node["agents"][0]["debtorLoans"] = %*[
      {"creditorId": 10, "debtorId": 99, "sugarLoan": 1, "spiceLoan": 1,
       "loanDuration": 1, "loanOrigin": 0},
    ]
    var world = loadWorld(node)
    world.stepOne()
    check world.agents[0].debtorLoans.len == 0
