import std/[json, math, strutils]

import ./agents
import ./py_random

type
  Disease* = object
    id*: int
    aggressionPenalty*, fertilityPenalty*: float64
    friendlinessPenalty*, happinessPenalty*: float64
    movementPenalty*, spiceMetabolismPenalty*: float64
    sugarMetabolismPenalty*, transmissionChance*: float64
    visionPenalty*: float64
    spiceMetabolismPenaltyIsFloat*: bool
    sugarMetabolismPenaltyIsFloat*: bool
    metabolismPenaltyIsFloat*: bool
    incubationPeriod*, startTimestep*: int
    tags*: seq[int]
    recoverable*: bool

proc decimalPlaces(value: JsonNode): int =
  if value.kind != JFloat:
    return 0
  let text = $value
  let decimal = text.find('.')
  if decimal < 0:
    return 0
  let exponent = text.find({'e', 'E'})
  if exponent < 0: text.len - decimal - 1
  else: exponent - decimal - 1

proc roundTo(value: float64, places: int): float64 =
  if places == 0:
    return round(value)
  parseFloat(formatFloat(value, ffDecimal, places))

proc values(config: JsonNode, name: string, count: int): seq[float64] =
  let
    bounds = config[name]
    places = max(decimalPlaces(bounds[0]), decimalPlaces(bounds[1]))
    increment = pow(10.0, float64(-places))
    maximum = bounds[1].getFloat()
  var current = bounds[0].getFloat()
  for _ in 0 ..< count:
    result.add(current)
    current = roundTo(current + increment, places)
    if current > maximum:
      current = bounds[0].getFloat()

proc shuffledValues(
    config: JsonNode,
    configName, hashName: string,
    count, timestep: int,
): seq[float64] =
  result = values(config, configName, count)
  var rng: PyRandom
  rng.seedFromMd5(hashName, uint64(timestep))
  rng.shuffle(result)

proc createDiseases*(
    config: JsonNode,
    count, timestep: int,
    rng: var PyRandom,
): seq[Disease] =
  if count <= 0:
    return

  var
    aggression = shuffledValues(
      config, "diseaseAggressionPenalty", "aggressionPenalty", count, timestep
    )
    fertility = shuffledValues(
      config, "diseaseFertilityPenalty", "fertilityPenalty", count, timestep
    )
    friendliness = shuffledValues(
      config,
      "diseaseFriendlinessPenalty",
      "friendlinessPenalty",
      count,
      timestep,
    )
    happiness = shuffledValues(
      config, "diseaseHappinessPenalty", "happinessPenalty", count, timestep
    )
    incubation = shuffledValues(
      config, "diseaseIncubationPeriod", "incubationPeriod", count, timestep
    )
    movement = shuffledValues(
      config, "diseaseMovementPenalty", "movementPenalty", count, timestep
    )
    spiceMetabolism = shuffledValues(
      config,
      "diseaseSpiceMetabolismPenalty",
      "spiceMetabolismPenalty",
      count,
      timestep,
    )
    start = shuffledValues(
      config, "diseaseTimeframe", "startTimestep", count, timestep
    )
    sugarMetabolism = shuffledValues(
      config,
      "diseaseSugarMetabolismPenalty",
      "sugarMetabolismPenalty",
      count,
      timestep,
    )
    tagLengths = values(config, "diseaseTagStringLength", count)
    transmission = shuffledValues(
      config,
      "diseaseTransmissionChance",
      "transmissionChance",
      count,
      timestep,
    )
    vision = shuffledValues(
      config, "diseaseVisionPenalty", "visionPenalty", count, timestep
    )
    tags = newSeq[seq[int]](count)

  # Disease tag generation is the only endowment work that consumes the
  # simulation RNG. Per-field shuffles above intentionally use isolated RNGs.
  for index in 0 ..< count:
    tags[index] = newSeq[int](int(tagLengths[index]))
    for bit in tags[index].mitems:
      bit = int(rng.randBelow(2))
  rng.shuffle(tags)

  result = newSeq[Disease](count)
  for index in 0 ..< count:
    result[index] = Disease(
      id: index,
      aggressionPenalty: aggression.pop(),
      fertilityPenalty: fertility.pop(),
      friendlinessPenalty: friendliness.pop(),
      happinessPenalty: happiness.pop(),
      incubationPeriod: int(incubation.pop()),
      movementPenalty: movement.pop(),
      spiceMetabolismPenalty: spiceMetabolism.pop(),
      startTimestep: int(start.pop()),
      sugarMetabolismPenalty: sugarMetabolism.pop(),
      tags: tags.pop(),
      transmissionChance: transmission.pop(),
      visionPenalty: vision.pop(),
      metabolismPenaltyIsFloat:
        config["diseaseSpiceMetabolismPenalty"][0].kind == JFloat or
        config["diseaseSpiceMetabolismPenalty"][1].kind == JFloat or
        config["diseaseSugarMetabolismPenalty"][0].kind == JFloat or
        config["diseaseSugarMetabolismPenalty"][1].kind == JFloat,
      spiceMetabolismPenaltyIsFloat:
        config["diseaseSpiceMetabolismPenalty"][0].kind == JFloat or
        config["diseaseSpiceMetabolismPenalty"][1].kind == JFloat,
      sugarMetabolismPenaltyIsFloat:
        config["diseaseSugarMetabolismPenalty"][0].kind == JFloat or
        config["diseaseSugarMetabolismPenalty"][1].kind == JFloat,
      recoverable: true,
    )

proc createZombieVirus*(id: int): Disease =
  Disease(
    id: id,
    aggressionPenalty: 100000,
    fertilityPenalty: -1,
    incubationPeriod: 3,
    spiceMetabolismPenalty: -10,
    sugarMetabolismPenalty: -10,
    transmissionChance: 0.85,
    visionPenalty: 1,
    recoverable: false,
  )

proc nearestImmuneMatch*(
    agent: Agent,
    disease: Disease,
): tuple[distance, startIndex, endIndex: int] =
  result = (disease.tags.len, 0, disease.tags.len - 1)
  if disease.tags.len == 0:
    result.distance = 1
    return
  if agent.immuneSystem.len == 0:
    return
  for startIndex in 0 ..< agent.immuneSystem.len - disease.tags.len:
    var distance = 0
    for offset, tag in disease.tags:
      if agent.immuneSystem[startIndex + offset] != tag:
        inc distance
    if distance < result.distance:
      result = (
        distance,
        startIndex,
        startIndex + disease.tags.len - 1,
      )

proc trigger*(agent: var Agent, disease: Disease) =
  agent.aggressionFactorModifier += disease.aggressionPenalty
  agent.fertilityFactorModifier += disease.fertilityPenalty
  agent.friendlinessModifier += disease.friendlinessPenalty
  agent.happinessModifier += disease.happinessPenalty
  agent.movementModifier += disease.movementPenalty
  agent.spiceMetabolismModifier += disease.spiceMetabolismPenalty
  agent.sugarMetabolismModifier += disease.sugarMetabolismPenalty
  agent.visionModifier += disease.visionPenalty
  agent.metabolismModifierIsFloat =
    agent.metabolismModifierIsFloat or disease.metabolismPenaltyIsFloat
  agent.spiceMetabolismModifierIsFloat =
    agent.spiceMetabolismModifierIsFloat or
    disease.spiceMetabolismPenaltyIsFloat
  agent.sugarMetabolismModifierIsFloat =
    agent.sugarMetabolismModifierIsFloat or
    disease.sugarMetabolismPenaltyIsFloat

proc recover*(agent: var Agent, disease: Disease) =
  agent.aggressionFactorModifier -= disease.aggressionPenalty
  agent.fertilityFactorModifier -= disease.fertilityPenalty
  agent.friendlinessModifier -= disease.friendlinessPenalty
  agent.happinessModifier -= disease.happinessPenalty
  agent.movementModifier -= disease.movementPenalty
  agent.spiceMetabolismModifier -= disease.spiceMetabolismPenalty
  agent.sugarMetabolismModifier -= disease.sugarMetabolismPenalty
  agent.visionModifier -= disease.visionPenalty
