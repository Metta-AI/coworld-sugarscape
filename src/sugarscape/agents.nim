import std/[json, math, strutils]

import ./environment
import ./py_random

type
  MoveOption* = object
    cell*: int
    welfare*: float64

  Agent* = object
    id*: int
    born*: int
    cell*: int
    alive*: bool
    age*: int
    maxAge*: int
    movement*, vision*: int
    lookaheadFactor*: float64
    sugar*, spice*: float64
    startingSugar*, startingSpice*: float64
    sugarMetabolism*, spiceMetabolism*: float64
    sex*: string
    decisionModel*: string
    aggressionFactor*, decisionModelFactor*: float64
    decisionModelAgeismFactor*, decisionModelRacismFactor*: float64
    decisionModelSexismFactor*, selfishnessFactor*: float64
    depressed*: bool
    maxFriends*: int
    lastMovedTimestep*: int
    lastSugar*, lastSpice*: float64
    lastMoveRank*, lastValidMoves*: int
    lastMoveOptimal*: bool
    cellsInRange*: seq[RangeEntry]
    movementNeighborhood*: seq[int]
    validMoves*: seq[MoveOption]
    happiness*, conflictHappiness*, familyHappiness*: float64
    healthHappiness*, socialHappiness*, wealthHappiness*: float64

proc decimalPlaces(value: JsonNode): int =
  if value.kind != JFloat:
    return 0
  let text = $value
  let decimal = text.find('.')
  if decimal < 0:
    return 0
  let exponent = text.find({'e', 'E'})
  if exponent < 0:
    text.len - decimal - 1
  else:
    exponent - decimal - 1

proc roundTo(value: float64, places: int): float64 =
  if places == 0:
    return round(value)
  let scale = pow(10.0, float64(places))
  round(value * scale) / scale

proc endowmentValues(config: JsonNode, name: string, count: int): seq[float64] =
  let
    bounds = config[name]
    minimum = bounds[0].getFloat()
    maximum = bounds[1].getFloat()
    places = max(decimalPlaces(bounds[0]), decimalPlaces(bounds[1]))
    increment = pow(10.0, float64(-places))
  var current = minimum
  result = newSeqOfCap[float64](count)
  for _ in 0 ..< count:
    result.add(current)
    current = roundTo(current + increment, places)
    if current > maximum:
      current = minimum

proc shuffledEndowments(
    config: JsonNode,
    configName, hashName: string,
    count, timestep: int,
): seq[float64] =
  result = endowmentValues(config, configName, count)
  var localRng: PyRandom
  localRng.seedFromMd5(hashName, uint64(timestep))
  localRng.shuffle(result)

proc activeQuadrants(config: JsonNode, world: Environment): seq[seq[int]] =
  let
    quadrantWidth = int(
      floor(
        float64(world.width) / 2.0 *
        config["environmentQuadrantSizeFactor"].getFloat()
      )
    )
    quadrantHeight = int(
      floor(
        float64(world.height) / 2.0 *
        config["environmentQuadrantSizeFactor"].getFloat()
      )
    )
  for quadrant in config["environmentStartingQuadrants"]:
    case quadrant.getInt()
    of 1:
      var cells: seq[int]
      for y in 0 ..< quadrantHeight:
        for x in 0 ..< quadrantWidth:
          cells.add(world.cellId(x, y))
      result.add(cells)
    of 2:
      var cells: seq[int]
      for y in 0 ..< quadrantHeight:
        for x in world.width - quadrantWidth ..< world.width:
          cells.add(world.cellId(x, y))
      result.add(cells)
    of 3:
      var cells: seq[int]
      for y in world.height - quadrantHeight ..< world.height:
        for x in world.width - quadrantWidth ..< world.width:
          cells.add(world.cellId(x, y))
      result.add(cells)
    of 4:
      var cells: seq[int]
      for y in world.height - quadrantHeight ..< world.height:
        for x in 0 ..< quadrantWidth:
          cells.add(world.cellId(x, y))
      result.add(cells)
    else:
      discard

proc createInitialAgents*(
    config: JsonNode,
    world: var Environment,
    rng: var PyRandom,
): seq[Agent] =
  let count = config["startingAgents"].getInt()
  if count == 0:
    return

  var depressionFactors = newSeq[int](count)
  let depressedCount =
    int(ceil(float64(count) * config["agentDepressionPercentage"].getFloat()))
  for index in 0 ..< depressedCount:
    depressionFactors[index] = 1
  rng.shuffle(depressionFactors)

  var sexes = newSeq[string](count)
  let ratio = config["agentMaleToFemaleRatio"].getFloat()
  var sexDistributionCountdown = float64(count)
  if ratio != 0:
    sexDistributionCountdown =
      floor(sexDistributionCountdown / (ratio + 1.0)) * ratio
  for index in 0 ..< count:
    if ratio == 0:
      sexes[index] = ""
    elif sexDistributionCountdown == 0:
      sexes[index] = "female"
    else:
      sexes[index] = "male"
      sexDistributionCountdown -= 1

  var decisionModels = newSeq[string](count)
  let configuredModels = config["agentDecisionModels"]
  for index in 0 ..< count:
    decisionModels[index] =
      configuredModels[index mod configuredModels.len].getStr()
    if decisionModels[index] == "rawSugarscape":
      decisionModels[index] = "none"

  var
    aggression = shuffledEndowments(
      config, "agentAggressionFactor", "aggressionFactor", count, 0
    )
    ageism = shuffledEndowments(
      config,
      "agentDecisionModelAgeismFactor",
      "decisionModelAgeismFactor",
      count,
      0,
    )
    decisionFactor = shuffledEndowments(
      config, "agentDecisionModelFactor", "decisionModelFactor", count, 0
    )
    lookahead = shuffledEndowments(
      config, "agentLookaheadFactor", "lookaheadFactor", count, 0
    )
    maxAges = shuffledEndowments(config, "agentMaxAge", "maxAge", count, 0)
    movements = shuffledEndowments(
      config, "agentMovement", "movement", count, 0
    )
    maxFriends = shuffledEndowments(
      config, "agentMaxFriends", "maxFriends", count, 0
    )
    racism = shuffledEndowments(
      config,
      "agentDecisionModelRacismFactor",
      "decisionModelRacismFactor",
      count,
      0,
    )
    selfishness = shuffledEndowments(
      config, "agentSelfishnessFactor", "selfishnessFactor", count, 0
    )
    sexism = shuffledEndowments(
      config,
      "agentDecisionModelSexismFactor",
      "decisionModelSexismFactor",
      count,
      0,
    )
    spice = shuffledEndowments(config, "agentStartingSpice", "spice", count, 0)
    spiceMetabolism = shuffledEndowments(
      config, "agentSpiceMetabolism", "spiceMetabolism", count, 0
    )
    sugar = shuffledEndowments(config, "agentStartingSugar", "sugar", count, 0)
    sugarMetabolism = shuffledEndowments(
      config, "agentSugarMetabolism", "sugarMetabolism", count, 0
    )
    vision = shuffledEndowments(config, "agentVision", "vision", count, 0)

  rng.shuffle(sexes)
  rng.shuffle(decisionModels)

  var quadrants = activeQuadrants(config, world)
  for quadrant in quadrants.mitems:
    rng.shuffle(quadrant)
  var quadrantIndices = newSeq[int](quadrants.len)
  for index in 0 ..< quadrantIndices.len:
    quadrantIndices[index] = index
  rng.shuffle(quadrantIndices)

  result = newSeq[Agent](count)
  for id in 0 ..< count:
    let
      quadrant = quadrantIndices[id mod quadrantIndices.len]
      cell = quadrants[quadrant].pop()
      endowmentIndex = count - id - 1
    result[id] = Agent(
      id: id,
      born: 0,
      cell: cell,
      alive: true,
      age: 0,
      maxAge: int(maxAges[endowmentIndex]),
      movement: int(movements[endowmentIndex]),
      vision: int(vision[endowmentIndex]),
      lookaheadFactor: lookahead[endowmentIndex],
      sugar: sugar[endowmentIndex],
      spice: spice[endowmentIndex],
      startingSugar: sugar[endowmentIndex],
      startingSpice: spice[endowmentIndex],
      sugarMetabolism: sugarMetabolism[endowmentIndex],
      spiceMetabolism: spiceMetabolism[endowmentIndex],
      sex: sexes[id],
      decisionModel: decisionModels.pop(),
      aggressionFactor: aggression[endowmentIndex],
      decisionModelFactor: decisionFactor[endowmentIndex],
      decisionModelAgeismFactor: ageism[endowmentIndex],
      decisionModelRacismFactor: racism[endowmentIndex],
      decisionModelSexismFactor: sexism[endowmentIndex],
      selfishnessFactor: selfishness[endowmentIndex],
      depressed: depressionFactors[id] == 1,
      maxFriends: int(maxFriends[endowmentIndex]),
      lastMovedTimestep: -1,
      lastMoveRank: 0,
      lastValidMoves: 0,
      lastMoveOptimal: true,
    )
    world.cells[cell].agent = id
