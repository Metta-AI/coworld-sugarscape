import std/[json, unittest]

import sugarscape/configuration

suite "DTL configuration compatibility":
  test "command-line defaults match the pinned Python implementation":
    let config = parseConfiguration("{}")

    check config["agentDecisionModels"] == %* ["none"]
    check config["agentMaxAge"] == %* [-1, -1]
    check config["agentMovement"] == %* [1, 6]
    check config["environmentHeight"].getInt() == 50
    check config["environmentWidth"].getInt() == 50
    check config["headlessMode"].getBool() == false
    check config["seed"].getInt() == -1
    check config["startingAgents"].getInt() == 250
    check config["timesteps"].getInt() == 200

  test "sugarscapeOptions is the optional overlay object":
    let config = parseConfiguration(
      """{"sugarscapeOptions":{"seed":12345,"startingAgents":7,"unknown":9}}"""
    )

    check config["seed"].getInt() == 12345
    check config["startingAgents"].getInt() == 7
    check not config.hasKey("unknown")

  test "legacy ethical options preserve upstream alias behavior":
    let config = parseConfiguration(
      """{"agentEthicalTheory":"bentham","agentEthicalFactor":[0.25,0.75]}"""
    )

    check config["agentDecisionModel"].getStr() == "bentham"
    check config["agentDecisionModelFactor"] == %* [0.25, 0.75]

  test "numeric lists sort and ordinary negative values clamp to zero":
    let config = parseConfiguration(
      """{"agentMovement":[6,-2],"agentTradeFactor":[2,1]}"""
    )

    check config["agentMovement"] == %* [0, 6]
    check config["agentTradeFactor"] == %* [1, 2]
