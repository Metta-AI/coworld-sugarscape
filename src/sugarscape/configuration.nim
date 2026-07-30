import std/[algorithm, json, os]

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

proc normalizePeaks(config: JsonNode, name, maximumName: string) =
  let maximum = config[maximumName].getInt()
  var peaks = config[name]
  for peak in peaks.mitems:
    if peak.len < 3:
      peak.add(newJInt(maximum))
    if peak[2].getInt() > maximum:
      peak.elems[2] = newJInt(maximum)

proc normalizeSpecialCases(config: JsonNode) =
  for name in [
    "diseaseTimeframe",
    "environmentPollutionDiffusionTimeframe",
    "environmentPollutionTimeframe",
  ]:
    config.normalizeTimeframe(name)

  config.normalizePeaks("environmentSpicePeaks", "environmentMaxSpice")
  config.normalizePeaks("environmentSugarPeaks", "environmentMaxSugar")

  if config["environmentStartingQuadrants"].len == 0:
    config["environmentStartingQuadrants"] = %* [1, 2, 3, 4]
  if config["environmentTribePerQuadrant"].getBool():
    config["environmentMaxTribes"] =
      newJInt(config["environmentStartingQuadrants"].len)

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
  result.normalizeSpecialCases()

proc loadConfiguration*(path: string): JsonNode =
  parseConfiguration(readFile(path))
