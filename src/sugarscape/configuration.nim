import std/[algorithm, json, math, os, strutils]

import ./py_random

const
  DefaultsText = staticRead(currentSourcePath().parentDir / "defaults.json")
  NegativeValuesAllowed = [
    "agentDecisionModelAgeismFactor",
    "agentDecisionModelRacismFactor",
    "agentDecisionModelSexismFactor",
    "agentDecisionModelTribalFactor",
    "agentMaxAge",
    "agentSelfishnessFactor",
    "diseaseAggressionPenalty",
    "diseaseFertilityPenalty",
    "diseaseFriendlinessPenalty",
    "diseaseHappinessPenalty",
    "diseaseMovementPenalty",
    "diseaseSpiceMetabolismPenalty",
    "diseaseSugarMetabolismPenalty",
    "diseaseTimeframe",
    "diseaseVisionPenalty",
    "environmentAgeistAbsoluteRanges",
    "environmentAgeistRelativeRange",
    "environmentEquator",
    "environmentPollutionDiffusionTimeframe",
    "environmentPollutionTimeframe",
    "environmentMaxSpice",
    "environmentMaxSugar",
    "interfaceHeight",
    "interfaceWidth",
    "seed",
    "timesteps",
  ]

proc compareJson(left, right: JsonNode): int =
  if left.kind in {JInt, JFloat} and right.kind in {JInt, JFloat}:
    return cmp(left.getFloat(), right.getFloat())
  if left.kind == JString and right.kind == JString:
    return cmp(left.getStr(), right.getStr())
  if left.kind == JArray and right.kind == JArray:
    let commonLength = min(left.len, right.len)
    for index in 0 ..< commonLength:
      result = compareJson(left[index], right[index])
      if result != 0:
        return
    return cmp(left.len, right.len)
  cmp($left, $right)

proc isNegativeAllowed(name: string): bool =
  for allowed in NegativeValuesAllowed:
    if name == allowed:
      return true

proc isTimeframe(name: string): bool =
  name in [
    "diseaseTimeframe",
    "environmentPollutionDiffusionTimeframe",
    "environmentPollutionTimeframe",
  ]

proc normalizeListsAndNegatives(config: JsonNode) =
  var mutableConfig = config
  for name, value in mutableConfig.mpairs:
    if value.kind == JArray:
      if value.len == 0:
        continue
      if not isTimeframe(name):
        value.elems.sort(compareJson)
      if not isNegativeAllowed(name) and value[0].kind in {JInt, JFloat}:
        for item in value.mitems:
          if item.getFloat() < 0:
            item = newJInt(0)
    elif value.kind in {JInt, JFloat}:
      if not isNegativeAllowed(name) and value.getFloat() < 0:
        value = newJInt(0)

proc normalizeTimeframe(config: JsonNode, name: string) =
  var timeframe = config[name]
  if timeframe[0].getInt() > timeframe[1].getInt() and
      timeframe[1].getInt() >= 0:
    swap(timeframe.elems[0], timeframe.elems[1])
  if timeframe[0].getInt() < 0:
    timeframe.elems[0] = newJInt(0)
  if timeframe[1].getInt() < 0:
    timeframe.elems[1] = config["timesteps"]

proc randomInteger(rng: var PyRandom, minimum, maximum: int): int =
  minimum + int(rng.randBelow(uint64(maximum - minimum + 1)))

proc normalizeSpecialCases*(config: JsonNode, rng: var PyRandom) =
  ## Match ``verifyConfiguration`` after CPython has seeded its global RNG.
  ## Validation order is observable because malformed maxima and peak
  ## coordinates consume draws before the environment is generated.
  for name in [
    "diseaseTimeframe",
    "environmentPollutionDiffusionTimeframe",
    "environmentPollutionTimeframe",
  ]:
    config.normalizeTimeframe(name)

  if config["experimentalGroup"].kind == JString:
    let group = config["experimentalGroup"].getStr()
    if "ageRange" in group:
      let suffix = group[group.find("ageRange") + "ageRange".len .. ^1]
      if suffix.len == 0 or not suffix[0].isDigit:
        config["experimentalGroup"] = newJString("ageInGroup")
    if "disease" in group:
      let suffix = group[group.find("disease") + "disease".len .. ^1]
      if suffix.len == 0 or not suffix[0].isDigit:
        config["experimentalGroup"] = newJString("sick")
    if "race" in group:
      let suffix = group[group.find("race") + "race".len .. ^1]
      if suffix.len == 0 or not suffix[0].isDigit:
        config["experimentalGroup"] = newJString("raceInGroup")

  if config["environmentMaxSpice"].getInt() < 0:
    config["environmentMaxSpice"] =
      newJInt(rng.randomInteger(1, 10))
  if config["environmentMaxSugar"].getInt() < 0:
    config["environmentMaxSugar"] =
      newJInt(rng.randomInteger(1, 10))

  for specification in [
    ("environmentSpicePeaks", "environmentMaxSpice"),
    ("environmentSugarPeaks", "environmentMaxSugar"),
  ]:
    let
      peakName = specification[0]
      maximumName = specification[1]
      maximum = config[maximumName].getInt()
      width = config["environmentWidth"].getInt()
      height = config["environmentHeight"].getInt()
    var peaks = config[peakName]
    for peak in peaks.mitems:
      if peak.len < 3:
        peak.add(newJInt(maximum))
      if peak[0].getInt() < 0 or peak[0].getInt() > width:
        peak.elems[0] = newJInt(rng.randomInteger(0, width - 1))
      if peak[1].getInt() < 0 or peak[1].getInt() > height:
        peak.elems[1] = newJInt(rng.randomInteger(0, height - 1))
      if peak[2].getInt() < 0:
        peak.elems[2] = newJInt(rng.randomInteger(1, maximum))
      elif peak[2].getInt() > maximum:
        peak.elems[2] = newJInt(maximum)

  let quadrantFactor = config["environmentQuadrantSizeFactor"].getFloat()
  if quadrantFactor > 1 or quadrantFactor < 0:
    config["environmentQuadrantSizeFactor"] = newJInt(1)

  if config["environmentStartingQuadrants"].len == 0:
    config["environmentStartingQuadrants"] = %* [1, 2, 3, 4]
  if config["environmentTribePerQuadrant"].getBool():
    config["environmentMaxTribes"] =
      newJInt(config["environmentStartingQuadrants"].len)

  let
    totalCells =
      float64(
        config["environmentHeight"].getInt() *
        config["environmentWidth"].getInt()
      ) *
      pow(config["environmentQuadrantSizeFactor"].getFloat(), 2) *
      float64(config["environmentStartingQuadrants"].len) /
      4.0
  if config["startingAgents"].getFloat() > totalCells:
    config["startingAgents"] = newJFloat(totalCells)

  if config["timesteps"].getInt() < 0:
    config["timesteps"] = newJInt(high(int64))

  for name in [
    "agentDecisionModelAgeismFactor",
    "agentDecisionModelRacismFactor",
    "agentDecisionModelSexismFactor",
    "agentDecisionModelTribalFactor",
    "agentSelfishnessFactor",
  ]:
    if config[name][0].getFloat() < 0:
      config[name] = %* [-1, -1]
    elif config[name][1].getFloat() > 1:
      config[name].elems[1] = newJInt(1)

  if config["agentMaxAge"][0].getInt() < 0:
    config["agentMaxAge"] = %* [-1, -1]

  for name in [
    "agentDynamicDecisionModelFactor",
    "agentDynamicSocialPressureFactor",
  ]:
    if config[name][0].getFloat() < 0:
      config[name] = %* [-1, -1]
    elif config[name][1].getFloat() > 1:
      config[name].elems[1] = newJFloat(1.0)

  if config["agentTagStringLength"].getInt() > 0 and
      config["environmentMaxTribes"].getInt() >
      config["agentTagStringLength"].getInt():
    config["environmentMaxTribes"] =
      config["agentTagStringLength"].copy()

  config["environmentMaxRaces"] =
    newJInt(min(25, config["environmentMaxRaces"].getInt()))
  config["environmentMaxTribes"] =
    newJInt(min(25, config["environmentMaxTribes"].getInt()))

  var validAgeRanges = newJArray()
  for ageRange in config["environmentAgeistAbsoluteRanges"]:
    let
      minimum = ageRange[0].getInt()
      maximum = ageRange[1].getInt()
    if minimum >= -1 and maximum >= -1 and
        (minimum <= maximum or maximum == -1):
      validAgeRanges.add(ageRange.copy())
  config["environmentAgeistAbsoluteRanges"] = validAgeRanges

  if config["environmentAgeistRelativeRange"].getFloat() < 0 and
      config["environmentAgeistRelativeRange"].getFloat() != -1:
    config["environmentAgeistRelativeRange"] = newJInt(-1)
  if config["environmentAgeistAbsoluteRanges"].len == 0 and
      config["environmentAgeistRelativeRange"].getFloat() == -1 and
      config["agentDecisionModelAgeismFactor"] != %* [-1, -1]:
    config["agentDecisionModelAgeismFactor"] = %* [-1, -1]

  let maxRaces = config["environmentMaxRaces"].getInt()
  var inGroupRaces = newJArray()
  for race in config["environmentInGroupRaces"]:
    if race.getInt() < maxRaces:
      inGroupRaces.add(race.copy())
  config["environmentInGroupRaces"] = inGroupRaces

  if config["startingDiseasesPerAgent"] != %* [0, 0]:
    let maximumDiseases = config["startingDiseases"].getInt()
    var diseaseRange = newJArray()
    for count in config["startingDiseasesPerAgent"]:
      diseaseRange.add(newJInt(min(maximumDiseases, max(0, count.getInt()))))
    diseaseRange.elems.sort(compareJson)
    config["startingDiseasesPerAgent"] = diseaseRange

  if config["logfile"].kind == JString and
      config["logfile"].getStr().len == 0:
    config["logfile"] = newJNull()
  if config["agentLogfile"].kind == JString and
      config["agentLogfile"].getStr().len == 0:
    config["agentLogfile"] = newJNull()

  if config["agentDecisionModel"].kind == JString:
    config["agentDecisionModels"] = %* [config["agentDecisionModel"].getStr()]
  elif config["agentDecisionModel"].kind == JArray:
    config["agentDecisionModels"] = config["agentDecisionModel"].copy()
  if config["agentDecisionModels"].kind == JString:
    config["agentDecisionModels"] = %*[
      config["agentDecisionModels"].getStr()
    ]

  if config["experimentalGroup"].kind == JString and
      config["experimentalGroup"].getStr().len == 0:
    config["experimentalGroup"] = newJNull()
  if config["experimentalGroup"].kind == JString:
    let group = config["experimentalGroup"].getStr()
    var recognized = group in [
      "ageInGroup", "depressed", "female", "male",
      "raceInGroup", "sick",
    ]
    for model in config["agentDecisionModels"]:
      if model.getStr() == group:
        recognized = true
    if not recognized and "ageRange" notin group and
        "disease" notin group and "race" notin group:
      config["experimentalGroup"] = newJNull()

proc parseConfiguration*(input: string): JsonNode =
  result = parseJson(DefaultsText)
  var options = parseJson(input)
  if options.hasKey("sugarscapeOptions"):
    options = options["sugarscapeOptions"]

  if options.hasKey("agentEthicalTheory"):
    options["agentDecisionModel"] = options["agentEthicalTheory"]
  if options.hasKey("agentEthicalFactor"):
    options["agentDecisionModelFactor"] = options["agentEthicalFactor"]

  for name, value in options:
    if result.hasKey(name):
      result[name] = value

  result.normalizeListsAndNegatives()

proc loadConfiguration*(path: string): JsonNode =
  parseConfiguration(readFile(path))
