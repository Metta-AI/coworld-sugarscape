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

  test "default Coworld game enables the dual-resource conflict economy":
    let
      localConfig = parseFile("config.json")
      manifest = parseFile("coworld_manifest.json")
      defaultConfig = manifest["variants"][0]["game_config"]

    for config in [localConfig, defaultConfig]:
      check config["environmentMaxSugar"].getInt() == 4
      check config["environmentMaxSpice"].getInt() == 4
      check config["environmentSugarRegrowRate"].getInt() == 1
      check config["environmentSpiceRegrowRate"].getInt() == 1
      check config["agentStartingSugar"] == %* [10, 40]
      check config["agentStartingSpice"] == %* [10, 40]
      check config["agentSugarMetabolism"] == %* [1, 4]
      check config["agentSpiceMetabolism"] == %* [1, 4]
      check config["agentTradeFactor"] == %* [1, 1]
      check config["agentAggressionFactor"] == %* [1, 1]
      check config["onePlayerPerAgent"].getBool()
      check config["playerTribes"].getBool()
      check config["players"].len == config["startingAgents"].getInt()
      check config["agentDecisionModels"] == %* ["none"]
      check not config.hasKey("slots")
      check config["environmentMaxCombatLoot"].getInt() == 2
      check config["environmentPollutionTimeframe"] == %* [100, -1]
      check config["environmentPollutionDiffusionTimeframe"] == %* [100, -1]

    check defaultConfig["timesteps"].getInt() == 2000
    check defaultConfig["startingAgents"].getInt() == 64
    check manifest["game"]["config_schema"]["properties"]["tokens"]["maxItems"].getInt() == 64
    check manifest["game"]["config_schema"]["properties"]["players"]["maxItems"].getInt() == 64
    check manifest["game"]["config_schema"]["required"] ==
      %* ["tokens", "players"]

    let certification = manifest["certification"]
    check certification["players"].len == 16
    check certification["game_config"]["startingAgents"].getInt() == 16
    check certification["game_config"]["players"].len == 16
    check certification["game_config"]["onePlayerPerAgent"].getBool()
    check manifest["players_per_user"].getInt() == 2
