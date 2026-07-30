import std/[json, math, sequtils, strutils]

import ./environment
import ./py_random

type
  MoveOption* = object
    cell*: int
    welfare*: float64

  FriendEntry* = object
    agent*: int
    hammingDistance*: int

  Infection* = object
    disease*: int
    startIndex*, endIndex*: int
    infector*: int
    caught*, incubation*: int
    active*: bool

  Agent* = object
    id*: int
    born*: int
    cell*: int
    endowmentIndex*: int
    alive*: bool
    causeOfDeath*: string
    diseaseDeath*: bool
    age*: int
    maxAge*: int
    movement*, vision*: int
    lookaheadFactor*: float64
    sugar*, spice*: float64
    sugarIsFloat*, spiceIsFloat*: bool
    wealthIsFloat*: bool
    startingSugar*, startingSpice*: float64
    startingSugarIsFloat*, startingSpiceIsFloat*: bool
    inheritancePolicy*: string
    sugarMetabolism*, spiceMetabolism*: float64
    sugarMetabolismIsFloat*, spiceMetabolismIsFloat*: bool
    sex*: string
    decisionModel*: string
    aggressionFactor*, decisionModelFactor*: float64
    decisionModelLookaheadDiscount*, decisionModelLookaheadFactor*: float64
    aggressionFactorModifier*: float64
    decisionModelAgeismFactor*, decisionModelRacismFactor*: float64
    decisionModelSexismFactor*, decisionModelTribalFactor*: float64
    selfishnessFactor*: float64
    dynamicDecisionModelFactor*, dynamicSelfishnessFactor*: float64
    dynamicSocialPressureFactor*: float64
    baseInterestRate*, lendingFactor*: float64
    baseInterestRateIsFloat*, lendingFactorIsFloat*: bool
    loanDuration*: int
    diseaseProtectionChance*: float64
    fertilityAge*, infertilityAge*: int
    fertilityFactor*, fertilityFactorModifier*: float64
    friendlinessModifier*, happinessModifier*: float64
    movementModifier*, visionModifier*: float64
    sugarMetabolismModifier*, spiceMetabolismModifier*: float64
    sugarMetabolismModifierIsFloat*: bool
    spiceMetabolismModifierIsFloat*: bool
    metabolismModifierIsFloat*: bool
    happinessUnit*: float64
    tradeFactor*, universalSpice*, universalSugar*: float64
    universalSpiceIsFloat*, universalSugarIsFloat*: bool
    universalSpiceIncomeInterval*, universalSugarIncomeInterval*: int
    tagging*, tagPreferences*: bool
    hasTags*, hasRacialTags*: bool
    tags*, racialTags*: seq[int]
    immuneSystem*, startingImmuneSystem*: seq[int]
    diseases*: seq[Infection]
    hasImmuneSystem*: bool
    tribe*, race*, tagZeroes*: int
    depressed*: bool
    maxFriends*: int
    lastMovedTimestep*: int
    lastActivatedTimestep*: int
    lastSugar*, lastSpice*: float64
    lastSugarIsFloat*, lastSpiceIsFloat*: bool
    lastPollution*, lastTimeToLive*, timeToLive*: float64
    lastPollutionIsFloat*: bool
    lastTimeToLiveIsFloat*, timeToLiveIsFloat*: bool
    lastMoveRank*, lastValidMoves*: int
    lastMoveOptimal*: bool
    lastCombatTimestep*: int
    lastPreyWealth*: float64
    lastTradeTimestep*, lastTradePartners*: int
    lastSpreadDiseaseTimestep*, lastDiseasesSpread*: int
    lastUniversalSpiceIncomeTimestep*: int
    lastUniversalSugarIncomeTimestep*: int
    marginalRateOfSubstitution*: float64
    tradeVolume*: int
    sugarPrice*, spicePrice*: float64
    cellsInRange*: seq[RangeEntry]
    movementNeighborhood*: seq[int]
    neighbors*: seq[int]
    validMoves*: seq[MoveOption]
    friends*: seq[FriendEntry]
    children*, mates*: seq[int]
    father*, mother*: int
    lastReproducedTimestep*, lastMates*: int
    lastLendedTimestep*, lastLoans*: int
    creditorLoans*, debtorLoans*: seq[int]
    sugarMeanIncome*, spiceMeanIncome*: float64
    happiness*, conflictHappiness*, familyHappiness*: float64
    healthHappiness*, socialHappiness*, wealthHappiness*: float64
    temperanceTotalMetabolism*: float64
    temperanceRules*: array[5, int]
    timeSeenOverconsuming*, timesSeenIndulging*: int
    timesOverharvested*: int
    temperanceSocialPressure*, lastDeltaTimeToLive*: float64
    temperancePecs*: bool
    combatWithControlGroup*, combatWithExperimentalGroup*: int
    diseaseWithControlGroup*, diseaseWithExperimentalGroup*: int
    lendingWithControlGroup*, lendingWithExperimentalGroup*: int
    reproductionWithControlGroup*, reproductionWithExperimentalGroup*: int
    tradeWithControlGroup*, tradeWithExperimentalGroup*: int

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

proc activeQuadrants*(
    config: JsonNode,
    world: Environment,
): seq[seq[int]] =
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

proc generateTribeTags*(
    config: JsonNode,
    tribe: int,
    rng: var PyRandom,
): seq[int] =
  let
    tagLength = config["agentTagStringLength"].getInt()
    numTribes = config["environmentMaxTribes"].getInt()
    tribeSize = float64(tagLength + 1) / float64(numTribes)
    minimumZeroes = int(floor(float64(tribe) * tribeSize))
    maximumZeroes = min(
      int(floor(float64(tribe + 1) * tribeSize)) - 1,
      tagLength,
    )
    zeroes = minimumZeroes + int(
      rng.randBelow(uint64(maximumZeroes - minimumZeroes + 1))
    )
  result = newSeq[int](tagLength)
  for index in zeroes ..< tagLength:
    result[index] = 1
  rng.shuffle(result)

proc generateAgentTags(
    config: JsonNode,
    count: int,
    rng: var PyRandom,
): seq[seq[int]] =
  result = newSeq[seq[int]](count)
  if config["agentTagStringLength"].getInt() == 0 or
      config["environmentMaxTribes"].getInt() == 0 or
      config["environmentTribePerQuadrant"].getBool():
    return
  let numTribes = config["environmentMaxTribes"].getInt()
  for index in 0 ..< count:
    result[index] = generateTribeTags(
      config,
      index mod numTribes,
      rng,
    )
  rng.shuffle(result)

proc generateRacialTags(
    config: JsonNode,
    race: int,
    rng: var PyRandom,
): seq[int] =
  let
    tagLength = config["agentRacialTagStringLength"].getInt()
    numRaces = config["environmentMaxRaces"].getInt()
  if numRaces == 1:
    return newSeqWith(tagLength, race)
  let
    majority = tagLength div 2 + 1
    assigned = majority + int(
      rng.randBelow(uint64(tagLength - majority + 1))
    )
  result = newSeq[int](tagLength)
  for index in assigned ..< tagLength:
    let choice = int(rng.randBelow(uint64(numRaces - 1)))
    result[index] = if choice >= race: choice + 1 else: choice
  for index in 0 ..< assigned:
    result[index] = race
  rng.shuffle(result)

proc generateAgentRacialTags(
    config: JsonNode,
    count: int,
    rng: var PyRandom,
): seq[seq[int]] =
  result = newSeq[seq[int]](count)
  if config["agentRacialTagStringLength"].getInt() == 0 or
      config["environmentMaxRaces"].getInt() == 0:
    return
  let numRaces = config["environmentMaxRaces"].getInt()
  for index in 0 ..< count:
    result[index] = generateRacialTags(
      config,
      index mod numRaces,
      rng,
    )
  rng.shuffle(result)

proc findTribe*(agent: var Agent, config: JsonNode): int =
  if not agent.hasTags:
    return -1
  agent.tagZeroes = 0
  for tag in agent.tags:
    if tag == 0:
      inc agent.tagZeroes
  let
    possibleZeroes = config["agentTagStringLength"].getInt() + 1
    numTribes = config["environmentMaxTribes"].getInt()
    tribeSize = float64(possibleZeroes) / float64(numTribes)
  min(
    int(ceil(float64(agent.tagZeroes + 1) / tribeSize)) - 1,
    numTribes - 1,
  )

proc findRace(tags: seq[int], hasTags: bool): int =
  if not hasTags:
    return -1
  var bestCount = -1
  for candidate in tags:
    var count = 0
    for tag in tags:
      if tag == candidate:
        inc count
    if count > bestCount or
        (count == bestCount and candidate < result):
      result = candidate
      bestCount = count

proc createInitialAgents*(
    config: JsonNode,
    world: var Environment,
    rng: var PyRandom,
): seq[Agent] =
  var quadrants = activeQuadrants(config, world)
  var availableCells = 0
  for quadrant in quadrants:
    availableCells += quadrant.len
  let requestedCount =
    config["startingAgents"].getInt() +
    (if config["agentLeader"].getBool(): 1 else: 0)
  let count = min(requestedCount, availableCells)
  if count == 0:
    return

  var depressionFactors = newSeq[int](count)
  let depressedCount =
    int(ceil(float64(count) * config["agentDepressionPercentage"].getFloat()))
  for index in 0 ..< depressedCount:
    depressionFactors[index] = 1
  rng.shuffle(depressionFactors)

  var racialTagEndowments =
    generateAgentRacialTags(config, count, rng)
  var tagEndowments = generateAgentTags(config, count, rng)
  let
    hasRacialTags =
      config["agentRacialTagStringLength"].getInt() > 0 and
      config["environmentMaxRaces"].getInt() > 0
    hasTags =
      config["agentTagStringLength"].getInt() > 0 and
      config["environmentMaxTribes"].getInt() > 0

  var sexes = newSeq[string](count)
  let immuneLength = config["agentImmuneSystemLength"].getInt()
  var immuneSystems = newSeq[seq[int]](count)
  if immuneLength > 0:
    for system in immuneSystems.mitems:
      system = newSeq[int](immuneLength)
      for bit in system.mitems:
        bit = int(rng.randBelow(2))
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
    baseInterestRate = shuffledEndowments(
      config, "agentBaseInterestRate", "baseInterestRate", count, 0
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
    decisionLookaheadDiscount = shuffledEndowments(
      config,
      "agentDecisionModelLookaheadDiscount",
      "decisionModelLookaheadDiscount",
      count,
      0,
    )
    tribalism = shuffledEndowments(
      config,
      "agentDecisionModelTribalFactor",
      "decisionModelTribalFactor",
      count,
      0,
    )
    dynamicDecision = shuffledEndowments(
      config,
      "agentDynamicDecisionModelFactor",
      "dynamicDecisionModelFactor",
      count,
      0,
    )
    dynamicSelfishness = shuffledEndowments(
      config,
      "agentDynamicSelfishnessFactor",
      "dynamicSelfishnessFactor",
      count,
      0,
    )
    dynamicSocialPressure = shuffledEndowments(
      config,
      "agentDynamicSocialPressureFactor",
      "dynamicSocialPressureFactor",
      count,
      0,
    )
    diseaseProtection = shuffledEndowments(
      config,
      "agentDiseaseProtectionChance",
      "diseaseProtectionChance",
      count,
      0,
    )
    fertilityFactor = shuffledEndowments(
      config, "agentFertilityFactor", "fertilityFactor", count, 0
    )
    femaleFertilityAge = shuffledEndowments(
      config,
      "agentFemaleFertilityAge",
      "femaleFertilityAge",
      count,
      0,
    )
    femaleInfertilityAge = shuffledEndowments(
      config,
      "agentFemaleInfertilityAge",
      "femaleInfertilityAge",
      count,
      0,
    )
    maleFertilityAge = shuffledEndowments(
      config,
      "agentMaleFertilityAge",
      "maleFertilityAge",
      count,
      0,
    )
    maleInfertilityAge = shuffledEndowments(
      config,
      "agentMaleInfertilityAge",
      "maleInfertilityAge",
      count,
      0,
    )
    lookahead = shuffledEndowments(
      config, "agentLookaheadFactor", "lookaheadFactor", count, 0
    )
    lendingFactor = shuffledEndowments(
      config, "agentLendingFactor", "lendingFactor", count, 0
    )
    loanDuration = shuffledEndowments(
      config, "agentLoanDuration", "loanDuration", count, 0
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
    tradeFactor = shuffledEndowments(
      config, "agentTradeFactor", "tradeFactor", count, 0
    )
    universalSpice = shuffledEndowments(
      config, "agentUniversalSpice", "universalSpice", count, 0
    )
    universalSugar = shuffledEndowments(
      config, "agentUniversalSugar", "universalSugar", count, 0
    )
    vision = shuffledEndowments(config, "agentVision", "vision", count, 0)

  rng.shuffle(sexes)
  rng.shuffle(decisionModels)

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
      endowmentIndex: id,
      alive: true,
      age: 0,
      maxAge: int(maxAges[endowmentIndex]),
      movement: int(movements[endowmentIndex]),
      vision: int(vision[endowmentIndex]),
      lookaheadFactor: lookahead[endowmentIndex],
      sugar: sugar[endowmentIndex],
      spice: spice[endowmentIndex],
      sugarIsFloat:
        config["agentStartingSugar"][0].kind == JFloat or
        config["agentStartingSugar"][1].kind == JFloat,
      spiceIsFloat:
        config["agentStartingSpice"][0].kind == JFloat or
        config["agentStartingSpice"][1].kind == JFloat,
      wealthIsFloat:
        config["agentStartingSugar"][0].kind == JFloat or
        config["agentStartingSugar"][1].kind == JFloat or
        config["agentStartingSpice"][0].kind == JFloat or
        config["agentStartingSpice"][1].kind == JFloat,
      startingSugar: sugar[endowmentIndex],
      startingSpice: spice[endowmentIndex],
      startingSugarIsFloat:
        config["agentStartingSugar"][0].kind == JFloat or
        config["agentStartingSugar"][1].kind == JFloat,
      startingSpiceIsFloat:
        config["agentStartingSpice"][0].kind == JFloat or
        config["agentStartingSpice"][1].kind == JFloat,
      inheritancePolicy: config["agentInheritancePolicy"].getStr(),
      sugarMetabolism: sugarMetabolism[endowmentIndex],
      spiceMetabolism: spiceMetabolism[endowmentIndex],
      sugarMetabolismIsFloat:
        config["agentSugarMetabolism"][0].kind == JFloat or
        config["agentSugarMetabolism"][1].kind == JFloat,
      spiceMetabolismIsFloat:
        config["agentSpiceMetabolism"][0].kind == JFloat or
        config["agentSpiceMetabolism"][1].kind == JFloat,
      sex: sexes[id],
      decisionModel: decisionModels.pop(),
      aggressionFactor: aggression[endowmentIndex],
      baseInterestRate: baseInterestRate[endowmentIndex],
      baseInterestRateIsFloat:
        config["agentBaseInterestRate"][0].kind == JFloat or
        config["agentBaseInterestRate"][1].kind == JFloat,
      lendingFactor: lendingFactor[endowmentIndex],
      lendingFactorIsFloat:
        config["agentLendingFactor"][0].kind == JFloat or
        config["agentLendingFactor"][1].kind == JFloat,
      loanDuration: int(loanDuration[endowmentIndex]),
      decisionModelFactor: decisionFactor[endowmentIndex],
      decisionModelLookaheadDiscount:
        decisionLookaheadDiscount[endowmentIndex],
      decisionModelLookaheadFactor:
        config["agentDecisionModelLookaheadFactor"].getFloat(),
      decisionModelTribalFactor: tribalism[endowmentIndex],
      dynamicDecisionModelFactor: dynamicDecision[endowmentIndex],
      dynamicSelfishnessFactor: dynamicSelfishness[endowmentIndex],
      dynamicSocialPressureFactor:
        dynamicSocialPressure[endowmentIndex],
      diseaseProtectionChance: diseaseProtection[endowmentIndex],
      fertilityAge:
        if sexes[id] == "female":
          int(femaleFertilityAge[endowmentIndex])
        elif sexes[id] == "male":
          int(maleFertilityAge[endowmentIndex])
        else:
          0,
      infertilityAge:
        if sexes[id] == "female":
          int(femaleInfertilityAge[endowmentIndex])
        elif sexes[id] == "male":
          int(maleInfertilityAge[endowmentIndex])
        else:
          0,
      fertilityFactor: fertilityFactor[endowmentIndex],
      decisionModelAgeismFactor: ageism[endowmentIndex],
      decisionModelRacismFactor: racism[endowmentIndex],
      decisionModelSexismFactor: sexism[endowmentIndex],
      selfishnessFactor: selfishness[endowmentIndex],
      tradeFactor: tradeFactor[endowmentIndex],
      universalSpice: universalSpice[endowmentIndex],
      universalSugar: universalSugar[endowmentIndex],
      universalSpiceIsFloat:
        config["agentUniversalSpice"][0].kind == JFloat or
        config["agentUniversalSpice"][1].kind == JFloat,
      universalSugarIsFloat:
        config["agentUniversalSugar"][0].kind == JFloat or
        config["agentUniversalSugar"][1].kind == JFloat,
      universalSpiceIncomeInterval:
        config["environmentUniversalSpiceIncomeInterval"].getInt(),
      universalSugarIncomeInterval:
        config["environmentUniversalSugarIncomeInterval"].getInt(),
      depressed: depressionFactors[id] == 1,
      happinessUnit: 1,
      maxFriends: int(maxFriends[endowmentIndex]),
      tagging: config["agentTagging"].getBool(),
      tagPreferences: config["agentTagPreferences"].getBool(),
      hasTags: hasTags,
      hasRacialTags: hasRacialTags,
      tags: tagEndowments[endowmentIndex],
      racialTags: racialTagEndowments[endowmentIndex],
      immuneSystem: immuneSystems[endowmentIndex] & @[],
      startingImmuneSystem: immuneSystems[endowmentIndex] & @[],
      hasImmuneSystem: immuneLength > 0,
      tribe: -1,
      race: findRace(
        racialTagEndowments[endowmentIndex],
        hasRacialTags,
      ),
      lastMovedTimestep: -1,
      lastActivatedTimestep: 0,
      lastMoveRank: 0,
      lastValidMoves: 0,
      lastMoveOptimal: true,
      lastCombatTimestep: -1,
      lastTradeTimestep: -1,
      lastSpreadDiseaseTimestep: -1,
      marginalRateOfSubstitution: 1,
      father: -1,
      mother: -1,
      lastReproducedTimestep: -1,
      lastLendedTimestep: -1,
      sugarMeanIncome: 1,
      spiceMeanIncome: 1,
    )
    if result[id].depressed:
      result[id].aggressionFactor *= 1.145
      result[id].maxFriends =
        int(ceil(float64(result[id].maxFriends) * 0.6333))
      result[id].happinessUnit *= 0.5763
      result[id].movement *=
        int(ceil(float64(result[id].movement) * 0.429))
      result[id].spiceMetabolism *=
        ceil(result[id].spiceMetabolism * 1.544)
      result[id].sugarMetabolism *=
        ceil(result[id].sugarMetabolism * 1.544)
    if "altruist" in result[id].decisionModel:
      result[id].selfishnessFactor = 0
    elif "bentham" in result[id].decisionModel and
        result[id].selfishnessFactor < 0:
      result[id].selfishnessFactor = 0.5
    elif "egoist" in result[id].decisionModel:
      result[id].selfishnessFactor = 1
    elif "negativeBentham" in result[id].decisionModel:
      result[id].selfishnessFactor = -1
    if "Dynamic" in result[id].decisionModel and
        config["agentDynamicSelfishnessFactor"][0].getFloat() == 0 and
        config["agentDynamicSelfishnessFactor"][1].getFloat() == 0:
      result[id].dynamicSelfishnessFactor = 0.01
    if "NoLookahead" in result[id].decisionModel:
      result[id].decisionModelLookaheadFactor = 0
    elif "HalfLookahead" in result[id].decisionModel:
      result[id].decisionModelLookaheadFactor = 0.5
    if "asimov" in result[id].decisionModel or
        (
          "temperance" in result[id].decisionModel and
          "PECS" in result[id].decisionModel
        ):
      # DTL reconstructs these subclasses after applying the modifiers above.
      result[id].dynamicSelfishnessFactor =
        dynamicSelfishness[endowmentIndex]
      result[id].decisionModelLookaheadFactor =
        config["agentDecisionModelLookaheadFactor"].getFloat()
    if "temperance" in result[id].decisionModel:
      result[id].temperancePecs = "PECS" in result[id].decisionModel
      result[id].temperanceTotalMetabolism =
        result[id].sugarMetabolism + result[id].spiceMetabolism
    if config["environmentTribePerQuadrant"].getBool():
      result[id].tags = generateTribeTags(config, quadrant, rng)
      result[id].endowmentIndex = -1
    result[id].tribe = result[id].findTribe(config)
    world.cells[cell].agent = id

  if config["agentLeader"].getBool() and result.len > 0:
    let leaderCell = result[0].cell
    world.cells[leaderCell].agent = -1
    result[0].alive = false
    result[0].cell = -1
    result[0].fertilityFactor = 0
    result[0].maxAge = -1
    result[0].movement = 0
    result[0].vision = max(world.height, world.width)
    result[0].sugar = float64(high(int64))
    result[0].spice = float64(high(int64))
    result[0].startingSugar = float64(high(int64))
    result[0].startingSpice = float64(high(int64))
    result[0].sugarMetabolism = 0
    result[0].spiceMetabolism = 0
    result[0].tradeFactor = 0
