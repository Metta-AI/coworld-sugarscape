# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[algorithm, json, math, sets, strutils, syncio, sysrand]

import ./agents
import ./configuration
import ./diseases
import ./environment
import ./py_json
import ./py_random

type
  MoveCandidate* = object
    cell*: int
    welfare*: float64
    distance*: float64

  Loan = object
    creditor, debtor: int
    sugarLoan, spiceLoan: float64
    sugarLoanIsFloat, spiceLoanIsFloat: bool
    duration, origin: int
    active: bool

  PythonNumber = object
    value: float64
    isFloat: bool

  Simulation* = object
    config*: JsonNode
    environment*: Environment
    agents*: seq[Agent]
    diseases*: seq[Disease]
    diseaseRegistry*: seq[int]
    remainingDiseases*: seq[int]
    activeAgents*: seq[int]
    rng*: PyRandom
    timestep*: int
    maxTimestep*: int
    meanWealth*: float64
    carryingCapacity*: int
    runtimeStats*: JsonNode
    deathsThisTimestep*: seq[int]
    agentTemplates*: seq[Agent]
    nextAgentId*: int
    agentEndowmentIndex*: int
    agentsReplacedThisTimestep*: int
    agentsBornThisTimestep*: seq[int]
    agentRuntimeStats*: seq[JsonNode]
    loans: seq[Loan]

  PopulationPolicy* = proc(
    sim: Simulation,
    agentId: int,
    candidates: openArray[MoveCandidate],
    greedyCell: int,
  ): int {.closure.}

proc pythonDivide(numerator, denominator: float64): float64 {.noinline.} =
  ## Keep CPython's separately rounded `/` bytecode result visible to callers.
  var rounded {.volatile.} = numerator / denominator
  rounded

proc movement(agent: Agent): int =
  max(0, agent.movement + int(agent.movementModifier))

proc vision(agent: Agent): int =
  max(0, agent.vision + int(agent.visionModifier))

proc sugarMetabolism(agent: Agent): float64 =
  max(0.0, agent.sugarMetabolism + agent.sugarMetabolismModifier)

proc spiceMetabolism(agent: Agent): float64 =
  max(0.0, agent.spiceMetabolism + agent.spiceMetabolismModifier)

proc socialLinksJson*(sim: Simulation): JsonNode =
  ## Read-only relationships for spectator rendering. This must not mutate
  ## simulation state or consume random numbers.
  result = newJArray()
  var seen = initHashSet[(string, int, int)]()
  for id in sim.activeAgents:
    let agent = sim.agents[id]
    for friend in agent.friends:
      if sim.agents[friend.agent].alive:
        let
          source = min(id, friend.agent)
          target = max(id, friend.agent)
          key = ("friend", source, target)
        if key in seen:
          continue
        seen.incl(key)
        result.add(%*{
          "source": source,
          "target": target,
          "type": "friend",
        })
    for mate in agent.mates:
      if sim.agents[mate].alive:
        let
          source = min(id, mate)
          target = max(id, mate)
          key = ("mate", source, target)
        if key in seen:
          continue
        seen.incl(key)
        result.add(%*{
          "source": source,
          "target": target,
          "type": "mate",
        })
  for loan in sim.loans:
    if loan.active and sim.agents[loan.creditor].alive and
        sim.agents[loan.debtor].alive:
      result.add(%*{
        "source": loan.creditor,
        "target": loan.debtor,
        "type": "loan",
      })

proc findCellsInRange(sim: Simulation, agent: Agent): seq[RangeEntry]
proc isExperimental(sim: Simulation, agent: Agent): bool

proc hasDisease(agent: Agent, disease: int): bool =
  for infection in agent.diseases:
    if infection.disease == disease:
      return true

proc catchDisease(
    sim: var Simulation,
    agentId, diseaseId: int,
    infector = -1,
    initial = false,
): bool =
  if sim.agents[agentId].hasDisease(diseaseId):
    return
  let
    disease = sim.diseases[diseaseId]
    match = nearestImmuneMatch(sim.agents[agentId], disease)
  if match.distance == 0:
    return
  if not initial:
    let
      attack = sim.rng.randomFloat()
      defense = sim.rng.randomFloat()
      attackSuccess =
        disease.transmissionChance != 0 and
        attack <= disease.transmissionChance
      defenseSuccess =
        sim.agents[agentId].diseaseProtectionChance != 0 and
        defense <= sim.agents[agentId].diseaseProtectionChance
    if not attackSuccess or defenseSuccess:
      return

  let caught =
    if infector >= 0: sim.agents[infector].lastMovedTimestep
    else: sim.timestep
  sim.agents[agentId].diseases.add(
    Infection(
      disease: diseaseId,
      startIndex: match.startIndex,
      endIndex: match.endIndex,
      infector: infector,
      caught: caught,
      incubation: disease.incubationPeriod,
    )
  )
  if disease.incubationPeriod == 0:
    sim.agents[agentId].trigger(disease)
  sim.agents[agentId].cellsInRange =
    sim.findCellsInRange(sim.agents[agentId])
  if initial:
    sim.diseaseRegistry.add(diseaseId)
  true

proc configureDiseases(sim: var Simulation) =
  var zombieCount = 0
  for name in sim.config["diseaseList"]:
    if "zombieVirus" in name.getStr():
      inc zombieCount
  let count = max(0, min(
    sim.config["startingDiseases"].getInt(),
    sim.activeAgents.len,
  ) - zombieCount)
  sim.diseases = createDiseases(
    sim.config,
    count,
    sim.timestep,
    sim.rng,
  )
  for _ in 0 ..< zombieCount:
    sim.diseases.add(createZombieVirus(sim.diseases.len))
  sim.rng.shuffle(sim.activeAgents)

  var initialDiseases: seq[int]
  for index, disease in sim.diseases:
    if disease.startTimestep == 0:
      initialDiseases.add(index)
    else:
      sim.remainingDiseases.add(index)

  let
    bounds = sim.config["startingDiseasesPerAgent"]
    minimum = bounds[0].getInt()
    maximum = bounds[1].getInt()
    placeOneEach = minimum == 0 and maximum == 0
  var current = minimum
  for agentId in sim.activeAgents:
    sim.rng.shuffle(initialDiseases)
    var diseaseIndex = 0
    while diseaseIndex < initialDiseases.len:
      if sim.agents[agentId].diseases.len >= current and not placeOneEach:
        inc current
        break
      let id = initialDiseases[diseaseIndex]
      if nearestImmuneMatch(sim.agents[agentId], sim.diseases[id]).distance != 0:
        discard sim.catchDisease(agentId, id, initial = true)
        if placeOneEach:
          initialDiseases.delete(diseaseIndex)
          break
      inc diseaseIndex
    if current > maximum:
      current = minimum

proc addRemainingDiseases(sim: var Simulation) =
  var index = 0
  while index < sim.remainingDiseases.len:
    let diseaseId = sim.remainingDiseases[index]
    if sim.diseases[diseaseId].startTimestep <= sim.timestep:
      var placed = false
      for agentId in sim.activeAgents:
        if nearestImmuneMatch(
          sim.agents[agentId],
          sim.diseases[diseaseId],
        ).distance != 0:
          discard sim.catchDisease(agentId, diseaseId, initial = true)
          placed = true
          break
      if placed:
        sim.remainingDiseases.delete(index)
        continue
    inc index

proc doDisease(sim: var Simulation, id: int) =
  sim.rng.shuffle(sim.agents[id].diseases)
  var infectionIndex = 0
  while infectionIndex < sim.agents[id].diseases.len:
    var infection = sim.agents[id].diseases[infectionIndex]
    let disease = sim.diseases[infection.disease]
    if infection.caught != sim.timestep and infection.incubation > 0:
      dec infection.incubation
      sim.agents[id].diseases[infectionIndex].incubation =
        infection.incubation
    if infection.incubation == 0:
      sim.agents[id].trigger(disease)
    if disease.recoverable and disease.tags.len > 0:
      let responseEnd = min(
        infection.endIndex + 1,
        sim.agents[id].immuneSystem.len,
      )
      var responseMatches = true
      for offset in 0 ..< responseEnd - infection.startIndex:
        if sim.agents[id].immuneSystem[infection.startIndex + offset] !=
            disease.tags[offset]:
          let
            immuneIndex = infection.startIndex + offset
            bit = disease.tags[offset]
            endowmentIndex = sim.agents[id].endowmentIndex
          if endowmentIndex >= 0:
            sim.agentTemplates[endowmentIndex].immuneSystem[immuneIndex] = bit
            sim.agentTemplates[endowmentIndex].startingImmuneSystem[
              immuneIndex
            ] = bit
            for agent in sim.agents.mitems:
              if agent.endowmentIndex == endowmentIndex:
                agent.immuneSystem[immuneIndex] = bit
                agent.startingImmuneSystem[immuneIndex] = bit
          else:
            sim.agents[id].immuneSystem[immuneIndex] = bit
            sim.agents[id].startingImmuneSystem[immuneIndex] = bit
          responseMatches = false
          break
      if responseMatches:
        sim.agents[id].recover(disease)
        sim.agents[id].diseases.delete(infectionIndex)
        inc infectionIndex
        continue
    inc infectionIndex

  let diseaseCount = sim.agents[id].diseases.len
  if diseaseCount == 0:
    return
  var neighbors: seq[int]
  let cell = sim.agents[id].cell
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighborCell = sim.environment.cells[cell].neighbors[index]
    let neighbor = sim.environment.cells[neighborCell].agent
    if neighbor >= 0 and sim.agents[neighbor].alive:
      neighbors.add(neighbor)
  sim.rng.shuffle(neighbors)
  var diseasesSpread = 0
  for neighbor in neighbors:
    let infection =
      sim.agents[id].diseases[
        int(sim.rng.randBelow(uint64(diseaseCount)))
      ]
    discard sim.catchDisease(neighbor, infection.disease, infector = id)
    if sim.agents[neighbor].hasDisease(infection.disease):
      inc diseasesSpread
    if sim.config["experimentalGroup"].kind != JNull:
      if sim.isExperimental(sim.agents[neighbor]):
        inc sim.agents[id].diseaseWithExperimentalGroup
      else:
        inc sim.agents[id].diseaseWithControlGroup
  if diseasesSpread > 0:
    sim.agents[id].lastSpreadDiseaseTimestep = sim.timestep
    sim.agents[id].lastDiseasesSpread = diseasesSpread

proc initialRuntimeStats(config: JsonNode): JsonNode =
  result = newJObject()
  template integer(name: string, value: int64 = 0) =
    result[name] = newJInt(value)
  integer("timestep")
  integer("population")
  integer("meanMetabolism")
  integer("meanMovement")
  integer("meanVision")
  integer("meanWealth")
  integer("meanAge")
  integer("giniCoefficient")
  integer("meanTradePrice")
  integer("tradeVolume")
  integer("maxWealth")
  integer("minWealth")
  integer("meanHappiness")
  integer("meanWealthHappiness")
  integer("meanHealthHappiness")
  integer("meanSocialHappiness")
  integer("meanFamilyHappiness")
  integer("meanConflictHappiness")
  integer("meanAgeAtDeath")
  integer("seed", config["seed"].getBiggestInt())
  integer("agentsReplaced")
  integer("agentsBorn")
  integer("agentStarvationDeaths")
  integer("agentDiseaseDeaths")
  integer("environmentWealthCreated")
  integer("agentWealthTotal")
  integer("environmentWealthTotal")
  integer("agentWealthCollected")
  integer("agentWealthBurnRate")
  integer("agentMeanTimeToLive")
  integer("agentTotalMetabolism")
  integer("agentCombatDeaths")
  integer("agentAgingDeaths")
  integer("agentDeaths")
  integer("largestRace")
  integer("largestTribe")
  integer("largestRaceSize")
  integer("largestTribeSize")
  integer("remainingRaces", config["environmentMaxRaces"].getBiggestInt())
  integer("remainingTribes", config["environmentMaxTribes"].getBiggestInt())
  integer("sickAgents")
  integer("carryingCapacity")
  integer("meanDeathsPercentage")
  integer("sickAgentsPercentage")
  integer("meanSelfishness")
  integer("diseaseEffectiveReproductionRate")
  integer("diseaseIncidence")
  integer("diseasePrevalence")
  integer("agentLastMoveOptimalityPercentage")
  integer("meanNeighbors")
  integer("meanMoveRank")
  integer("meanMoveDifferenceFromOptimal")
  integer("meanValidMoves")
  integer("totalHappiness")
  integer("loanVolume")
  integer("meanAgeismFactor")
  integer("meanRacismFactor")
  integer("meanSexismFactor")
  integer("moveSpace")
  if config["experimentalGroup"].kind != JNull:
    integer("meanControlNeighbors")
    integer("meanExperimentalNeighbors")
    var baseKeys: seq[string]
    for key, _ in result:
      baseKeys.add(key)
    let experimental = config["experimentalGroup"].getStr()
    for key in baseKeys:
      let suffix = key[0].toUpperAscii() & key[1 .. ^1]
      integer("control" & suffix)
      integer(experimental & suffix)
    for interaction in [
      "combatControlGroupToControlGroup",
      "combatControlGroupToExperimentalGroup",
      "combatExperimentalGroupToControlGroup",
      "combatExperimentalGroupToExperimentalGroup",
      "diseaseControlGroupToControlGroup",
      "diseaseControlGroupToExperimentalGroup",
      "diseaseExperimentalGroupToControlGroup",
      "diseaseExperimentalGroupToExperimentalGroup",
      "lendingControlGroupToControlGroup",
      "lendingControlGroupToExperimentalGroup",
      "lendingExperimentalGroupToControlGroup",
      "lendingExperimentalGroupToExperimentalGroup",
      "reproductionControlGroupToControlGroup",
      "reproductionControlGroupToExperimentalGroup",
      "reproductionExperimentalGroupToControlGroup",
      "reproductionExperimentalGroupToExperimentalGroup",
      "tradeControlGroupToControlGroup",
      "tradeControlGroupToExperimentalGroup",
      "tradeExperimentalGroupToControlGroup",
      "tradeExperimentalGroupToExperimentalGroup",
    ]:
      integer(interaction)

proc roundHalfEven(value: float64, places: int): float64 =
  parseFloat(formatFloat(value, ffDecimal, places))

proc timeToLiveValue(
    agent: Agent,
    ageLimited: bool,
): tuple[value: float64, isFloat: bool] =
  let
    sugarMet = sugarMetabolism(agent)
    spiceMet = spiceMetabolism(agent)
  var
    sugarTime =
      if sugarMet > 0:
        agent.sugar / sugarMet
      else:
        float64(high(int))
    spiceTime =
      if spiceMet > 0:
        agent.spice / spiceMet
      else:
        float64(high(int))
    sugarIsFloat = sugarMet > 0
    spiceIsFloat = spiceMet > 0
  if agent.universalSugar != 0 and sugarMet > 0:
    let income =
      sugarTime * agent.universalSugar /
      float64(agent.universalSugarIncomeInterval)
    sugarTime = (agent.sugar + income) / sugarMet
  if agent.universalSpice != 0 and spiceMet > 0:
    let income =
      spiceTime * agent.universalSpice /
      float64(agent.universalSpiceIncomeInterval)
    spiceTime = (agent.spice + income) / spiceMet
  if sugarTime <= spiceTime:
    result = (sugarTime, sugarIsFloat)
  else:
    result = (spiceTime, spiceIsFloat)
  if ageLimited and float64(agent.maxAge - agent.age) < result.value:
    result = (float64(agent.maxAge - agent.age), false)

proc timeToLive(agent: Agent, ageLimited: bool): float64 =
  timeToLiveValue(agent, ageLimited).value

proc timeToLiveAt(
    sim: Simulation,
    agent: Agent,
    cell: int,
): float64 =
  var prospective = agent
  prospective.sugar += float64(sim.environment.cells[cell].sugar)
  prospective.spice += float64(sim.environment.cells[cell].spice)
  timeToLive(prospective, false)

proc giniCoefficient(sim: Simulation): float64 =
  if sim.activeAgents.len == 0:
    return 0
  var wealth = newSeqOfCap[float64](sim.activeAgents.len)
  for id in sim.activeAgents:
    wealth.add(sim.agents[id].sugar + sim.agents[id].spice)
  wealth.sort()
  var total = 0.0
  for value in wealth:
    total += value
  if total == 0:
    return 1
  var
    cumulative = 0.0
    area = 0.0
  for index in 0 ..< wealth.len - 1:
    cumulative += wealth[index]
    area += cumulative / total
  cumulative += wealth[^1]
  area += (cumulative / 2.0) / total
  area /= float64(wealth.len)
  roundHalfEven((0.5 - area) / 0.5, 3)

proc updateExperimentalStats(sim: var Simulation)

proc updateRuntimeStats(sim: var Simulation) =
  let population = sim.activeAgents.len
  var
    agingDeaths: int64
    combatDeaths: int64
    diseaseDeaths: int64
    starvationDeaths: int64
    totalAgeAtDeath = 0.0
  for id in sim.deathsThisTimestep:
    totalAgeAtDeath += float64(sim.agents[id].age)
    case sim.agents[id].causeOfDeath
    of "aging":
      inc agingDeaths
    of "starvation":
      inc starvationDeaths
    of "combat":
      inc combatDeaths
    else:
      discard
    if sim.agents[id].diseaseDeath:
      inc diseaseDeaths
  var
    environmentWealthCreated: int64
    environmentWealthTotal: int64
  for cell in sim.environment.cells:
    environmentWealthCreated +=
      cell.sugarLastProduced + cell.spiceLastProduced
    environmentWealthTotal += cell.sugar + cell.spice
    if sim.timestep == 1:
      environmentWealthCreated += cell.maxSugar + cell.maxSpice

  if sim.timestep == 0:
    sim.carryingCapacity = population
  else:
    sim.carryingCapacity = int(
      ceil(
        0.05 * float64(population) +
        0.95 * float64(sim.carryingCapacity)
      )
    )

  var
    totalAge = 0.0
    totalAgeism = 0.0
    totalConflictHappiness = 0.0
    totalFamilyHappiness = 0.0
    totalHappiness = 0.0
    totalHealthHappiness = 0.0
    totalMovement = 0.0
    totalRacism = 0.0
    totalSelfishness = 0.0
    totalSexism = 0.0
    totalSocialHappiness = 0.0
    totalSpiceMetabolism = 0.0
    totalSugarMetabolism = 0.0
    totalVision = 0.0
    totalWealth = 0.0
    totalWealthIsFloat = false
    collectedWealthIsFloat = false
    totalWealthHappiness = 0.0
    maxWealth = -Inf
    minWealth = Inf
    maxWealthIsFloat = false
    minWealthIsFloat = false
    agentWealthCollected = 0.0
    agentWealthBurnRate = 0.0
    agentMeanTimeToLive = 0.0
    optimalMoves = 0
    agentMoves = 0
    totalNeighbors = 0.0
    totalValidMoves = 0.0
    totalMoveRank = 0.0
    totalMoveDifference = 0.0
    moveDifferenceIsFloat = false
    moveSpace = 0
    totalTradePrice = 0.0
    tradeVolume: int64
    loanVolume: int64
    traders = 0
    sickAgents = 0
    diseaseIncidence = 0
    diseasePrevalence = 0
    infectors: seq[int]
    races: seq[tuple[key: int, count: int]]
    tribes: seq[tuple[key: int, count: int]]

  for id in sim.activeAgents:
    let agent = sim.agents[id]
    let wealth = agent.sugar + agent.spice
    totalAge += float64(agent.age)
    totalAgeism += agent.decisionModelAgeismFactor
    totalConflictHappiness += agent.conflictHappiness
    totalFamilyHappiness += agent.familyHappiness
    totalHappiness += agent.happiness
    totalHealthHappiness += agent.healthHappiness
    totalMovement += float64(agent.movement)
    totalRacism += agent.decisionModelRacismFactor
    totalSelfishness += agent.selfishnessFactor
    totalSexism += agent.decisionModelSexismFactor
    totalSocialHappiness += agent.socialHappiness
    totalSpiceMetabolism += agent.spiceMetabolism
    totalSugarMetabolism += agent.sugarMetabolism
    totalVision += float64(agent.vision)
    if agent.diseases.len > 0:
      inc sickAgents
    for infection in agent.diseases:
      if infection.caught == sim.timestep:
        inc diseaseIncidence
        if sim.timestep != 0 and infection.infector >= 0 and
            infection.infector notin infectors:
          infectors.add(infection.infector)
    totalWealth += wealth
    totalWealthIsFloat = totalWealthIsFloat or agent.wealthIsFloat
    totalWealthHappiness += agent.wealthHappiness
    if agent.tradeVolume > 0:
      totalTradePrice += max(agent.spicePrice, agent.sugarPrice)
      tradeVolume += int64(agent.tradeVolume)
      inc traders
    if agent.lastLendedTimestep == sim.timestep:
      loanVolume += int64(agent.lastLoans)
    var foundRace = false
    for entry in races.mitems:
      if entry.key == agent.race:
        inc entry.count
        foundRace = true
        break
    if not foundRace:
      races.add((key: agent.race, count: 1))
    var foundTribe = false
    for entry in tribes.mitems:
      if entry.key == agent.tribe:
        inc entry.count
        foundTribe = true
        break
    if not foundTribe:
      tribes.add((key: agent.tribe, count: 1))
    if wealth > maxWealth:
      maxWealth = wealth
      maxWealthIsFloat = agent.wealthIsFloat
    if wealth < minWealth:
      minWealth = wealth
      minWealthIsFloat = agent.wealthIsFloat
    agentWealthCollected +=
      wealth - (agent.lastSugar + agent.lastSpice)
    collectedWealthIsFloat =
      collectedWealthIsFloat or agent.wealthIsFloat
    agentWealthBurnRate += timeToLive(agent, false)
    agentMeanTimeToLive += timeToLive(agent, true)
    let ageLimitedTimeToLive = timeToLiveValue(agent, true)
    sim.agents[id].timeToLive = ageLimitedTimeToLive.value
    sim.agents[id].timeToLiveIsFloat = ageLimitedTimeToLive.isFloat
    if agent.lastMoveOptimal:
      inc optimalMoves
    inc agentMoves
    totalNeighbors += float64(agent.movementNeighborhood.len)
    moveSpace += agent.lastValidMoves
    totalValidMoves += float64(agent.validMoves.len)
    for index, option in agent.validMoves:
      if option.cell == agent.cell:
        totalMoveRank += float64(index)
        totalMoveDifference +=
          agent.validMoves[0].welfare - option.welfare
        moveDifferenceIsFloat = true
        break

  for diseaseId in sim.diseaseRegistry:
    for agentId in sim.activeAgents:
      if sim.agents[agentId].hasDisease(diseaseId):
        inc diseasePrevalence

  for id in sim.deathsThisTimestep:
    let agent = sim.agents[id]
    agentWealthCollected +=
      agent.sugar + agent.spice - (agent.lastSugar + agent.lastSpice)
    collectedWealthIsFloat =
      collectedWealthIsFloat or agent.wealthIsFloat
    if agent.lastActivatedTimestep == sim.timestep:
      if agent.lastMoveOptimal:
        inc optimalMoves
      inc agentMoves

  let count = float64(population)
  var
    meanMetabolism = 0.0
    meanMovement = 0.0
    meanVision = 0.0
    meanWealth = 0.0
    meanAge = 0.0
    meanHappiness = 0.0
    meanWealthHappiness = 0.0
    meanHealthHappiness = 0.0
    meanSocialHappiness = 0.0
    meanFamilyHappiness = 0.0
    meanConflictHappiness = 0.0
    meanSelfishness = 0.0
    meanAgeism = 0.0
    meanRacism = 0.0
    meanSexism = 0.0
    optimalPercentage = 0.0
    meanNeighbors = 0.0
    meanValidMoves = 0.0
    meanMoveRank = 0.0
    meanMoveDifference = 0.0
    meanTradePrice = 0.0
    meanAgeAtDeath = 0.0
    meanDeathsPercentage = 0.0
  if population > 0:
    var combinedMetabolism =
      totalSugarMetabolism + totalSpiceMetabolism
    if totalSugarMetabolism > 0 and totalSpiceMetabolism > 0:
      combinedMetabolism = roundHalfEven(combinedMetabolism / 2.0, 2)
    meanMetabolism = roundHalfEven(combinedMetabolism / count, 2)
    meanMovement = roundHalfEven(totalMovement / count, 2)
    meanVision = roundHalfEven(totalVision / count, 2)
    meanWealth = roundHalfEven(totalWealth / count, 2)
    meanAge = roundHalfEven(totalAge / count, 2)
    meanHappiness = roundHalfEven(totalHappiness / count, 2)
    meanWealthHappiness =
      roundHalfEven(totalWealthHappiness / count, 2)
    meanHealthHappiness =
      roundHalfEven(totalHealthHappiness / count, 2)
    meanSocialHappiness =
      roundHalfEven(totalSocialHappiness / count, 2)
    meanFamilyHappiness =
      roundHalfEven(totalFamilyHappiness / count, 2)
    meanConflictHappiness =
      roundHalfEven(totalConflictHappiness / count, 2)
    meanSelfishness = roundHalfEven(totalSelfishness / count, 2)
    meanAgeism = roundHalfEven(totalAgeism / count, 2)
    meanRacism = roundHalfEven(totalRacism / count, 2)
    meanSexism = roundHalfEven(totalSexism / count, 2)
    agentWealthBurnRate =
      roundHalfEven(agentWealthBurnRate / count, 2)
    agentMeanTimeToLive =
      roundHalfEven(agentMeanTimeToLive / count, 2)
    optimalPercentage =
      roundHalfEven(float64(optimalMoves) / float64(agentMoves) * 100.0, 2)
    meanNeighbors = roundHalfEven(totalNeighbors / count, 2)
    meanValidMoves = roundHalfEven(totalValidMoves / count, 2)
    meanMoveRank = roundHalfEven(totalMoveRank / count, 2)
    if meanNeighbors > 0:
      meanMoveDifference =
        roundHalfEven(totalMoveDifference / meanNeighbors, 2)
    if traders > 0:
      meanTradePrice =
        roundHalfEven(totalTradePrice / float64(traders), 2)
    if sim.deathsThisTimestep.len > 0:
      meanAgeAtDeath = roundHalfEven(
        totalAgeAtDeath / float64(sim.deathsThisTimestep.len),
        2,
      )
      meanDeathsPercentage = roundHalfEven(
        float64(sim.deathsThisTimestep.len) / count * 100.0,
        2,
      )
  else:
    maxWealth = 0
    minWealth = 0
    totalHappiness = 0
  if sim.deathsThisTimestep.len > 0:
    meanAgeAtDeath = roundHalfEven(
      totalAgeAtDeath / float64(sim.deathsThisTimestep.len),
      2,
    )

  sim.meanWealth = meanWealth
  template setFloat(name: string, value: float64) =
    sim.runtimeStats[name] = newJFloat(value)
  template setInt(name: string, value: int64) =
    sim.runtimeStats[name] = newJInt(value)
  template setMean(name: string, value: float64) =
    if population > 0:
      setFloat(name, value)
    else:
      setInt(name, 0)

  setInt("timestep", int64(sim.timestep))
  setInt("population", int64(population))
  setMean("meanMetabolism", meanMetabolism)
  setMean("meanMovement", meanMovement)
  setMean("meanVision", meanVision)
  setMean("meanWealth", meanWealth)
  setMean("meanAge", meanAge)
  if population == 0:
    setInt("giniCoefficient", 0)
  elif totalWealth == 0:
    setInt("giniCoefficient", 1)
  else:
    setFloat("giniCoefficient", sim.giniCoefficient())
  if traders > 0:
    setFloat("meanTradePrice", meanTradePrice)
  else:
    setInt("meanTradePrice", 0)
  setInt("tradeVolume", tradeVolume)
  if maxWealthIsFloat:
    setFloat("maxWealth", roundHalfEven(maxWealth, 2))
  else:
    setInt("maxWealth", int64(maxWealth))
  if minWealthIsFloat:
    setFloat("minWealth", roundHalfEven(minWealth, 2))
  else:
    setInt("minWealth", int64(minWealth))
  setMean("meanHappiness", meanHappiness)
  setMean("meanWealthHappiness", meanWealthHappiness)
  setMean("meanHealthHappiness", meanHealthHappiness)
  setMean("meanSocialHappiness", meanSocialHappiness)
  setMean("meanFamilyHappiness", meanFamilyHappiness)
  setMean("meanConflictHappiness", meanConflictHappiness)
  if sim.deathsThisTimestep.len > 0:
    setFloat("meanAgeAtDeath", meanAgeAtDeath)
  else:
    setInt("meanAgeAtDeath", 0)
  setInt("agentsReplaced", int64(sim.agentsReplacedThisTimestep))
  setInt("agentsBorn", int64(sim.agentsBornThisTimestep.len))
  setInt("agentStarvationDeaths", starvationDeaths)
  setInt("agentDiseaseDeaths", diseaseDeaths)
  setInt("environmentWealthCreated", environmentWealthCreated)
  if totalWealthIsFloat:
    setFloat("agentWealthTotal", roundHalfEven(totalWealth, 2))
  else:
    setInt("agentWealthTotal", int64(totalWealth))
  setInt("environmentWealthTotal", environmentWealthTotal)
  if collectedWealthIsFloat:
    setFloat("agentWealthCollected", agentWealthCollected)
  else:
    setInt("agentWealthCollected", int64(agentWealthCollected))
  setMean("agentWealthBurnRate", agentWealthBurnRate)
  setMean("agentMeanTimeToLive", agentMeanTimeToLive)
  setInt(
    "agentTotalMetabolism",
    int64(totalSugarMetabolism + totalSpiceMetabolism),
  )
  setInt("agentCombatDeaths", combatDeaths)
  setInt("agentAgingDeaths", agingDeaths)
  setInt("agentDeaths", int64(sim.deathsThisTimestep.len))
  if population > 0:
    var
      largestRace = races[0]
      largestTribe = tribes[0]
    for entry in races:
      if entry.count > largestRace.count:
        largestRace = entry
    for entry in tribes:
      if entry.count > largestTribe.count:
        largestTribe = entry
    if largestRace.key < 0:
      sim.runtimeStats["largestRace"] = newJNull()
    else:
      setInt("largestRace", int64(largestRace.key))
    if largestTribe.key < 0:
      sim.runtimeStats["largestTribe"] = newJNull()
    else:
      setInt("largestTribe", int64(largestTribe.key))
    setInt("largestRaceSize", int64(largestRace.count))
    setInt("largestTribeSize", int64(largestTribe.count))
  else:
    setInt("largestRace", 0)
    setInt("largestTribe", 0)
    setInt("largestRaceSize", 0)
    setInt("largestTribeSize", 0)
  setInt("remainingRaces", int64(races.len))
  setInt("remainingTribes", int64(tribes.len))
  setInt("sickAgents", int64(sickAgents))
  setInt("carryingCapacity", int64(sim.carryingCapacity))
  setMean("meanDeathsPercentage", meanDeathsPercentage)
  setMean(
    "sickAgentsPercentage",
    roundHalfEven(float64(sickAgents) / max(count, 1.0) * 100.0, 2),
  )
  setMean("meanSelfishness", meanSelfishness)
  if infectors.len > 0:
    setFloat(
      "diseaseEffectiveReproductionRate",
      roundHalfEven(
        float64(diseaseIncidence) / float64(infectors.len),
        2,
      ),
    )
  else:
    setInt("diseaseEffectiveReproductionRate", 0)
  setInt("diseaseIncidence", int64(diseaseIncidence))
  setInt("diseasePrevalence", int64(diseasePrevalence))
  if population > 0:
    setFloat("agentLastMoveOptimalityPercentage", optimalPercentage)
  else:
    setInt("agentLastMoveOptimalityPercentage", int64(optimalMoves))
  setMean("meanNeighbors", meanNeighbors)
  setMean("meanMoveRank", meanMoveRank)
  if population > 0 and moveDifferenceIsFloat:
    setFloat("meanMoveDifferenceFromOptimal", meanMoveDifference)
  else:
    setInt("meanMoveDifferenceFromOptimal", int64(meanMoveDifference))
  setMean("meanValidMoves", meanValidMoves)
  if population > 0:
    setFloat("totalHappiness", totalHappiness)
  else:
    setInt("totalHappiness", 0)
  setInt("loanVolume", loanVolume)
  setMean("meanAgeismFactor", meanAgeism)
  setMean("meanRacismFactor", meanRacism)
  setMean("meanSexismFactor", meanSexism)
  setInt("moveSpace", int64(moveSpace))
  sim.updateExperimentalStats()
  sim.deathsThisTimestep.setLen(0)
  sim.agentsReplacedThisTimestep = 0
  sim.agentsBornThisTimestep.setLen(0)

proc isExperimental(sim: Simulation, agent: Agent): bool =
  let group = sim.config["experimentalGroup"].getStr()
  if group.startsWith("ageRange"):
    let index = parseInt(group["ageRange".len .. ^1])
    let bounds = sim.config["environmentAgeistAbsoluteRanges"][index]
    return agent.age >= bounds[0].getInt() and
      (agent.age <= bounds[1].getInt() or bounds[1].getInt() == -1)
  if group == "depressed":
    return agent.depressed
  if group.startsWith("disease"):
    let disease = parseInt(group["disease".len .. ^1])
    return agent.hasDisease(disease)
  if group == "female":
    return agent.sex == "female"
  if group == "male":
    return agent.sex == "male"
  if group == "raceInGroup":
    for race in sim.config["environmentInGroupRaces"]:
      if agent.race == race.getInt():
        return true
    return false
  if group.startsWith("race"):
    return agent.race == parseInt(group["race".len .. ^1])
  if group == "sick":
    return agent.diseases.len > 0
  group == agent.decisionModel

proc updateOneGroup(
    sim: var Simulation,
    experimental: bool,
) =
  let
    groupName =
      if experimental: sim.config["experimentalGroup"].getStr()
      else: "control"
  template member(agent: Agent): bool =
    sim.isExperimental(agent) == experimental
  template key(name: string): string =
    groupName & name[0].toUpperAscii() & name[1 .. ^1]
  template setFloat(name: string, value: float64) =
    sim.runtimeStats[key(name)] = newJFloat(value)
  template setInt(name: string, value: int64) =
    sim.runtimeStats[key(name)] = newJInt(value)
  template setMean(name: string, value: float64) =
    if population > 0:
      setFloat(name, value)
    else:
      setInt(name, 0)

  var
    population = 0
    totalAge = 0.0
    totalAgeism = 0.0
    totalConflictHappiness = 0.0
    totalFamilyHappiness = 0.0
    totalHappiness = 0.0
    totalHealthHappiness = 0.0
    totalMovement = 0.0
    totalRacism = 0.0
    totalSelfishness = 0.0
    totalSexism = 0.0
    totalSocialHappiness = 0.0
    totalSpiceMetabolism = 0.0
    totalSugarMetabolism = 0.0
    totalVision = 0.0
    totalWealth = 0.0
    totalWealthIsFloat = false
    totalWealthHappiness = 0.0
    maxWealth = -Inf
    minWealth = Inf
    maxWealthIsFloat = false
    minWealthIsFloat = false
    collected = 0.0
    collectedIsFloat = false
    burnRate = 0.0
    meanTtl = 0.0
    optimalMoves = 0
    agentMoves = 0
    totalNeighbors = 0.0
    totalControlNeighbors = 0.0
    totalExperimentalNeighbors = 0.0
    totalValidMoves = 0.0
    totalMoveRank = 0.0
    totalMoveDifference = 0.0
    moveSpace = 0
    tradePrice = 0.0
    tradeVolume: int64
    loanVolume: int64
    traders = 0
    sickAgents = 0
    diseaseIncidence = 0
    diseasePrevalence = 0
    infectors: seq[int]
    races: seq[tuple[key, count: int]]
    tribes: seq[tuple[key, count: int]]

  for id in sim.activeAgents:
    let agent = sim.agents[id]
    if not member(agent):
      continue
    inc population
    let wealth = agent.sugar + agent.spice
    totalAge += float64(agent.age)
    totalAgeism += agent.decisionModelAgeismFactor
    totalConflictHappiness += agent.conflictHappiness
    totalFamilyHappiness += agent.familyHappiness
    totalHappiness += agent.happiness
    totalHealthHappiness += agent.healthHappiness
    totalMovement += float64(agent.movement)
    totalRacism += agent.decisionModelRacismFactor
    totalSelfishness += agent.selfishnessFactor
    totalSexism += agent.decisionModelSexismFactor
    totalSocialHappiness += agent.socialHappiness
    totalSpiceMetabolism += agent.spiceMetabolism
    totalSugarMetabolism += agent.sugarMetabolism
    totalVision += float64(agent.vision)
    totalWealth += wealth
    totalWealthIsFloat = totalWealthIsFloat or agent.wealthIsFloat
    totalWealthHappiness += agent.wealthHappiness
    if agent.tradeVolume > 0:
      tradePrice += max(agent.spicePrice, agent.sugarPrice)
      tradeVolume += int64(agent.tradeVolume)
      inc traders
    if agent.lastLendedTimestep == sim.timestep:
      loanVolume += int64(agent.lastLoans)
    if agent.diseases.len > 0:
      inc sickAgents
    if not experimental or
        "disease" in sim.config["experimentalGroup"].getStr():
      for infection in agent.diseases:
        if infection.caught == sim.timestep:
          inc diseaseIncidence
          if sim.timestep != 0 and infection.infector >= 0 and
              infection.infector notin infectors:
            infectors.add(infection.infector)
    for neighborId in agent.movementNeighborhood:
      if sim.isExperimental(sim.agents[neighborId]):
        totalExperimentalNeighbors += 1
      else:
        totalControlNeighbors += 1
    if wealth > maxWealth:
      maxWealth = wealth
      maxWealthIsFloat = agent.wealthIsFloat
    if wealth < minWealth:
      minWealth = wealth
      minWealthIsFloat = agent.wealthIsFloat
    collected += wealth - (agent.lastSugar + agent.lastSpice)
    collectedIsFloat = collectedIsFloat or agent.wealthIsFloat
    burnRate += timeToLive(agent, false)
    meanTtl += timeToLive(agent, true)
    if agent.lastMoveOptimal:
      inc optimalMoves
    inc agentMoves
    totalNeighbors += float64(agent.movementNeighborhood.len)
    totalValidMoves += float64(agent.validMoves.len)
    moveSpace += agent.lastValidMoves
    for index, option in agent.validMoves:
      if option.cell == agent.cell:
        totalMoveRank += float64(index)
        totalMoveDifference +=
          agent.validMoves[0].welfare - option.welfare
        break
    var found = false
    for entry in races.mitems:
      if entry.key == agent.race:
        inc entry.count
        found = true
        break
    if not found:
      races.add((agent.race, 1))
    found = false
    for entry in tribes.mitems:
      if entry.key == agent.tribe:
        inc entry.count
        found = true
        break
    if not found:
      tribes.add((agent.tribe, 1))

  var
    deadCount = 0
    ageAtDeath = 0.0
    agingDeaths: int64
    combatDeaths: int64
    diseaseDeaths: int64
    starvationDeaths: int64
  for id in sim.deathsThisTimestep:
    let agent = sim.agents[id]
    if not member(agent):
      continue
    inc deadCount
    ageAtDeath += float64(agent.age)
    case agent.causeOfDeath
    of "aging": inc agingDeaths
    of "combat": inc combatDeaths
    of "starvation": inc starvationDeaths
    else: discard
    if agent.diseaseDeath:
      inc diseaseDeaths
    collected +=
      agent.sugar + agent.spice -
      (agent.lastSugar + agent.lastSpice)
    collectedIsFloat = collectedIsFloat or agent.wealthIsFloat
    if agent.lastActivatedTimestep == sim.timestep:
      if agent.lastMoveOptimal:
        inc optimalMoves
      inc agentMoves

  if not experimental or
      "disease" in sim.config["experimentalGroup"].getStr():
    for diseaseId in sim.diseaseRegistry:
      for agentId in sim.activeAgents:
        if sim.agents[agentId].hasDisease(diseaseId):
          inc diseasePrevalence

  var
    largestRace = (key: 0, count: 0)
    largestTribe = (key: 0, count: 0)
  for entry in races:
    if entry.count > largestRace.count:
      largestRace = entry
  for entry in tribes:
    if entry.count > largestTribe.count:
      largestTribe = entry

  let count = float64(population)
  template mean(value: float64): float64 =
    if population > 0: roundHalfEven(value / count, 2)
    else: 0.0
  var combinedMetabolism =
    totalSugarMetabolism + totalSpiceMetabolism
  if totalSugarMetabolism > 0 and totalSpiceMetabolism > 0:
    combinedMetabolism = roundHalfEven(combinedMetabolism / 2, 2)
  let
    meanNeighbors = mean(totalNeighbors)
    meanControlNeighbors = mean(totalControlNeighbors)
    meanExperimentalNeighbors = mean(totalExperimentalNeighbors)
    meanMoveDifference =
      if meanNeighbors > 0:
        roundHalfEven(totalMoveDifference / meanNeighbors, 2)
      else:
        0.0

  setInt("agentAgingDeaths", agingDeaths)
  setInt("agentCombatDeaths", combatDeaths)
  setInt("agentDeaths", int64(deadCount))
  setInt("agentDiseaseDeaths", diseaseDeaths)
  setMean("agentMeanTimeToLive", mean(meanTtl))
  var groupBirths = 0
  for id in sim.agentsBornThisTimestep:
    if member(sim.agents[id]):
      inc groupBirths
  setInt("agentsBorn", int64(groupBirths))
  setInt("agentsReplaced", 0)
  setInt("agentStarvationDeaths", starvationDeaths)
  setInt(
    "agentTotalMetabolism",
    int64(totalSugarMetabolism + totalSpiceMetabolism),
  )
  setMean("agentWealthBurnRate", mean(burnRate))
  if collectedIsFloat:
    setFloat("agentWealthCollected", collected)
  else:
    setInt("agentWealthCollected", int64(collected))
  if totalWealthIsFloat:
    setFloat("agentWealthTotal", roundHalfEven(totalWealth, 2))
  else:
    setInt("agentWealthTotal", int64(totalWealth))
  setInt("carryingCapacity", int64(sim.carryingCapacity))
  setInt("largestRace", int64(largestRace.key))
  setInt("largestRaceSize", int64(largestRace.count))
  setInt("largestTribe", int64(largestTribe.key))
  setInt("largestTribeSize", int64(largestTribe.count))
  if population == 0:
    setInt("maxWealth", 0)
    setInt("minWealth", 0)
  else:
    if maxWealthIsFloat:
      setFloat("maxWealth", roundHalfEven(maxWealth, 2))
    else:
      setInt("maxWealth", int64(maxWealth))
    if minWealthIsFloat:
      setFloat("minWealth", roundHalfEven(minWealth, 2))
    else:
      setInt("minWealth", int64(minWealth))
  setMean("meanAge", mean(totalAge))
  if deadCount > 0:
    setFloat("meanAgeAtDeath", roundHalfEven(ageAtDeath / float64(deadCount), 2))
  else:
    setInt("meanAgeAtDeath", 0)
  setMean("meanConflictHappiness", mean(totalConflictHappiness))
  setMean("meanFamilyHappiness", mean(totalFamilyHappiness))
  setMean("meanHappiness", mean(totalHappiness))
  setMean("meanHealthHappiness", mean(totalHealthHappiness))
  setMean("meanMetabolism", mean(combinedMetabolism))
  setMean("meanMovement", mean(totalMovement))
  setMean("meanMoveDifferenceFromOptimal", meanMoveDifference)
  setMean("meanMoveRank", mean(totalMoveRank))
  setMean("meanNeighbors", meanNeighbors)
  setMean("meanSelfishness", mean(totalSelfishness))
  setMean("meanSocialHappiness", mean(totalSocialHappiness))
  if traders > 0:
    setFloat("meanTradePrice", roundHalfEven(tradePrice / float64(traders), 2))
  else:
    setInt("meanTradePrice", 0)
  setMean("meanWealth", mean(totalWealth))
  setMean("meanWealthHappiness", mean(totalWealthHappiness))
  setMean("meanValidMoves", mean(totalValidMoves))
  setMean("meanVision", mean(totalVision))
  setInt("population", int64(population))
  setInt("sickAgents", int64(sickAgents))
  if population > 0:
    setFloat("totalHappiness", totalHappiness)
  else:
    setInt("totalHappiness", 0)
  setInt("remainingRaces", int64(races.len))
  setInt("remainingTribes", int64(tribes.len))
  setInt("tradeVolume", tradeVolume)
  setMean(
    "meanDeathsPercentage",
    roundHalfEven(float64(deadCount) / max(count, 1.0) * 100, 2),
  )
  setMean(
    "sickAgentsPercentage",
    roundHalfEven(float64(sickAgents) / max(count, 1.0) * 100, 2),
  )
  if infectors.len > 0:
    setFloat(
      "diseaseEffectiveReproductionRate",
      roundHalfEven(float64(diseaseIncidence) / float64(infectors.len), 2),
    )
  else:
    setInt("diseaseEffectiveReproductionRate", 0)
  setInt("diseaseIncidence", int64(diseaseIncidence))
  setInt("diseasePrevalence", int64(diseasePrevalence))
  if population > 0:
    setFloat(
      "agentLastMoveOptimalityPercentage",
      roundHalfEven(float64(optimalMoves) / float64(agentMoves) * 100, 2),
    )
  else:
    setInt("agentLastMoveOptimalityPercentage", int64(optimalMoves))
  setMean("meanAgeismFactor", mean(totalAgeism))
  setMean("meanRacismFactor", mean(totalRacism))
  setMean("meanSexismFactor", mean(totalSexism))
  setInt("loanVolume", loanVolume)
  setInt("moveSpace", int64(moveSpace))
  setMean("meanControlNeighbors", meanControlNeighbors)
  setMean("meanExperimentalNeighbors", meanExperimentalNeighbors)

proc updateExperimentalStats(sim: var Simulation) =
  if sim.config["experimentalGroup"].kind == JNull:
    return
  sim.updateOneGroup(true)
  sim.updateOneGroup(false)
  var
    totalControl = 0.0
    totalExperimental = 0.0
  for id in sim.activeAgents:
    for neighborId in sim.agents[id].movementNeighborhood:
      if sim.isExperimental(sim.agents[neighborId]):
        totalExperimental += 1
      else:
        totalControl += 1
  let count = float64(sim.activeAgents.len)
  if count > 0:
    sim.runtimeStats["meanControlNeighbors"] =
      newJFloat(roundHalfEven(totalControl / count, 2))
    sim.runtimeStats["meanExperimentalNeighbors"] =
      newJFloat(roundHalfEven(totalExperimental / count, 2))
  else:
    sim.runtimeStats["meanControlNeighbors"] = newJInt(0)
    sim.runtimeStats["meanExperimentalNeighbors"] = newJInt(0)
  for experimental in [false, true]:
    let actorGroup =
      if experimental: "ExperimentalGroup"
      else: "ControlGroup"
    var
      combatControl = 0
      combatExperimental = 0
      diseaseControl = 0
      diseaseExperimental = 0
      lendingControl = 0
      lendingExperimental = 0
      reproductionControl = 0
      reproductionExperimental = 0
      tradeControl = 0
      tradeExperimental = 0
    for collection in [sim.activeAgents, sim.deathsThisTimestep]:
      for id in collection:
        let agent = sim.agents[id]
        if sim.isExperimental(agent) != experimental:
          continue
        combatControl += agent.combatWithControlGroup
        combatExperimental += agent.combatWithExperimentalGroup
        diseaseControl += agent.diseaseWithControlGroup
        diseaseExperimental += agent.diseaseWithExperimentalGroup
        lendingControl += agent.lendingWithControlGroup
        lendingExperimental += agent.lendingWithExperimentalGroup
        reproductionControl += agent.reproductionWithControlGroup
        reproductionExperimental += agent.reproductionWithExperimentalGroup
        tradeControl += agent.tradeWithControlGroup
        tradeExperimental += agent.tradeWithExperimentalGroup
    template interaction(
        action, target: string,
        value: int,
      ) =
      sim.runtimeStats[
        action & actorGroup & "To" & target & "Group"
      ] = newJInt(value)
    interaction("combat", "Control", combatControl)
    interaction("combat", "Experimental", combatExperimental)
    interaction("disease", "Control", diseaseControl)
    interaction("disease", "Experimental", diseaseExperimental)
    interaction("lending", "Control", lendingControl)
    interaction("lending", "Experimental", lendingExperimental)
    interaction("reproduction", "Control", reproductionControl)
    interaction(
      "reproduction",
      "Experimental",
      reproductionExperimental,
    )
    interaction("trade", "Control", tradeControl)
    interaction("trade", "Experimental", tradeExperimental)

  for collection in [sim.activeAgents, sim.deathsThisTimestep]:
    for id in collection:
      sim.agents[id].combatWithControlGroup = 0
      sim.agents[id].combatWithExperimentalGroup = 0
      sim.agents[id].diseaseWithControlGroup = 0
      sim.agents[id].diseaseWithExperimentalGroup = 0
      sim.agents[id].lendingWithControlGroup = 0
      sim.agents[id].lendingWithExperimentalGroup = 0
      sim.agents[id].reproductionWithControlGroup = 0
      sim.agents[id].reproductionWithExperimentalGroup = 0
      sim.agents[id].tradeWithControlGroup = 0
      sim.agents[id].tradeWithExperimentalGroup = 0

proc findCellsInRange(sim: Simulation, agent: Agent): seq[RangeEntry] =
  let cellRange =
    min(min(vision(agent), movement(agent)), sim.environment.maxCellDistance)
  if cellRange <= 0:
    return
  for distance in 1 .. cellRange:
    for rangeEntry in sim.environment.ranges[agent.cell][distance]:
      var found = false
      for existing in result.mitems:
        if existing.cell == rangeEntry.cell:
          existing.distance = rangeEntry.distance
          found = true
          break
      if not found:
        result.add(rangeEntry)

proc sortCandidates(candidates: var seq[MoveCandidate]) =
  for index in 0 ..< candidates.len:
    var current = index
    while current > 0 and
        (
          candidates[current - 1].welfare < candidates[current].welfare or
          (
            candidates[current - 1].welfare == candidates[current].welfare and
            candidates[current - 1].distance > candidates[current].distance
          )
        ):
      swap(candidates[current - 1], candidates[current])
      dec current

proc welfareRewards(
    agent: Agent,
    sugarReward, spiceReward: float64,
): float64
proc canReach(agent: Agent, cell: int): bool
proc ethicalValue(
    sim: var Simulation,
    id, cell: int,
): tuple[value, happiness, unhappiness: float64]
proc ethicalBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
    greedy: int,
): int

proc sortedEthicalIndices(
    candidates: openArray[MoveCandidate],
    scores: openArray[float64],
): seq[int] =
  result = newSeq[int](candidates.len)
  for index in 0 ..< candidates.len:
    result[index] = index
  for index in 1 ..< result.len:
    var current = index
    while current > 0:
      let
        left = result[current - 1]
        right = result[current]
      if scores[left] > scores[right] or
          (
            scores[left] == scores[right] and
            candidates[left].distance <= candidates[right].distance
          ):
        break
      swap(result[current - 1], result[current])
      dec current

proc temperanceScore(
    sim: var Simulation,
    id, cell: int,
): float64 =
  let delta =
    sim.timeToLiveAt(sim.agents[id], cell) -
    sim.agents[id].timeToLive
  if not sim.agents[id].temperancePecs:
    return abs(delta)
  if sim.agents[id].temperanceTotalMetabolism == 0:
    return 0

  let physical =
    if sim.agents[id].timeToLive > 0:
      erf(1 / sim.agents[id].timeToLive)
    else:
      1.0
  var emotionalScore = 0.0
  if delta > 1:
    emotionalScore -= float64(sim.agents[id].timesOverharvested)
    inc sim.agents[id].timesOverharvested
  let emotional = erf(emotionalScore)

  var cognitiveScore = 0.0
  if delta < 1:
    cognitiveScore = -1
  elif delta < 2 and sim.agents[id].temperanceRules[0] != 0:
    cognitiveScore += float64(sim.agents[id].temperanceRules[0])
  elif delta < 3 and sim.agents[id].temperanceRules[1] != 0:
    cognitiveScore += float64(sim.agents[id].temperanceRules[1])
    if sim.agents[id].temperanceRules[2] != 0:
      cognitiveScore -= float64(sim.agents[id].temperanceRules[2])
  elif delta >= 3 and sim.agents[id].temperanceRules[3] != 0:
    cognitiveScore -= float64(sim.agents[id].temperanceRules[3])
    if sim.agents[id].temperanceRules[4] != 0:
      cognitiveScore -= float64(sim.agents[id].temperanceRules[4])
  let cognitive = erf(cognitiveScore)

  var socialScore = 0.0
  if delta <= 1:
    socialScore = 1
  elif delta <= 2:
    socialScore -= float64(sim.agents[id].timeSeenOverconsuming)
  else:
    socialScore -= float64(sim.agents[id].timesSeenIndulging)
  let social = erf(
    socialScore * sim.agents[id].temperanceSocialPressure
  )
  physical + emotional + cognitive + social

proc temperanceBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
): int =
  var scores = newSeq[float64](candidates.len)
  for index, candidate in candidates:
    scores[index] = sim.temperanceScore(id, candidate.cell)
  let order = sortedEthicalIndices(candidates, scores)
  if sim.agents[id].temperancePecs:
    return candidates[order[0]].cell
  let virtueRoll = sim.rng.randomFloat()
  if virtueRoll < sim.agents[id].decisionModelFactor:
    sim.agents[id].decisionModelFactor = min(
      1.0,
      roundHalfEven(
        sim.agents[id].decisionModelFactor +
        sim.agents[id].dynamicDecisionModelFactor,
        2,
      ),
    )
    candidates[order[0]].cell
  else:
    sim.agents[id].decisionModelFactor = max(
      0.0,
      roundHalfEven(
        sim.agents[id].decisionModelFactor -
        sim.agents[id].dynamicDecisionModelFactor,
        2,
      ),
    )
    candidates[order[^1]].cell

proc asimovValue(sim: Simulation, id, cell: int): float64 =
  let
    actor = sim.agents[id]
    target = sim.environment.cells[cell]
    occupant = target.agent
    loot =
      if occupant >= 0:
        min(
          sim.agents[occupant].sugar + sim.agents[occupant].spice,
          sim.environment.maxCombatLoot * 2,
        )
      else:
        0.0
  var modifier =
    if float64(target.spice) + actor.spice -
        spiceMetabolism(actor) > 0 and
        float64(target.sugar) + actor.sugar -
        sugarMetabolism(actor) > 0:
      1.0
    elif float64(target.spice) + actor.spice -
        spiceMetabolism(actor) <= 0 and
        float64(target.sugar) + actor.sugar -
        sugarMetabolism(actor) <= 0:
      -1.0
    else:
      0.0
  for neighborId in actor.movementNeighborhood:
    let neighbor = sim.agents[neighborId]
    if occupant == neighborId and
        actor.decisionModel != neighbor.decisionModel:
      return -float64(high(int))
    if not neighbor.canReach(cell):
      modifier += 1
    elif actor.decisionModel != neighbor.decisionModel and
        (
          float64(target.spice) + neighbor.spice -
            spiceMetabolism(neighbor) <= 0 or
          float64(target.sugar) + neighbor.sugar -
            sugarMetabolism(neighbor) <= 0
        ):
      return -float64(high(int))
  modifier * (float64(target.sugar + target.spice) + loot)

proc asimovRecommendation(
    sim: var Simulation,
    asimovId, neighborId, cell: int,
): float64 =
  let neighbor = sim.agents[neighborId]
  if neighbor.decisionModelFactor > 0 and
      neighbor.decisionModel != sim.agents[asimovId].decisionModel and
      neighbor.decisionModel != "none":
    if "temperance" in neighbor.decisionModel:
      return sim.temperanceScore(neighborId, cell)
    return sim.ethicalValue(neighborId, cell).value
  if neighbor.decisionModel == "none":
    let occupant = sim.environment.cells[cell].agent
    if occupant >= 0 and
        "asimov" in sim.agents[occupant].decisionModel:
      let
        aggression = max(
          0.0,
          neighbor.aggressionFactor + neighbor.aggressionFactorModifier,
        )
        sugarLoot = aggression * min(
          sim.environment.maxCombatLoot,
          sim.agents[occupant].sugar,
        )
        spiceLoot = aggression * min(
          sim.environment.maxCombatLoot,
          sim.agents[occupant].spice,
        )
        target = sim.environment.cells[cell]
      return welfareRewards(
        neighbor,
        (float64(target.sugar) + sugarLoot) /
          (1 + target.pollution),
        (float64(target.spice) + spiceLoot) /
          (1 + target.pollution),
      )

proc asimovBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
): int =
  var scores = newSeq[float64](candidates.len)
  for index, candidate in candidates:
    scores[index] = sim.asimovValue(id, candidate.cell)
  let order = sortedEthicalIndices(candidates, scores)
  var best = -1
  for index in order:
    let cell = candidates[index].cell
    for neighborId in sim.agents[id].movementNeighborhood:
      if "asimov" notin sim.agents[neighborId].decisionModel and
          sim.agents[neighborId].canReach(cell) and
          sim.asimovRecommendation(id, neighborId, cell) > 0:
        best = cell
    if best < 0 and scores[index] > 0:
      best = cell
      break
  if best >= 0: best else: sim.agents[id].cell

proc benthamBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
    greedy: int,
): int

proc groupBiasModifier(
    sim: Simulation,
    id, cell: int,
): float64 =
  let actor = sim.agents[id]
  var neighbors: seq[int]
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighbor =
      sim.environment.cells[
        sim.environment.cells[cell].neighbors[index]
      ].agent
    if neighbor >= 0:
      neighbors.add(neighbor)
  result = 1
  if neighbors.len == 0:
    return
  var
    inGroupAge = 0
    inGroupRace = 0
    inGroupSex = 0
    inGroupTribe = 0
  for neighborId in neighbors:
    let neighbor = sim.agents[neighborId]
    var ageInGroup =
      abs(neighbor.age - actor.age) <=
      sim.config["environmentAgeistRelativeRange"].getInt()
    for bounds in sim.config["environmentAgeistAbsoluteRanges"]:
      if neighbor.age >= bounds[0].getInt() and
          (
            neighbor.age <= bounds[1].getInt() or
            bounds[1].getInt() == -1
          ):
        ageInGroup = true
        break
    if ageInGroup:
      inc inGroupAge
    var raceInGroup = neighbor.race == actor.race
    for race in sim.config["environmentInGroupRaces"]:
      if neighbor.race == race.getInt():
        raceInGroup = true
        break
    if raceInGroup:
      inc inGroupRace
    if neighbor.sex == actor.sex:
      inc inGroupSex
    if neighbor.tribe == actor.tribe:
      inc inGroupTribe

  let count = float64(neighbors.len)
  template applyBias(factor: float64, members: int) =
    if factor > 0:
      let proportion = float64(members) / count
      result *=
        1 + factor * proportion +
        (1 - factor) * (1 - proportion)
  applyBias(actor.decisionModelAgeismFactor, inGroupAge)
  applyBias(actor.decisionModelRacismFactor, inGroupRace)
  var actorIsSexist = false
  for group in sim.config["environmentSexistGroups"]:
    if actor.sex == group.getStr():
      actorIsSexist = true
      break
  if actorIsSexist:
    applyBias(actor.decisionModelSexismFactor, inGroupSex)
  applyBias(actor.decisionModelTribalFactor, inGroupTribe)

proc bestCell(
    sim: var Simulation,
    id: int,
    populationPolicy: PopulationPolicy,
): int =
  if sim.agents[id].cellsInRange.len == 0:
    sim.agents[id].lastMoveRank = 0
    sim.agents[id].lastValidMoves = 1
    sim.agents[id].lastMoveOptimal = true
    if sim.agents[id].decisionModelFactor > 0 and
        sim.agents[id].decisionModel != "none":
      let previousNeighborhood = sim.agents[id].movementNeighborhood
      sim.agents[id].movementNeighborhood = @[id]
      discard sim.ethicalBestCell(
        id,
        @[
          MoveCandidate(
            cell: sim.agents[id].cell,
            welfare: 0.0,
            distance: 0,
          )
        ],
        sim.agents[id].cell,
      )
      sim.agents[id].movementNeighborhood = previousNeighborhood
    return sim.agents[id].cell

  sim.agents[id].movementNeighborhood.setLen(0)
  for candidate in sim.agents[id].cellsInRange:
    let occupant = sim.environment.cells[candidate.cell].agent
    if occupant >= 0 and sim.agents[occupant].alive:
      sim.agents[id].movementNeighborhood.add(occupant)
  sim.agents[id].movementNeighborhood.add(id)

  var candidates = sim.agents[id].cellsInRange
  sim.rng.shuffle(candidates)

  var retaliators: seq[tuple[tribe: int, wealth: float64]]
  for candidate in sim.agents[id].cellsInRange:
    let occupant = sim.environment.cells[candidate.cell].agent
    if occupant < 0:
      continue
    let
      tribe = sim.agents[occupant].tribe
      wealth = sim.agents[occupant].sugar + sim.agents[occupant].spice
    var found = false
    for entry in retaliators.mitems:
      if entry.tribe == tribe:
        entry.wealth = max(entry.wealth, wealth)
        found = true
        break
    if not found:
      retaliators.add((tribe: tribe, wealth: wealth))

  let aggression = max(
    0.0,
    sim.agents[id].aggressionFactor +
    sim.agents[id].aggressionFactorModifier,
  )
  var ranked = newSeqOfCap[MoveCandidate](candidates.len)
  for candidate in candidates:
    let occupant = sim.environment.cells[candidate.cell].agent
    if occupant >= 0:
      let
        attackerWealth =
          sim.agents[id].sugar + sim.agents[id].spice
        preyWealth =
          sim.agents[occupant].sugar + sim.agents[occupant].spice
      if aggression <= 0 or
          sim.agents[id].tribe == sim.agents[occupant].tribe or
          attackerWealth < preyWealth:
        continue
    let
      preySugar =
        if occupant >= 0:
          aggression * min(
            sim.environment.maxCombatLoot,
            sim.agents[occupant].sugar,
          )
        else:
          0.0
      preySpice =
        if occupant >= 0:
          aggression * min(
            sim.environment.maxCombatLoot,
            sim.agents[occupant].spice,
          )
        else:
          0.0
      target = sim.environment.cells[candidate.cell]
      baseCandidateWelfare = welfareRewards(
        sim.agents[id],
        (float64(target.sugar) + preySugar) / (1 + target.pollution),
        (float64(target.spice) + preySpice) / (1 + target.pollution),
      )
      candidateWelfare =
        if sim.agents[id].decisionModelAgeismFactor >= 0 or
            sim.agents[id].decisionModelRacismFactor >= 0 or
            sim.agents[id].decisionModelSexismFactor >= 0 or
            sim.agents[id].decisionModelTribalFactor >= 0:
          baseCandidateWelfare * sim.groupBiasModifier(id, candidate.cell)
        else:
          baseCandidateWelfare
    if occupant >= 0:
      var retaliationWealth = 0.0
      for entry in retaliators:
        if entry.tribe == sim.agents[occupant].tribe:
          retaliationWealth = entry.wealth
          break
      if retaliationWealth >
          sim.agents[id].sugar + sim.agents[id].spice +
          candidateWelfare:
        continue
    ranked.add(
      MoveCandidate(
        cell: candidate.cell,
        welfare: candidateWelfare,
        distance: candidate.distance,
      )
    )

  if ranked.len == 0:
    sim.agents[id].lastMoveRank = 0
    sim.agents[id].lastValidMoves = 1
    sim.agents[id].lastMoveOptimal = true
    sim.agents[id].validMoves = @[
      MoveOption(cell: sim.agents[id].cell, welfare: 0.0)
    ]
    if sim.agents[id].decisionModelFactor > 0 and
        sim.agents[id].decisionModel != "none":
      discard sim.ethicalBestCell(
        id,
        @[
          MoveCandidate(
            cell: sim.agents[id].cell,
            welfare: 0.0,
            distance: 0,
          )
        ],
        sim.agents[id].cell,
      )
    return sim.agents[id].cell

  ranked.sortCandidates()
  sim.agents[id].lastValidMoves = ranked.len
  sim.agents[id].validMoves.setLen(0)
  for candidate in ranked:
    sim.agents[id].validMoves.add(
      MoveOption(cell: candidate.cell, welfare: candidate.welfare)
    )
  var destination =
    if populationPolicy != nil:
      populationPolicy(sim, id, ranked, ranked[0].cell)
    elif sim.agents[id].decisionModelFactor > 0 and
        sim.agents[id].decisionModel != "none":
      sim.ethicalBestCell(id, ranked, ranked[0].cell)
    else:
      ranked[0].cell
  var legalDestination = false
  for candidate in ranked:
    if candidate.cell == destination:
      legalDestination = true
      break
  if not legalDestination:
    destination = ranked[0].cell
  sim.agents[id].lastMoveRank = 0
  for index, candidate in ranked:
    if candidate.cell == destination:
      sim.agents[id].lastMoveRank = index
      break
  sim.agents[id].lastMoveOptimal = destination == ranked[0].cell
  destination

proc killAgent(sim: var Simulation, id: int, cause: string) =
  if not sim.agents[id].alive:
    return
  sim.agents[id].alive = false
  sim.agents[id].causeOfDeath = cause
  sim.agents[id].diseaseDeath = sim.agents[id].diseases.len > 0
  # Upstream calls doInheritance for every death. Besides distributing an
  # estate, it clamps debts before the deceased agent enters runtime stats.
  if sim.agents[id].inheritancePolicy != "none":
    if sim.agents[id].sugar < 0:
      sim.agents[id].sugar = 0
      sim.agents[id].sugarIsFloat = false
    if sim.agents[id].spice < 0:
      sim.agents[id].spice = 0
      sim.agents[id].spiceIsFloat = false
    var heirs: seq[int]
    case sim.agents[id].inheritancePolicy
    of "children", "sons", "daughters":
      for child in sim.agents[id].children:
        if not sim.agents[child].alive:
          continue
        if sim.agents[id].inheritancePolicy == "sons" and
            sim.agents[child].sex != "male":
          continue
        if sim.agents[id].inheritancePolicy == "daughters" and
            sim.agents[child].sex != "female":
          continue
        heirs.add(child)
    of "friends":
      for friend in sim.agents[id].friends:
        if sim.agents[friend.agent].alive:
          heirs.add(friend.agent)
    else:
      discard
    if heirs.len > 0:
      let
        sugarShare = sim.agents[id].sugar / float64(heirs.len)
        spiceShare = sim.agents[id].spice / float64(heirs.len)
      for heir in heirs:
        sim.agents[heir].sugar += sugarShare
        sim.agents[heir].spice += spiceShare
        sim.agents[heir].sugarIsFloat = true
        sim.agents[heir].spiceIsFloat = true
        sim.agents[heir].wealthIsFloat = true
        sim.agents[id].sugar -= sugarShare
        sim.agents[id].spice -= spiceShare
        sim.agents[id].sugarIsFloat = true
        sim.agents[id].spiceIsFloat = true
      sim.agents[id].wealthIsFloat = true
  for infection in sim.agents[id].diseases:
    sim.agents[id].recover(sim.diseases[infection.disease])
  sim.agents[id].diseases.setLen(0)
  sim.deathsThisTimestep.add(id)
  if sim.agents[id].cell >= 0:
    sim.environment.cells[sim.agents[id].cell].agent = -1
    sim.agents[id].cell = -1

proc resetFromTemplate(templateAgent: Agent, id, born, cell: int): Agent =
  result = templateAgent
  result.id = id
  result.born = born
  result.cell = cell
  result.alive = true
  result.causeOfDeath = ""
  result.diseaseDeath = false
  result.age = 0
  result.sugar = result.startingSugar
  result.spice = result.startingSpice
  result.lastMovedTimestep = -1
  result.lastActivatedTimestep = born
  result.lastSugar = 0
  result.lastSpice = 0
  result.lastSugarIsFloat = false
  result.lastSpiceIsFloat = false
  result.lastPollution = 0
  result.lastPollutionIsFloat = false
  result.lastTimeToLive = 0
  result.timeToLive = 0
  result.lastMoveRank = 0
  result.lastValidMoves = 0
  result.lastMoveOptimal = true
  result.lastCombatTimestep = -1
  result.lastTradeTimestep = -1
  result.lastSpreadDiseaseTimestep = -1
  result.lastTradePartners = 0
  result.lastDiseasesSpread = 0
  result.lastPreyWealth = 0
  result.lastUniversalSpiceIncomeTimestep = 0
  result.lastUniversalSugarIncomeTimestep = 0
  result.marginalRateOfSubstitution = 1
  result.tradeVolume = 0
  result.sugarPrice = 0
  result.spicePrice = 0
  result.cellsInRange = @[]
  result.movementNeighborhood = @[]
  result.neighbors = @[]
  result.validMoves = @[]
  result.friends = @[]
  result.diseases = @[]
  result.creditorLoans = @[]
  result.debtorLoans = @[]
  result.lastLendedTimestep = -1
  result.lastLoans = 0
  result.sugarMeanIncome = 1
  result.spiceMeanIncome = 1
  result.happiness = 0
  result.conflictHappiness = 0
  result.familyHappiness = 0
  result.healthHappiness = 0
  result.socialHappiness = 0
  result.wealthHappiness = 0
  result.combatWithControlGroup = 0
  result.combatWithExperimentalGroup = 0
  result.diseaseWithControlGroup = 0
  result.diseaseWithExperimentalGroup = 0
  result.lendingWithControlGroup = 0
  result.lendingWithExperimentalGroup = 0
  result.reproductionWithControlGroup = 0
  result.reproductionWithExperimentalGroup = 0
  result.tradeWithControlGroup = 0
  result.tradeWithExperimentalGroup = 0

proc replaceAgents(sim: var Simulation) =
  let target = sim.config["agentReplacements"].getInt()
  if sim.activeAgents.len >= target or sim.agentTemplates.len == 0:
    return

  var quadrants = activeQuadrants(sim.config, sim.environment)
  for quadrant in quadrants.mitems:
    var emptyCells = newSeqOfCap[int](quadrant.len)
    for cell in quadrant:
      if sim.environment.cells[cell].agent < 0:
        emptyCells.add(cell)
    quadrant = emptyCells
    sim.rng.shuffle(quadrant)

  var quadrantIndices = newSeq[int](quadrants.len)
  for index in 0 ..< quadrantIndices.len:
    quadrantIndices[index] = index
  sim.rng.shuffle(quadrantIndices)
  if quadrantIndices.len == 0:
    return

  var totalEmpty = 0
  for quadrant in quadrants:
    totalEmpty += quadrant.len
  let requested = min(target - sim.activeAgents.len, totalEmpty)
  for replacement in 0 ..< requested:
    let quadrantIndex =
      quadrantIndices[replacement mod quadrantIndices.len]
    if quadrants[quadrantIndex].len == 0:
      break
    let
      cell = quadrants[quadrantIndex].pop()
      templateIndex =
        sim.agentEndowmentIndex mod sim.agentTemplates.len
      id = sim.nextAgentId
    inc sim.agentEndowmentIndex
    inc sim.nextAgentId
    var agent = resetFromTemplate(
      sim.agentTemplates[templateIndex],
      id,
      sim.timestep,
      cell,
    )
    if sim.config["environmentTribePerQuadrant"].getBool():
      agent.tags =
        generateTribeTags(sim.config, quadrantIndex, sim.rng)
      agent.endowmentIndex = -1
      agent.tribe = agent.findTribe(sim.config)
    agent.cellsInRange = sim.findCellsInRange(agent)
    sim.agents.add(agent)
    sim.activeAgents.add(id)
    sim.environment.cells[cell].agent = id
    inc sim.agentsReplacedThisTimestep

proc marginalRate(agent: Agent): float64 =
  let
    spiceMet = spiceMetabolism(agent)
    sugarMet = sugarMetabolism(agent)
    spiceNeed =
      if spiceMet > 0:
        agent.spice / spiceMet
      else:
        1.0
    sugarNeed =
      if sugarMet > 0:
        agent.sugar / sugarMet
      else:
        1.0
  agent.tradeFactor * (spiceNeed / sugarNeed)

proc newMarginalRate(agent: Agent, sugar, spice: float64): float64 =
  let
    spiceMet = spiceMetabolism(agent)
    sugarMet = sugarMetabolism(agent)
    spiceNeed =
      if spiceMet > 0:
        spice / spiceMet
      else:
        1.0
    sugarNeed =
      if sugarMet > 0:
        sugar / sugarMet
      else:
        1.0
  if spiceNeed == 1 and sugarNeed == 1:
    return 1
  if spiceNeed == 0:
    return spiceMet
  if sugarNeed == 0:
    return 1 / sugarMet
  spiceNeed / sugarNeed

proc welfareRewards(
    agent: Agent,
    sugarReward, spiceReward: float64,
): float64 =
  let
    sugarMet = sugarMetabolism(agent)
    spiceMet = spiceMetabolism(agent)
    totalMetabolism = sugarMet + spiceMet
    baseSugarProportion =
      if totalMetabolism == 0:
        0.0
      else:
        sugarMet / totalMetabolism
    baseSpiceProportion =
      if totalMetabolism == 0:
        0.0
      else:
        spiceMet / totalMetabolism
    totalSugar = max(
      0.0,
      agent.sugar + sugarReward -
      sugarMet * agent.lookaheadFactor,
    )
    totalSpice = max(
      0.0,
      agent.spice + spiceReward -
      spiceMet * agent.lookaheadFactor,
    )
  var
    sugarProportion = baseSugarProportion
    spiceProportion = baseSpiceProportion
  if agent.tagPreferences and agent.tags.len > 0:
    let
      zeroFraction =
        float64(agent.tagZeroes) / float64(agent.tags.len)
      oneFraction = 1 - zeroFraction
    var preference =
      sugarMet * zeroFraction +
      spiceMet * oneFraction
    if preference <= 0:
      preference = 1
    sugarProportion =
      sugarMet / preference * zeroFraction
    spiceProportion =
      spiceMet / preference * oneFraction
  pow(totalSugar, sugarProportion) * pow(totalSpice, spiceProportion)

proc canReach(agent: Agent, cell: int): bool =
  if agent.cell == cell:
    return true
  for entry in agent.cellsInRange:
    if entry.cell == cell:
      return true

proc ethicalValue(
    sim: var Simulation,
    id, cell: int,
): tuple[value, happiness, unhappiness: float64] =
  let
    actor = sim.agents[id]
    target = sim.environment.cells[cell]
    occupant = target.agent
    loot =
      if occupant >= 0:
        min(
          sim.agents[occupant].sugar + sim.agents[occupant].spice,
          sim.environment.maxCombatLoot * 2,
        )
      else:
        0.0
    siteWealth = float64(target.sugar + target.spice) + loot
    siteMaxWealth =
      float64(target.maxSugar + target.maxSpice) + loot
    globalMaxWealth = float64(
      sim.config["environmentMaxSugar"].getInt() +
      sim.config["environmentMaxSpice"].getInt()
    )
  var adjacentWealth = 0.0
  for neighborIndex in 0 ..< target.neighborCount:
    let neighbor = sim.environment.cells[target.neighbors[neighborIndex]]
    adjacentWealth += float64(neighbor.sugar + neighbor.spice)

  let neighborhoodSize = actor.movementNeighborhood.len
  var futureNeighborhoodSize = 1
  if actor.decisionModelLookaheadFactor != 0:
    var futureActor = actor
    futureActor.cell = cell
    let futureRange = sim.findCellsInRange(futureActor)
    futureNeighborhoodSize = 1
    for entry in futureRange:
      if sim.environment.cells[entry.cell].agent >= 0:
        inc futureNeighborhoodSize

  for neighborId in actor.movementNeighborhood:
    if not sim.agents[neighborId].alive or
        not sim.agents[neighborId].canReach(cell):
      continue
    # The Python oracle's welfare calculation calls findTimeToLive without a
    # potential cell, which updates the observed neighbor as a side effect.
    let neighborTimeToLive =
      timeToLiveValue(sim.agents[neighborId], false)
    sim.agents[neighborId].timeToLive = neighborTimeToLive.value
    sim.agents[neighborId].timeToLiveIsFloat =
      neighborTimeToLive.isFloat
    let neighbor = sim.agents[neighborId]
    let
      baseMetabolism =
        neighbor.sugarMetabolism + neighbor.spiceMetabolism
      cellDuration =
        if baseMetabolism > 0: siteWealth / baseMetabolism
        else: 0.0
      intensity =
        1.0 / (1.0 + timeToLive(neighbor, false)) /
        (1.0 + target.pollution)
      duration =
        if siteMaxWealth > 0: cellDuration / siteMaxWealth
        else: 0.0
      discount =
        if neighbor.decisionModelLookaheadFactor != 0:
          neighbor.decisionModelLookaheadDiscount
        else:
          0.0
      futureDurationRaw =
        if baseMetabolism > 0:
          (siteWealth - baseMetabolism) / baseMetabolism
        else:
          siteWealth
      futureDuration =
        if siteMaxWealth > 0:
          futureDurationRaw / siteMaxWealth
        else:
          0.0
      cellNeighbors = max(target.neighborCount, 1)
      futureIntensity =
        if globalMaxWealth > 0:
          adjacentWealth /
          (globalMaxWealth * float64(cellNeighbors))
        else:
          0.0
      cellsInRange = neighbor.cellsInRange.len
      extent =
        if cellsInRange > 0:
          float64(neighborhoodSize) / float64(cellsInRange)
        else:
          1.0
      futureExtent =
        if cellsInRange > 0 and
            actor.decisionModelLookaheadFactor != 0:
          float64(futureNeighborhoodSize) / float64(cellsInRange)
        else:
          1.0
    var neighborValue =
      extent * (intensity + duration) +
      discount * futureExtent * (futureIntensity + futureDuration)
    if neighborId != id and actor.selfishnessFactor < 1:
      neighborValue = -neighborValue
      if cell == neighbor.cell and neighborValue > -1:
        neighborValue = -1
    if actor.decisionModelAgeismFactor >= 0:
      var inGroup =
        abs(neighbor.age - actor.age) <=
        sim.config["environmentAgeistRelativeRange"].getInt()
      for bounds in sim.config["environmentAgeistAbsoluteRanges"]:
        if neighbor.age >= bounds[0].getInt() and
            (
              neighbor.age <= bounds[1].getInt() or
              bounds[1].getInt() == -1
            ):
          inGroup = true
          break
      if inGroup:
        neighborValue *= actor.decisionModelAgeismFactor
      else:
        neighborValue *= 1 - actor.decisionModelAgeismFactor
    if actor.decisionModelRacismFactor >= 0:
      var inGroup = neighbor.race == actor.race
      for race in sim.config["environmentInGroupRaces"]:
        if neighbor.race == race.getInt():
          inGroup = true
          break
      if inGroup:
        neighborValue *= actor.decisionModelRacismFactor
      else:
        neighborValue *= 1 - actor.decisionModelRacismFactor
    if actor.decisionModelSexismFactor >= 0 and
        sim.config["environmentSexistGroups"].kind == JArray:
      var actorIsSexist = false
      for group in sim.config["environmentSexistGroups"]:
        if actor.sex == group.getStr():
          actorIsSexist = true
          break
      if actorIsSexist:
        if neighbor.sex == actor.sex:
          neighborValue *= actor.decisionModelSexismFactor
        else:
          neighborValue *= 1 - actor.decisionModelSexismFactor
    if actor.decisionModelTribalFactor >= 0:
      if neighbor.tribe == actor.tribe:
        neighborValue *= actor.decisionModelTribalFactor
      else:
        neighborValue *= 1 - actor.decisionModelTribalFactor
    if actor.selfishnessFactor >= 0:
      if neighborId == id:
        neighborValue *= actor.selfishnessFactor
      else:
        neighborValue *= 1 - actor.selfishnessFactor
    elif neighborValue > 0:
      result.happiness += neighborValue
    else:
      result.unhappiness += neighborValue
    result.value += neighborValue

proc benthamBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
    greedy: int,
): int =
  if candidates.len == 0:
    return greedy
  var scores = newSeq[
    tuple[value, happiness, unhappiness: float64]
  ](candidates.len)
  for index, candidate in candidates:
    scores[index] = sim.ethicalValue(id, candidate.cell)
  if "Top" in sim.agents[id].decisionModel:
    var scalarScores = newSeq[float64](scores.len)
    for index, score in scores:
      scalarScores[index] = score.value
    return candidates[
      sortedEthicalIndices(candidates, scalarScores)[0]
    ].cell
  if sim.agents[id].selfishnessFactor >= 0:
    for index, candidate in candidates:
      if scores[index].value > 0:
        return candidate.cell
    return greedy

  var
    best = candidates[0].cell
    bestScore = scores[0]
  for index in 1 ..< candidates.len:
    let score = scores[index]
    if score.unhappiness > bestScore.unhappiness or
        (
          score.unhappiness == bestScore.unhappiness and
          score.happiness > bestScore.happiness
        ):
      best = candidates[index].cell
      bestScore = score
  best

proc ethicalBestCell(
    sim: var Simulation,
    id: int,
    candidates: seq[MoveCandidate],
    greedy: int,
): int =
  if candidates.len == 0:
    return greedy
  let model = sim.agents[id].decisionModel
  if "asimov" in model:
    return sim.asimovBestCell(id, candidates)
  if "temperance" in model:
    return sim.temperanceBestCell(id, candidates)
  sim.benthamBestCell(id, candidates, greedy)

proc canTrade(first, second: Agent): bool =
  if second.marginalRateOfSubstitution >= 1 and
      first.marginalRateOfSubstitution >= 1:
    return false
  if second.marginalRateOfSubstitution < 1 and
      first.marginalRateOfSubstitution < 1:
    return false
  second.marginalRateOfSubstitution !=
    first.marginalRateOfSubstitution

proc doTrading(sim: var Simulation, id: int) =
  if sim.agents[id].tradeFactor == 0:
    return

  sim.agents[id].tradeVolume = 0
  sim.agents[id].sugarPrice = 0
  sim.agents[id].spicePrice = 0
  sim.agents[id].marginalRateOfSubstitution =
    marginalRate(sim.agents[id])

  var potentialTraders: seq[int]
  let cell = sim.agents[id].cell
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighbor =
      sim.environment.cells[
        sim.environment.cells[cell].neighbors[index]
      ].agent
    if neighbor >= 0 and sim.agents[neighbor].alive and
        sim.agents[neighbor].marginalRateOfSubstitution !=
        sim.agents[id].marginalRateOfSubstitution:
      potentialTraders.add(neighbor)
  sim.rng.shuffle(potentialTraders)

  var tradePartners: seq[int]
  for trader in potentialTraders:
    var
      spiceSeller = -1
      sugarSeller = -1
      tradeFlag = true
      sugarPrice = 0.0
      spicePrice = 0.0
      sugarPriceIsFloat = false
      spicePriceIsFloat = false
    while tradeFlag:
      let traderMRS = sim.agents[trader].marginalRateOfSubstitution
      if not canTrade(sim.agents[id], sim.agents[trader]):
        break

      if traderMRS > sim.agents[id].marginalRateOfSubstitution:
        spiceSeller = trader
        sugarSeller = id
      else:
        spiceSeller = id
        sugarSeller = trader
      let
        spiceSellerMRS =
          sim.agents[spiceSeller].marginalRateOfSubstitution
        sugarSellerMRS =
          sim.agents[sugarSeller].marginalRateOfSubstitution
      if spiceSellerMRS < 0 or sugarSellerMRS < 0:
        spiceSeller = -1
        sugarSeller = -1
        break

      let tradePrice = sqrt(spiceSellerMRS * sugarSellerMRS)
      if tradePrice < 1:
        spicePrice = 1
        sugarPrice = tradePrice
        spicePriceIsFloat = false
        sugarPriceIsFloat = true
      else:
        spicePrice = tradePrice
        sugarPrice = 1
        spicePriceIsFloat = true
        sugarPriceIsFloat = false

      if sim.agents[spiceSeller].spice - spicePrice <
          sim.agents[spiceSeller].spiceMetabolism or
          sim.agents[sugarSeller].sugar - sugarPrice <
          sim.agents[sugarSeller].sugarMetabolism:
        break

      let
        spiceSellerNewMRS = newMarginalRate(
          sim.agents[spiceSeller],
          sim.agents[spiceSeller].sugar + sugarPrice,
          sim.agents[spiceSeller].spice - spicePrice,
        )
        sugarSellerNewMRS = newMarginalRate(
          sim.agents[sugarSeller],
          sim.agents[sugarSeller].sugar - sugarPrice,
          sim.agents[sugarSeller].spice + spicePrice,
        )
        betterForSpiceSeller =
          abs(1 - spiceSellerMRS) >
            abs(1 - spiceSellerNewMRS) or
          welfareRewards(
            sim.agents[spiceSeller],
            sugarPrice,
            -spicePrice,
          ) >= welfareRewards(sim.agents[spiceSeller], 0, 0)
        betterForSugarSeller =
          abs(1 - sugarSellerMRS) >
            abs(1 - sugarSellerNewMRS) or
          welfareRewards(
            sim.agents[sugarSeller],
            -sugarPrice,
            spicePrice,
          ) >= welfareRewards(sim.agents[sugarSeller], 0, 0)
        crossed = spiceSellerNewMRS < sugarSellerNewMRS
      if betterForSpiceSeller and betterForSugarSeller and not crossed:
        sim.agents[spiceSeller].sugar += sugarPrice
        sim.agents[spiceSeller].spice -= spicePrice
        sim.agents[sugarSeller].sugar -= sugarPrice
        sim.agents[sugarSeller].spice += spicePrice
        sim.agents[spiceSeller].sugarIsFloat =
          sim.agents[spiceSeller].sugarIsFloat or sugarPriceIsFloat
        sim.agents[sugarSeller].sugarIsFloat =
          sim.agents[sugarSeller].sugarIsFloat or sugarPriceIsFloat
        sim.agents[spiceSeller].spiceIsFloat =
          sim.agents[spiceSeller].spiceIsFloat or spicePriceIsFloat
        sim.agents[sugarSeller].spiceIsFloat =
          sim.agents[sugarSeller].spiceIsFloat or spicePriceIsFloat
        sim.agents[spiceSeller].wealthIsFloat = true
        sim.agents[sugarSeller].wealthIsFloat = true
        sim.agents[spiceSeller].marginalRateOfSubstitution =
          marginalRate(sim.agents[spiceSeller])
        sim.agents[sugarSeller].marginalRateOfSubstitution =
          marginalRate(sim.agents[sugarSeller])
      else:
        tradeFlag = false

    if spiceSeller >= 0 and sugarSeller >= 0:
      inc sim.agents[id].tradeVolume
      sim.agents[id].sugarPrice += sugarPrice
      sim.agents[id].spicePrice += spicePrice
      sim.agents[id].lastTradeTimestep = sim.timestep
      if trader notin tradePartners:
        tradePartners.add(trader)
      if sim.config["experimentalGroup"].kind != JNull:
        if sim.isExperimental(sim.agents[trader]):
          inc sim.agents[id].tradeWithExperimentalGroup
        else:
          inc sim.agents[id].tradeWithControlGroup
  if sim.agents[id].lastTradeTimestep == sim.timestep:
    sim.agents[id].lastTradePartners = tradePartners.len

proc doTagging(sim: var Simulation, id: int) =
  if not sim.agents[id].tagging or not sim.agents[id].hasTags:
    return
  let cell = sim.agents[id].cell
  var neighborCells: seq[int]
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    neighborCells.add(sim.environment.cells[cell].neighbors[index])
  sim.rng.shuffle(neighborCells)
  for neighborCell in neighborCells:
    let neighbor = sim.environment.cells[neighborCell].agent
    if neighbor >= 0:
      let position = int(
        sim.rng.randBelow(uint64(sim.agents[id].tags.len))
      )
      let
        value = sim.agents[id].tags[position]
        endowmentIndex = sim.agents[neighbor].endowmentIndex
      if endowmentIndex >= 0:
        sim.agentTemplates[endowmentIndex].tags[position] = value
        sim.agentTemplates[endowmentIndex].tribe =
          sim.agentTemplates[endowmentIndex].findTribe(sim.config)
        for agent in sim.agents.mitems:
          if agent.endowmentIndex == endowmentIndex:
            agent.tags[position] = value
            agent.tribe = agent.findTribe(sim.config)
      else:
        sim.agents[neighbor].tags[position] = value
        sim.agents[neighbor].tribe =
          sim.agents[neighbor].findTribe(sim.config)

proc hammingDistance(first, second: Agent): int =
  if not first.hasTags:
    return 0
  for index in 0 ..< first.tags.len:
    if first.tags[index] != second.tags[index]:
      inc result

proc updateFriends(sim: var Simulation, id: int) =
  let cell = sim.agents[id].cell
  sim.agents[id].neighbors.setLen(0)
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighbor =
      sim.environment.cells[
        sim.environment.cells[cell].neighbors[index]
      ].agent
    if neighbor < 0:
      continue
    sim.agents[id].neighbors.add(neighbor)
    let entry = FriendEntry(
      agent: neighbor,
      hammingDistance: hammingDistance(
        sim.agents[id],
        sim.agents[neighbor],
      ),
    )
    if sim.agents[id].friends.len < sim.agents[id].maxFriends:
      sim.agents[id].friends.add(entry)
      continue

    var
      maximumDistance = 0
      maximumIndex = -1
      duplicateIndex = -1
    for friendIndex, friend in sim.agents[id].friends:
      if friend.agent == neighbor:
        duplicateIndex = friendIndex
        break
      if friend.hammingDistance > maximumDistance:
        maximumDistance = friend.hammingDistance
        maximumIndex = friendIndex
    if duplicateIndex >= 0:
      sim.agents[id].friends.delete(duplicateIndex)
      sim.agents[id].friends.add(entry)
    elif maximumDistance > entry.hammingDistance:
      sim.agents[id].friends.delete(maximumIndex)
      sim.agents[id].friends.add(entry)

proc fertile(agent: Agent): bool =
  agent.sugar >= agent.startingSugar and
    agent.spice >= agent.startingSpice and
    agent.age >= agent.fertilityAge and
    agent.age < agent.infertilityAge and
    agent.fertilityFactor + agent.fertilityFactorModifier > 0

proc emptyNeighborCells(sim: Simulation, id: int): seq[int] =
  let cell = sim.agents[id].cell
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighbor = sim.environment.cells[cell].neighbors[index]
    if sim.environment.cells[neighbor].agent < 0:
      result.add(neighbor)

proc chooseParent(
    first, second: int,
    name: string,
    timestep: int,
): int =
  var rng: PyRandom
  rng.seedFromMd5(name, uint64(timestep))
  if rng.randBelow(2) == 0: first else: second

proc childRace(tags: seq[int]): int =
  if tags.len == 0:
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

proc createChild(
    sim: var Simulation,
    first, second, cell: int,
): int =
  let pairedParent =
    chooseParent(first, second, "decisionModel", sim.timestep)
  var child = sim.agents[pairedParent]
  template chooseField(name: string, field: untyped) =
    block:
      let parent = chooseParent(first, second, name, sim.timestep)
      child.field = sim.agents[parent].field
  chooseField("aggressionFactor", aggressionFactor)
  chooseField("baseInterestRate", baseInterestRate)
  chooseField("baseInterestRateIsFloat", baseInterestRateIsFloat)
  chooseField("diseaseProtectionChance", diseaseProtectionChance)
  chooseField("fertilityAge", fertilityAge)
  chooseField("fertilityFactor", fertilityFactor)
  chooseField("infertilityAge", infertilityAge)
  chooseField("inheritancePolicy", inheritancePolicy)
  chooseField("lendingFactor", lendingFactor)
  chooseField("lendingFactorIsFloat", lendingFactorIsFloat)
  chooseField("loanDuration", loanDuration)
  chooseField("lookaheadFactor", lookaheadFactor)
  chooseField("maxAge", maxAge)
  chooseField("maxFriends", maxFriends)
  chooseField("movement", movement)
  chooseField("spiceMetabolism", spiceMetabolism)
  chooseField("sugarMetabolism", sugarMetabolism)
  chooseField("sex", sex)
  chooseField("tradeFactor", tradeFactor)
  chooseField("vision", vision)
  chooseField("universalSpice", universalSpice)
  chooseField("universalSugar", universalSugar)
  child.decisionModel = sim.agents[pairedParent].decisionModel
  child.decisionModelAgeismFactor =
    sim.agents[pairedParent].decisionModelAgeismFactor
  child.decisionModelFactor =
    sim.agents[pairedParent].decisionModelFactor
  child.decisionModelLookaheadDiscount =
    sim.agents[pairedParent].decisionModelLookaheadDiscount
  child.decisionModelLookaheadFactor =
    sim.agents[pairedParent].decisionModelLookaheadFactor
  child.decisionModelRacismFactor =
    sim.agents[pairedParent].decisionModelRacismFactor
  child.decisionModelSexismFactor =
    sim.agents[pairedParent].decisionModelSexismFactor
  child.decisionModelTribalFactor =
    sim.agents[pairedParent].decisionModelTribalFactor
  child.dynamicDecisionModelFactor =
    sim.agents[pairedParent].dynamicDecisionModelFactor
  child.dynamicSelfishnessFactor =
    sim.agents[pairedParent].dynamicSelfishnessFactor
  child.dynamicSocialPressureFactor =
    sim.agents[pairedParent].dynamicSocialPressureFactor
  child.selfishnessFactor =
    sim.agents[pairedParent].selfishnessFactor

  child.startingSugar =
    sim.agents[first].startingSugar /
      (sim.agents[first].fertilityFactor * 2) +
    sim.agents[second].startingSugar /
      (sim.agents[second].fertilityFactor * 2)
  child.startingSpice =
    sim.agents[first].startingSpice /
      (sim.agents[first].fertilityFactor * 2) +
    sim.agents[second].startingSpice /
      (sim.agents[second].fertilityFactor * 2)
  child.startingSugarIsFloat = true
  child.startingSpiceIsFloat = true
  child.sugar = child.startingSugar
  child.spice = child.startingSpice
  child.sugarIsFloat = true
  child.spiceIsFloat = true
  child.wealthIsFloat = true

  var localRng: PyRandom
  localRng.seedFromMd5("tags", uint64(sim.timestep))
  child.tags.setLen(0)
  if sim.agents[first].hasTags:
    for index, tag in sim.agents[first].tags:
      if tag == sim.agents[second].tags[index]:
        child.tags.add(tag)
      else:
        child.tags.add(int(localRng.randBelow(2)))
  child.hasTags = child.tags.len > 0

  localRng.seedFromMd5("racialTags", uint64(sim.timestep))
  child.racialTags.setLen(0)
  if sim.agents[first].hasRacialTags:
    for index, tag in sim.agents[first].racialTags:
      if localRng.randBelow(2) == 0:
        child.racialTags.add(tag)
      else:
        child.racialTags.add(sim.agents[second].racialTags[index])
  child.hasRacialTags = child.racialTags.len > 0
  child.race = childRace(child.racialTags)
  child.depressed =
    localRng.randomFloat() <=
    sim.config["agentDepressionPercentage"].getFloat()

  localRng.seedFromMd5("immuneSystem", uint64(sim.timestep))
  child.immuneSystem.setLen(0)
  if sim.agents[first].hasImmuneSystem:
    for index in 0 ..< sim.agents[first].immuneSystem.len:
      let firstBit = sim.agents[first].startingImmuneSystem[index]
      if firstBit == sim.agents[second].startingImmuneSystem[index]:
        child.immuneSystem.add(firstBit)
      else:
        child.immuneSystem.add(int(localRng.randBelow(2)))
  child.startingImmuneSystem = child.immuneSystem & @[]
  child.hasImmuneSystem = child.immuneSystem.len > 0

  result = sim.nextAgentId
  inc sim.nextAgentId
  child.id = result
  child.endowmentIndex = -1
  child.born = sim.timestep
  child.cell = cell
  child.alive = true
  child.causeOfDeath = ""
  child.diseaseDeath = false
  child.age = 0
  child.lastMovedTimestep = -1
  child.lastActivatedTimestep = sim.timestep
  child.lastSugar = 0
  child.lastSpice = 0
  child.lastPollution = 0
  child.lastPollutionIsFloat = false
  child.lastTimeToLive = 0
  child.timeToLive = 0
  child.lastTimeToLiveIsFloat = false
  child.timeToLiveIsFloat = false
  child.lastMoveRank = 0
  child.lastValidMoves = 0
  child.lastMoveOptimal = true
  child.lastCombatTimestep = -1
  child.lastTradeTimestep = -1
  child.lastSpreadDiseaseTimestep = -1
  child.lastTradePartners = 0
  child.lastDiseasesSpread = 0
  child.lastReproducedTimestep = -1
  child.lastMates = 0
  child.father = if child.sex == "male": first else: second
  child.mother = if child.sex == "female": first else: second
  child.fertilityFactorModifier = 0
  child.aggressionFactorModifier = 0
  child.friendlinessModifier = 0
  child.happinessModifier = 0
  child.movementModifier = 0
  child.visionModifier = 0
  child.sugarMetabolismModifier = 0
  child.spiceMetabolismModifier = 0
  child.sugarMetabolismModifierIsFloat = false
  child.spiceMetabolismModifierIsFloat = false
  child.metabolismModifierIsFloat = false
  child.happinessUnit = 1
  child.diseases = @[]
  child.friends = @[]
  child.children = @[]
  child.mates = @[]
  child.validMoves = @[]
  child.movementNeighborhood = @[]
  child.neighbors = @[]
  child.cellsInRange = @[]
  child.marginalRateOfSubstitution = 1
  child.tradeVolume = 0
  child.sugarPrice = 0
  child.spicePrice = 0
  child.creditorLoans = @[]
  child.debtorLoans = @[]
  child.lastLendedTimestep = -1
  child.lastLoans = 0
  child.sugarMeanIncome = 1
  child.spiceMeanIncome = 1
  child.happiness = 0
  child.conflictHappiness = 0
  child.familyHappiness = 0
  child.healthHappiness = 0
  child.socialHappiness = 0
  child.wealthHappiness = 0
  child.temperanceRules = default(array[5, int])
  child.timeSeenOverconsuming = 0
  child.timesSeenIndulging = 0
  child.timesOverharvested = 0
  child.temperanceSocialPressure = 0
  child.lastDeltaTimeToLive = 0
  child.temperanceTotalMetabolism =
    sugarMetabolism(child) + spiceMetabolism(child)
  child.combatWithControlGroup = 0
  child.combatWithExperimentalGroup = 0
  child.diseaseWithControlGroup = 0
  child.diseaseWithExperimentalGroup = 0
  child.lendingWithControlGroup = 0
  child.lendingWithExperimentalGroup = 0
  child.reproductionWithControlGroup = 0
  child.reproductionWithExperimentalGroup = 0
  child.tradeWithControlGroup = 0
  child.tradeWithExperimentalGroup = 0
  if child.depressed:
    child.aggressionFactor *= 1.145
    child.maxFriends =
      int(ceil(float64(child.maxFriends) * 0.6333))
    child.happinessUnit *= 0.5763
    child.movement *= int(ceil(float64(child.movement) * 0.429))
    child.spiceMetabolism *=
      ceil(child.spiceMetabolism * 1.544)
    child.sugarMetabolism *=
      ceil(child.sugarMetabolism * 1.544)
  child.tribe = child.findTribe(sim.config)

  let
    childSugarIncome = float64(sim.environment.cells[cell].sugar)
    childSpiceIncome = float64(sim.environment.cells[cell].spice)
  child.sugar += childSugarIncome
  child.spice += childSpiceIncome
  child.sugarMeanIncome =
    0.05 * childSugarIncome + 0.95 * child.sugarMeanIncome
  child.spiceMeanIncome =
    0.05 * childSpiceIncome + 0.95 * child.spiceMeanIncome
  if sim.environment.pollutionStart <= sim.timestep and
      sim.timestep <= sim.environment.pollutionEnd:
    sim.environment.cells[cell].pollution +=
      childSugarIncome *
      sim.environment.sugarProductionPollutionFactor
    sim.environment.cells[cell].pollutionIsFloat =
      sim.environment.cells[cell].pollutionIsFloat or
      sim.environment.sugarProductionPollutionFactorIsFloat
    sim.environment.cells[cell].pollution +=
      childSpiceIncome *
      sim.environment.spiceProductionPollutionFactor
    sim.environment.cells[cell].pollutionIsFloat =
      sim.environment.cells[cell].pollutionIsFloat or
      sim.environment.spiceProductionPollutionFactorIsFloat
  sim.environment.cells[cell].sugar = 0
  sim.environment.cells[cell].spice = 0
  sim.environment.cells[cell].agent = result
  child.cellsInRange = sim.findCellsInRange(child)
  sim.agents.add(child)
  sim.activeAgents.add(result)
  sim.agentsBornThisTimestep.add(result)

proc doReproduction(sim: var Simulation, id: int) =
  if not sim.agents[id].fertile():
    return
  let cell = sim.agents[id].cell
  var neighborCells: seq[int]
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    neighborCells.add(sim.environment.cells[cell].neighbors[index])
  sim.rng.shuffle(neighborCells)
  let ownEmpty = sim.emptyNeighborCells(id)
  var timestepMates: seq[int]
  for neighborCell in neighborCells:
    let mate = sim.environment.cells[neighborCell].agent
    if mate < 0 or not sim.agents[mate].alive:
      continue
    let compatible =
      sim.agents[mate].fertile() and
      (
        (
          sim.agents[id].sex == "female" and
          sim.agents[mate].sex == "male"
        ) or
        (
          sim.agents[id].sex == "male" and
          sim.agents[mate].sex == "female"
        )
      )
    var emptyCells = ownEmpty & sim.emptyNeighborCells(mate)
    sim.rng.shuffle(emptyCells)
    if not sim.agents[id].fertile() or not compatible or
        emptyCells.len == 0:
      continue
    var childCell = emptyCells.pop()
    while sim.environment.cells[childCell].agent >= 0 and
        emptyCells.len > 0:
      childCell = emptyCells.pop()
    if sim.environment.cells[childCell].agent >= 0:
      continue
    if mate notin sim.agents[id].mates:
      sim.agents[id].mates.add(mate)
    let child = sim.createChild(id, mate, childCell)
    sim.agents[id].children.add(child)
    if sim.agents[id].sex == "female":
      sim.agents[child].mother = id
      sim.agents[child].father = mate
    else:
      sim.agents[child].father = id
      sim.agents[child].mother = mate
    sim.agents[id].sugar -=
      sim.agents[id].startingSugar /
      (sim.agents[id].fertilityFactor * 2)
    sim.agents[id].spice -=
      sim.agents[id].startingSpice /
      (sim.agents[id].fertilityFactor * 2)
    sim.agents[mate].sugar -=
      sim.agents[mate].startingSugar /
      (sim.agents[mate].fertilityFactor * 2)
    sim.agents[mate].spice -=
      sim.agents[mate].startingSpice /
      (sim.agents[mate].fertilityFactor * 2)
    sim.agents[id].sugarIsFloat = true
    sim.agents[id].spiceIsFloat = true
    sim.agents[mate].sugarIsFloat = true
    sim.agents[mate].spiceIsFloat = true
    sim.agents[id].wealthIsFloat = true
    sim.agents[mate].wealthIsFloat = true
    sim.agents[id].lastReproducedTimestep = sim.timestep
    if mate notin timestepMates:
      timestepMates.add(mate)
    if sim.config["experimentalGroup"].kind != JNull:
      if sim.isExperimental(sim.agents[mate]):
        inc sim.agents[id].reproductionWithExperimentalGroup
      else:
        inc sim.agents[id].reproductionWithControlGroup
  sim.agents[id].lastMates = timestepMates.len

proc removeLoan(values: var seq[int], loanId: int) =
  for index, value in values:
    if value == loanId:
      values.delete(index)
      return

proc pythonDifference(
    first: float64,
    firstIsFloat: bool,
    second: float64,
    secondIsFloat: bool,
): PythonNumber =
  PythonNumber(
    value: first - second,
    isFloat: firstIsFloat or secondIsFloat,
  )

proc pythonMaxZero(value: PythonNumber): PythonNumber =
  # max(0, value) returns its first argument when the values compare equal.
  if value.value > 0:
    value
  else:
    PythonNumber(value: 0, isFloat: false)

proc pythonMin(first, second: PythonNumber): PythonNumber =
  # min(first, second) likewise preserves the first equal operand.
  if first.value <= second.value: first else: second

proc addLoan(
    sim: var Simulation,
    creditor, debtor, origin: int,
    sugarPrincipal, sugarLoan: float64,
    spicePrincipal, spiceLoan: float64,
    duration: int,
    principalIsFloat: array[2, bool],
    loanIsFloat: array[2, bool],
) =
  let loanId = sim.loans.len
  sim.loans.add(
    Loan(
      creditor: creditor,
      debtor: debtor,
      sugarLoan: sugarLoan,
      spiceLoan: spiceLoan,
      sugarLoanIsFloat: loanIsFloat[0],
      spiceLoanIsFloat: loanIsFloat[1],
      duration: duration,
      origin: origin,
      active: true,
    )
  )
  sim.agents[creditor].debtorLoans.add(loanId)
  sim.agents[debtor].creditorLoans.add(loanId)
  sim.agents[creditor].sugar -= sugarPrincipal
  sim.agents[creditor].spice -= spicePrincipal
  sim.agents[debtor].sugar += sugarPrincipal
  sim.agents[debtor].spice += spicePrincipal
  if principalIsFloat[0]:
    sim.agents[creditor].sugarIsFloat = true
    sim.agents[debtor].sugarIsFloat = true
  if principalIsFloat[1]:
    sim.agents[creditor].spiceIsFloat = true
    sim.agents[debtor].spiceIsFloat = true
  sim.agents[creditor].wealthIsFloat = true
  sim.agents[debtor].wealthIsFloat = true

proc payDebt(sim: var Simulation, debtor, loanId: int) =
  if not sim.loans[loanId].active:
    return
  let
    loan = sim.loans[loanId]
    creditor = loan.creditor
  if not sim.agents[creditor].alive:
    if sim.agents[creditor].inheritancePolicy == "children":
      var heirs: seq[int]
      for child in sim.agents[creditor].children:
        if child != debtor and sim.agents[child].alive:
          heirs.add(child)
      if heirs.len > 0:
        let
          sugarShare = loan.sugarLoan / float64(heirs.len)
          spiceShare = loan.spiceLoan / float64(heirs.len)
        for heir in heirs:
          sim.addLoan(
            heir,
            debtor,
            sim.agents[debtor].lastMovedTimestep,
            0,
            sugarShare,
            0,
            spiceShare,
            1,
            [false, false],
            [true, true],
          )
    sim.loans[loanId].active = false
    sim.agents[debtor].creditorLoans.removeLoan(loanId)
    sim.agents[creditor].debtorLoans.removeLoan(loanId)
    return

  if sim.agents[debtor].sugar - loan.sugarLoan > 0 and
      sim.agents[debtor].spice - loan.spiceLoan > 0:
    sim.agents[debtor].sugar -= loan.sugarLoan
    sim.agents[debtor].spice -= loan.spiceLoan
    sim.agents[creditor].sugar += loan.sugarLoan
    sim.agents[creditor].spice += loan.spiceLoan
    if loan.sugarLoanIsFloat:
      sim.agents[debtor].sugarIsFloat = true
      sim.agents[creditor].sugarIsFloat = true
    if loan.spiceLoanIsFloat:
      sim.agents[debtor].spiceIsFloat = true
      sim.agents[creditor].spiceIsFloat = true
    sim.loans[loanId].active = false
    sim.agents[debtor].creditorLoans.removeLoan(loanId)
    sim.agents[creditor].debtorLoans.removeLoan(loanId)
    return

  let
    sugarPayout = sim.agents[debtor].sugar / 2
    spicePayout = sim.agents[debtor].spice / 2
    sugarLeft = loan.sugarLoan - sugarPayout
    spiceLeft = loan.spiceLoan - spicePayout
  sim.agents[debtor].sugar -= sugarPayout
  sim.agents[debtor].spice -= spicePayout
  sim.agents[creditor].sugar += sugarPayout
  sim.agents[creditor].spice += spicePayout
  sim.agents[debtor].sugarIsFloat = true
  sim.agents[debtor].spiceIsFloat = true
  sim.agents[creditor].sugarIsFloat = true
  sim.agents[creditor].spiceIsFloat = true
  sim.loans[loanId].active = false
  sim.agents[debtor].creditorLoans.removeLoan(loanId)
  sim.agents[creditor].debtorLoans.removeLoan(loanId)
  let interest =
    sim.agents[creditor].lendingFactor *
    sim.agents[creditor].baseInterestRate
  sim.addLoan(
    creditor,
    debtor,
    sim.agents[debtor].lastMovedTimestep,
    0,
    sugarLeft + interest * sugarLeft,
    0,
    spiceLeft + interest * spiceLeft,
    sim.agents[creditor].loanDuration,
    [false, false],
    [
      loan.sugarLoanIsFloat or
        sim.agents[creditor].lendingFactorIsFloat or
        sim.agents[creditor].baseInterestRateIsFloat,
      loan.spiceLoanIsFloat or
        sim.agents[creditor].lendingFactorIsFloat or
        sim.agents[creditor].baseInterestRateIsFloat,
    ],
  )

proc updateLoans(sim: var Simulation, id: int) =
  var index = 0
  while index < sim.agents[id].debtorLoans.len:
    let loanId = sim.agents[id].debtorLoans[index]
    if not sim.loans[loanId].active or
        not sim.agents[sim.loans[loanId].debtor].alive:
      sim.agents[id].debtorLoans.delete(index)
    inc index
  index = 0
  while index < sim.agents[id].creditorLoans.len:
    let loanId = sim.agents[id].creditorLoans[index]
    if sim.loans[loanId].active and
        sim.agents[id].lastMovedTimestep - sim.loans[loanId].origin ==
        sim.loans[loanId].duration:
      sim.payDebt(id, loanId)
    inc index

proc currentDebt(
    sim: Simulation,
    id: int,
    sugar: bool,
): float64 =
  for loanId in sim.agents[id].creditorLoans:
    if not sim.loans[loanId].active:
      continue
    if sugar:
      result +=
        sim.loans[loanId].sugarLoan /
        float64(sim.loans[loanId].duration)
    else:
      result +=
        sim.loans[loanId].spiceLoan /
        float64(sim.loans[loanId].duration)

proc creditWorthy(
    sim: Simulation,
    id: int,
    sugarLoan, spiceLoan: float64,
    duration: int,
): bool =
  if duration == 0:
    return false
  let
    sugarIncome =
      sim.agents[id].sugarMeanIncome -
      sugarMetabolism(sim.agents[id]) -
      sim.currentDebt(id, true) -
      sugarLoan / float64(duration)
    spiceIncome =
      sim.agents[id].spiceMeanIncome -
      spiceMetabolism(sim.agents[id]) -
      sim.currentDebt(id, false) -
      spiceLoan / float64(duration)
  sugarIncome >= 0 and spiceIncome >= 0

proc doLending(sim: var Simulation, id: int) =
  sim.updateLoans(id)
  if sim.agents[id].lendingFactor == 0:
    return
  if sim.agents[id].fertile() and
      (
        sim.agents[id].sugar <= sim.agents[id].startingSugar or
        sim.agents[id].spice <= sim.agents[id].startingSpice
      ):
    return
  if sim.agents[id].age < sim.agents[id].fertilityAge:
    return

  let interestRate = min(
    1.0,
    sim.agents[id].lendingFactor *
    sim.agents[id].baseInterestRate,
  )
  let interestRateIsFloat =
    interestRate < 1 and
    (
      sim.agents[id].lendingFactorIsFloat or
      sim.agents[id].baseInterestRateIsFloat
    )
  var borrowers: seq[int]
  let cell = sim.agents[id].cell
  for index in 0 ..< sim.environment.cells[cell].neighborCount:
    let neighborCell = sim.environment.cells[cell].neighbors[index]
    let borrower = sim.environment.cells[neighborCell].agent
    if borrower >= 0 and sim.agents[borrower].alive and
        sim.agents[borrower].age >= sim.agents[borrower].fertilityAge and
        sim.agents[borrower].age < sim.agents[borrower].infertilityAge and
        not sim.agents[borrower].fertile():
      borrowers.add(borrower)
  sim.rng.shuffle(borrowers)

  var loans = 0
  for borrower in borrowers:
    var
      maxSugarLoan = PythonNumber(
        value: sim.agents[id].sugar / 2,
        isFloat: true,
      )
      maxSpiceLoan = PythonNumber(
        value: sim.agents[id].spice / 2,
        isFloat: true,
      )
    if sim.agents[id].fertile():
      maxSugarLoan = pythonMaxZero(pythonDifference(
        sim.agents[id].sugar,
        sim.agents[id].sugarIsFloat,
        sim.agents[id].startingSugar,
        sim.agents[id].startingSugarIsFloat,
      ))
      maxSpiceLoan = pythonMaxZero(pythonDifference(
        sim.agents[id].spice,
        sim.agents[id].spiceIsFloat,
        sim.agents[id].startingSpice,
        sim.agents[id].startingSpiceIsFloat,
      ))
    if maxSugarLoan.value == 0 and maxSpiceLoan.value == 0:
      return
    let
      sugarNeed = pythonMaxZero(pythonDifference(
        sim.agents[borrower].startingSugar,
        sim.agents[borrower].startingSugarIsFloat,
        sim.agents[borrower].sugar,
        sim.agents[borrower].sugarIsFloat,
      ))
      spiceNeed = pythonMaxZero(pythonDifference(
        sim.agents[borrower].startingSpice,
        sim.agents[borrower].startingSpiceIsFloat,
        sim.agents[borrower].spice,
        sim.agents[borrower].spiceIsFloat,
      ))
      sugarPrincipal = pythonMin(maxSugarLoan, sugarNeed)
      spicePrincipal = pythonMin(maxSpiceLoan, spiceNeed)
      sugarAmount = PythonNumber(
        value:
          sugarPrincipal.value +
          sugarPrincipal.value * interestRate,
        isFloat: sugarPrincipal.isFloat or interestRateIsFloat,
      )
      spiceAmount = PythonNumber(
        value:
          spicePrincipal.value +
          spicePrincipal.value * interestRate,
        isFloat: spicePrincipal.isFloat or interestRateIsFloat,
      )
    if (sugarNeed.value == 0 and spiceNeed.value == 0) or
        (sugarAmount.value == 0 and spiceAmount.value == 0):
      continue
    if sim.agents[id].sugar - sugarPrincipal.value <=
        sugarMetabolism(sim.agents[id]) or
        sim.agents[id].spice - spicePrincipal.value <=
        spiceMetabolism(sim.agents[id]):
      continue
    if not sim.creditWorthy(
      borrower,
      sugarAmount.value,
      spiceAmount.value,
      sim.agents[id].loanDuration,
    ):
      continue
    sim.addLoan(
      id,
      borrower,
      sim.agents[id].lastMovedTimestep,
      sugarPrincipal.value,
      sugarAmount.value,
      spicePrincipal.value,
      spiceAmount.value,
      sim.agents[id].loanDuration,
      [sugarPrincipal.isFloat, spicePrincipal.isFloat],
      [sugarAmount.isFloat, spiceAmount.isFloat],
    )
    inc loans
    if sim.config["experimentalGroup"].kind != JNull:
      if sim.isExperimental(sim.agents[borrower]):
        inc sim.agents[id].lendingWithExperimentalGroup
      else:
        inc sim.agents[id].lendingWithControlGroup
  if loans > 0:
    sim.agents[id].lastLendedTimestep = sim.timestep
    sim.agents[id].lastLoans = loans

proc roundedNode(value: float64, places: int, asFloat: bool): JsonNode =
  let rounded = roundHalfEven(value, places)
  if asFloat:
    newJFloat(rounded)
  else:
    newJInt(int64(rounded))

proc integerNode(value: float64): JsonNode =
  if value >= float64(high(int64)):
    pythonIntegerNode($high(int64))
  else:
    newJInt(int64(value))

proc maxIntegerDifference(previous: float64): JsonNode =
  let previousInteger = int64(previous)
  if previousInteger >= 0:
    newJInt(high(int64) - previousInteger)
  else:
    pythonIntegerNode($(
      uint64(high(int64)) + uint64(-(previousInteger + 1)) + 1'u64
    ))

proc appendAgentRuntimeStats(sim: var Simulation, id: int) =
  let agent = sim.agents[id]
  var
    neighborsInTribe = 0
    sameRaceNeighbors = 0
    experimentalNeighbors = 0
    controlNeighbors = 0
  for neighborId in agent.neighbors:
    let neighbor = sim.agents[neighborId]
    if neighbor.tribe == agent.tribe:
      inc neighborsInTribe
    if neighbor.race == agent.race:
      inc sameRaceNeighbors
    if sim.config["experimentalGroup"].kind != JNull:
      if sim.isExperimental(neighbor):
        inc experimentalNeighbors
      else:
        inc controlNeighbors

  let
    spiceGained = agent.spice - agent.lastSpice
    sugarGained = agent.sugar - agent.lastSugar
    wealthGained = spiceGained + sugarGained
    previousTimeToLive = agent.timeToLive
    currentTimeToLiveValue = timeToLiveValue(agent, false)
    currentTimeToLive = currentTimeToLiveValue.value
    pollutionDifference =
      sim.environment.cells[agent.cell].pollution - agent.lastPollution
    sugarIsFloat = agent.sugarIsFloat
    spiceIsFloat = agent.spiceIsFloat
    sugarGainedIsFloat =
      agent.sugarIsFloat or agent.lastSugarIsFloat
    spiceGainedIsFloat =
      agent.spiceIsFloat or agent.lastSpiceIsFloat
    wealthIsFloat = sugarIsFloat or spiceIsFloat
    wealthGainedIsFloat =
      sugarGainedIsFloat or spiceGainedIsFloat
    timeIsFloat = currentTimeToLiveValue.isFloat
    differenceIsFloat = timeIsFloat or agent.timeToLiveIsFloat
    pollutionIsFloat =
      sim.environment.cells[agent.cell].pollutionIsFloat or
      agent.lastPollutionIsFloat

  sim.agents[id].lastTimeToLive = previousTimeToLive
  sim.agents[id].lastTimeToLiveIsFloat = agent.timeToLiveIsFloat
  sim.agents[id].timeToLive = currentTimeToLive
  sim.agents[id].timeToLiveIsFloat = timeIsFloat
  sim.agentRuntimeStats.add(%*{
    "timestep": sim.timestep,
    "ID": agent.id,
    "age": agent.age,
    "wealth": roundedNode(agent.sugar + agent.spice, 2, wealthIsFloat),
    "sugar": roundedNode(agent.sugar, 2, sugarIsFloat),
    "spice": roundedNode(agent.spice, 2, spiceIsFloat),
    "sugarGained": roundedNode(sugarGained, 2, sugarGainedIsFloat),
    "spiceGained": roundedNode(spiceGained, 2, spiceGainedIsFloat),
    "wealthGained": roundedNode(
      wealthGained,
      2,
      wealthGainedIsFloat,
    ),
    "movement": movement(agent),
    "timeToLive":
      if timeIsFloat:
        roundedNode(currentTimeToLive, 1, true)
      else:
        integerNode(currentTimeToLive),
    "depression": agent.depressed,
    "compositeHappiness": newJFloat(roundHalfEven(agent.happiness, 1)),
    "preyKilled": agent.lastCombatTimestep == sim.timestep,
    "preyWealth":
      if agent.lastCombatTimestep == sim.timestep:
        if agent.lastPreyWealth != floor(agent.lastPreyWealth):
          newJFloat(agent.lastPreyWealth)
        else:
          newJInt(int64(agent.lastPreyWealth))
      else:
        newJInt(0),
    "tradePartners":
      if agent.lastTradeTimestep == sim.timestep:
        agent.lastTradePartners
      else:
        0,
    "diseasesSpread":
      if agent.lastSpreadDiseaseTimestep == sim.timestep:
        agent.lastDiseasesSpread
      else:
        0,
    "mates":
      if agent.lastReproducedTimestep == sim.timestep:
        agent.lastMates
      else:
        0,
    "neighbors": agent.neighbors.len,
    "validMoves": agent.lastValidMoves,
    "moveRank": agent.lastMoveRank,
    "lendingPartners":
      if agent.lastLendedTimestep == sim.timestep:
        agent.lastLoans
      else:
        0,
    "pollutionDifference":
      if pollutionIsFloat:
        newJFloat(pollutionDifference)
      else:
        newJInt(int64(pollutionDifference)),
    "timeToLiveDifference":
      if differenceIsFloat:
        newJFloat(currentTimeToLive - previousTimeToLive)
      elif currentTimeToLive >= float64(high(int64)):
        maxIntegerDifference(previousTimeToLive)
      else:
        newJInt(int64(currentTimeToLive) - int64(previousTimeToLive)),
    "neighborsInTribe": neighborsInTribe,
    "neighborsNotInTribe": agent.neighbors.len - neighborsInTribe,
    "sameRaceNeighbors": sameRaceNeighbors,
    "differentRaceNeighbors": agent.neighbors.len - sameRaceNeighbors,
    "experimentalGroupNeighbors": experimentalNeighbors,
    "controlGroupNeighbors": controlNeighbors,
  })

proc activate(
    sim: var Simulation,
    id: int,
    populationPolicy: PopulationPolicy,
    forcedDestination = -1,
) =
  sim.agents[id].lastActivatedTimestep = sim.timestep
  if not sim.agents[id].alive or
      sim.agents[id].lastMovedTimestep == sim.timestep:
    return

  sim.agents[id].lastSugar = sim.agents[id].sugar
  sim.agents[id].lastSpice = sim.agents[id].spice
  sim.agents[id].lastSugarIsFloat = sim.agents[id].sugarIsFloat
  sim.agents[id].lastSpiceIsFloat = sim.agents[id].spiceIsFloat

  let destination =
    if forcedDestination >= 0:
      forcedDestination
    else:
      sim.bestCell(id, populationPolicy)
  let prey = sim.environment.cells[destination].agent
  if prey >= 0 and prey != id:
    let
      sugarLoot = min(
        sim.environment.maxCombatLoot,
        sim.agents[prey].sugar,
      )
      spiceLoot = min(
        sim.environment.maxCombatLoot,
        sim.agents[prey].spice,
      )
      sugarLootIsFloat =
        (
          sim.config["environmentMaxCombatLoot"].kind == JFloat and
          sim.environment.maxCombatLoot <= sim.agents[prey].sugar
        ) or
        (
          sim.agents[prey].sugarIsFloat and
          sim.agents[prey].sugar < sim.environment.maxCombatLoot
        )
      spiceLootIsFloat =
        (
          sim.config["environmentMaxCombatLoot"].kind == JFloat and
          sim.environment.maxCombatLoot <= sim.agents[prey].spice
        ) or
        (
          sim.agents[prey].spiceIsFloat and
          sim.agents[prey].spice < sim.environment.maxCombatLoot
        )
      lootIsFloat =
        sugarLootIsFloat or spiceLootIsFloat
    sim.agents[id].sugar += sugarLoot
    sim.agents[id].spice += spiceLoot
    sim.agents[id].sugarIsFloat =
      sim.agents[id].sugarIsFloat or sugarLootIsFloat
    sim.agents[id].spiceIsFloat =
      sim.agents[id].spiceIsFloat or spiceLootIsFloat
    sim.agents[id].wealthIsFloat =
      sim.agents[id].wealthIsFloat or lootIsFloat
    sim.agents[id].lastCombatTimestep = sim.timestep
    sim.agents[id].lastPreyWealth = sugarLoot + spiceLoot
    sim.agents[prey].sugar -= sugarLoot
    sim.agents[prey].spice -= spiceLoot
    sim.agents[prey].sugarIsFloat =
      sim.agents[prey].sugarIsFloat or sugarLootIsFloat
    sim.agents[prey].spiceIsFloat =
      sim.agents[prey].spiceIsFloat or spiceLootIsFloat
    sim.agents[prey].wealthIsFloat =
      sim.agents[prey].wealthIsFloat or lootIsFloat
    if sim.config["experimentalGroup"].kind != JNull:
      if sim.isExperimental(sim.agents[prey]):
        inc sim.agents[id].combatWithExperimentalGroup
      else:
        inc sim.agents[id].combatWithControlGroup
    sim.killAgent(prey, "combat")
  sim.agents[id].lastPollution =
    sim.environment.cells[sim.agents[id].cell].pollution
  sim.agents[id].lastPollutionIsFloat =
    sim.environment.cells[sim.agents[id].cell].pollutionIsFloat
  sim.environment.cells[sim.agents[id].cell].agent = -1
  sim.agents[id].cell = destination
  sim.agents[id].lastMovedTimestep = sim.timestep
  sim.environment.cells[destination].agent = id
  sim.updateFriends(id)
  if "temperance" in sim.agents[id].decisionModel:
    sim.agents[id].lastDeltaTimeToLive =
      sim.timeToLiveAt(sim.agents[id], destination) -
      sim.agents[id].timeToLive

  let
    sugarIncome = float64(sim.environment.cells[destination].sugar)
    spiceIncome = float64(sim.environment.cells[destination].spice)
  sim.agents[id].sugar += sugarIncome
  sim.agents[id].spice += spiceIncome
  sim.agents[id].sugarMeanIncome =
    0.05 * sugarIncome + 0.95 * sim.agents[id].sugarMeanIncome
  sim.agents[id].spiceMeanIncome =
    0.05 * spiceIncome + 0.95 * sim.agents[id].spiceMeanIncome
  if sim.environment.pollutionStart <= sim.timestep and
      sim.timestep <= sim.environment.pollutionEnd:
    sim.environment.cells[destination].pollution +=
      float64(sim.environment.cells[destination].sugar) *
      sim.environment.sugarProductionPollutionFactor
    sim.environment.cells[destination].pollutionIsFloat =
      sim.environment.cells[destination].pollutionIsFloat or
      sim.environment.sugarProductionPollutionFactorIsFloat
    sim.environment.cells[destination].pollution +=
      float64(sim.environment.cells[destination].spice) *
      sim.environment.spiceProductionPollutionFactor
    sim.environment.cells[destination].pollutionIsFloat =
      sim.environment.cells[destination].pollutionIsFloat or
      sim.environment.spiceProductionPollutionFactorIsFloat
  sim.environment.cells[destination].sugar = 0
  sim.environment.cells[destination].spice = 0

  if sim.timestep -
      sim.agents[id].lastUniversalSpiceIncomeTimestep >=
      sim.environment.universalSpiceIncomeInterval:
    sim.agents[id].spice += sim.agents[id].universalSpice
    sim.agents[id].spiceIsFloat =
      sim.agents[id].spiceIsFloat or
      sim.agents[id].universalSpiceIsFloat
    sim.agents[id].lastUniversalSpiceIncomeTimestep = sim.timestep
  if sim.timestep -
      sim.agents[id].lastUniversalSugarIncomeTimestep >=
      sim.environment.universalSugarIncomeInterval:
    sim.agents[id].sugar += sim.agents[id].universalSugar
    sim.agents[id].sugarIsFloat =
      sim.agents[id].sugarIsFloat or
      sim.agents[id].universalSugarIsFloat
    sim.agents[id].lastUniversalSugarIncomeTimestep = sim.timestep

  let
    sugarMet = sugarMetabolism(sim.agents[id])
    spiceMet = spiceMetabolism(sim.agents[id])
  if "temperance" in sim.agents[id].decisionModel:
    # findNeighborhood(cell) always includes the acting agent itself.
    sim.agents[id].temperanceSocialPressure +=
      sim.agents[id].dynamicSocialPressureFactor
  sim.agents[id].wealthIsFloat =
    sim.agents[id].wealthIsFloat or
    sim.agents[id].metabolismModifierIsFloat
  sim.agents[id].sugarIsFloat =
    sim.agents[id].sugarIsFloat or
    sim.agents[id].sugarMetabolismIsFloat or
    sim.agents[id].sugarMetabolismModifierIsFloat
  sim.agents[id].spiceIsFloat =
    sim.agents[id].spiceIsFloat or
    sim.agents[id].spiceMetabolismIsFloat or
    sim.agents[id].spiceMetabolismModifierIsFloat
  sim.agents[id].sugar -= sugarMet
  sim.agents[id].spice -= spiceMet
  if sim.environment.pollutionStart <= sim.timestep and
      sim.timestep <= sim.environment.pollutionEnd:
    sim.environment.cells[destination].pollution +=
      sugarMet *
      sim.environment.sugarConsumptionPollutionFactor
    sim.environment.cells[destination].pollutionIsFloat =
      sim.environment.cells[destination].pollutionIsFloat or
      sim.agents[id].sugarMetabolismIsFloat or
      sim.agents[id].sugarMetabolismModifierIsFloat or
      sim.environment.sugarConsumptionPollutionFactorIsFloat
    sim.environment.cells[destination].pollution +=
      spiceMet *
      sim.environment.spiceConsumptionPollutionFactor
    sim.environment.cells[destination].pollutionIsFloat =
      sim.environment.cells[destination].pollutionIsFloat or
      sim.agents[id].spiceMetabolismIsFloat or
      sim.agents[id].spiceMetabolismModifierIsFloat or
      sim.environment.spiceConsumptionPollutionFactorIsFloat
  if sim.agents[id].sugar < 0 or sim.agents[id].spice < 0 or
      (
        sim.agents[id].sugar <= 0 and
        sugarMet > 0
      ) or
      (
        sim.agents[id].spice <= 0 and
        spiceMet > 0
      ):
    sim.killAgent(id, "starvation")
    return

  sim.doTagging(id)
  sim.doTrading(id)
  sim.doReproduction(id)
  sim.doLending(id)
  sim.doDisease(id)

  inc sim.agents[id].age
  if sim.agents[id].maxAge != -1 and
      sim.agents[id].age >= sim.agents[id].maxAge:
    sim.killAgent(id, "aging")
    return

  sim.agents[id].cellsInRange = sim.findCellsInRange(sim.agents[id])
  sim.agents[id].conflictHappiness =
    if sim.agents[id].lastCombatTimestep == sim.timestep:
      if sim.agents[id].aggressionFactor +
          sim.agents[id].aggressionFactorModifier > 1:
        sim.agents[id].happinessUnit
      else:
        -sim.agents[id].happinessUnit
    else:
      0.0
  var familyHappiness = 0.0
  for child in sim.agents[id].children:
    if sim.agents[child].alive:
      familyHappiness += sim.agents[id].happinessUnit
      if sim.agents[child].diseases.len > 0:
        familyHappiness -= sim.agents[id].happinessUnit * 0.5
      if sim.agents[child].born == sim.timestep:
        familyHappiness += sim.agents[id].happinessUnit
    else:
      familyHappiness -= sim.agents[id].happinessUnit
  for mate in sim.agents[id].mates:
    if sim.agents[mate].alive:
      familyHappiness += sim.agents[id].happinessUnit
      if sim.agents[mate].diseases.len > 0:
        familyHappiness -= sim.agents[id].happinessUnit * 0.5
    else:
      familyHappiness -= sim.agents[id].happinessUnit
  sim.agents[id].familyHappiness = erf(familyHappiness)
  sim.agents[id].healthHappiness =
    if sim.agents[id].diseases.len > 0:
      -sim.agents[id].happinessUnit
    else:
      sim.agents[id].happinessUnit
  sim.agents[id].socialHappiness =
    if sim.agents[id].maxFriends == 0:
      0.0
    else:
      var step {.volatile.} = pythonDivide(
        2.0,
        float64(sim.agents[id].maxFriends),
      )
      var scaled {.volatile.} =
        float64(sim.agents[id].friends.len) * step
      (scaled - 1.0) * sim.agents[id].happinessUnit
  sim.agents[id].wealthHappiness =
    erf(
      (
        sim.agents[id].sugar + sim.agents[id].spice -
        sim.meanWealth
      ) * sim.agents[id].happinessUnit
    )
  sim.agents[id].happiness =
    sim.agents[id].conflictHappiness +
    sim.agents[id].familyHappiness +
    sim.agents[id].healthHappiness +
    sim.agents[id].socialHappiness +
    sim.agents[id].wealthHappiness
  sim.appendAgentRuntimeStats(id)
  if sim.agents[id].dynamicSelfishnessFactor != 0:
    if sim.agents[id].timeToLive <
        sim.agents[id].lastTimeToLive and
        sim.agents[id].selfishnessFactor < 1:
      sim.agents[id].selfishnessFactor +=
        sim.agents[id].dynamicSelfishnessFactor
    elif sim.agents[id].timeToLive >
        sim.agents[id].lastTimeToLive and
        sim.agents[id].selfishnessFactor > 0:
      sim.agents[id].selfishnessFactor -=
        sim.agents[id].dynamicSelfishnessFactor
    sim.agents[id].selfishnessFactor =
      roundHalfEven(sim.agents[id].selfishnessFactor, 2)
    sim.agents[id].lastTimeToLive = sim.agents[id].timeToLive
  if "temperance" in sim.agents[id].decisionModel:
    if sim.agents[id].lastDeltaTimeToLive <= 1:
      inc sim.agents[id].temperanceRules[0]
    elif sim.agents[id].lastDeltaTimeToLive <= 2:
      inc sim.agents[id].temperanceRules[1]
      inc sim.agents[id].timeSeenOverconsuming
      inc sim.agents[id].temperanceRules[2]
    else:
      inc sim.agents[id].temperanceRules[3]
      inc sim.agents[id].timesSeenIndulging
      inc sim.agents[id].temperanceRules[4]

proc cloneAgent(agent: Agent): Agent =
  result = agent
  result.tags = agent.tags & @[]
  result.racialTags = agent.racialTags & @[]
  result.immuneSystem = agent.immuneSystem & @[]
  result.startingImmuneSystem = agent.startingImmuneSystem & @[]
  result.diseases = agent.diseases & @[]
  result.cellsInRange = agent.cellsInRange & @[]
  result.movementNeighborhood = agent.movementNeighborhood & @[]
  result.neighbors = agent.neighbors & @[]
  result.validMoves = agent.validMoves & @[]
  result.friends = agent.friends & @[]
  result.children = agent.children & @[]
  result.mates = agent.mates & @[]
  result.creditorLoans = agent.creditorLoans & @[]
  result.debtorLoans = agent.debtorLoans & @[]

proc cloneSimulation(sim: Simulation): Simulation =
  result = sim
  result.environment.cells = sim.environment.cells & @[]
  result.agents = newSeq[Agent](sim.agents.len)
  for index, agent in sim.agents:
    result.agents[index] = cloneAgent(agent)
  result.agentTemplates = newSeq[Agent](sim.agentTemplates.len)
  for index, agent in sim.agentTemplates:
    result.agentTemplates[index] = cloneAgent(agent)
  result.diseases = sim.diseases & @[]
  result.diseaseRegistry = sim.diseaseRegistry & @[]
  result.remainingDiseases = sim.remainingDiseases & @[]
  result.activeAgents = sim.activeAgents & @[]
  result.deathsThisTimestep = sim.deathsThisTimestep & @[]
  result.agentsBornThisTimestep = sim.agentsBornThisTimestep & @[]
  result.agentRuntimeStats = sim.agentRuntimeStats & @[]
  result.loans = sim.loans & @[]
  result.runtimeStats = sim.runtimeStats.copy()

proc appendLeaderRuntimeStats(sim: var Simulation) =
  let
    leader = sim.agents[0]
    socialHappiness =
      if leader.maxFriends == 0: 0.0
      else: -leader.happinessUnit
    compositeHappiness =
      leader.happinessUnit + socialHappiness + 1.0
    previousTimeToLive = leader.timeToLive
  sim.agents[0].lastTimeToLive = previousTimeToLive
  sim.agents[0].timeToLive = float64(high(int64))
  sim.agents[0].happiness = compositeHappiness
  sim.agentRuntimeStats.add(%*{
    "timestep": sim.timestep,
    "ID": 0,
    "age": 0,
    "wealth": pythonIntegerNode("18446744073709551614"),
    "sugar": newJInt(high(int64)),
    "spice": newJInt(high(int64)),
    "sugarGained": 0,
    "spiceGained": 0,
    "wealthGained": 0,
    "movement": 0,
    "timeToLive": newJInt(high(int64)),
    "depression": leader.depressed,
    "compositeHappiness":
      newJFloat(roundHalfEven(compositeHappiness, 1)),
    "preyKilled": false,
    "preyWealth": 0,
    "tradePartners": 0,
    "diseasesSpread": 0,
    "mates": 0,
    "neighbors": 0,
    "validMoves": 0,
    "moveRank": 0,
    "lendingPartners": 0,
    "pollutionDifference": 0,
    "timeToLiveDifference":
      if previousTimeToLive == 0:
        newJInt(high(int64))
      else:
        newJInt(0),
    "neighborsInTribe": 0,
    "neighborsNotInTribe": 0,
    "sameRaceNeighbors": 0,
    "differentRaceNeighbors": 0,
    "experimentalGroupNeighbors": 0,
    "controlGroupNeighbors": 0,
  })

proc leaderPlacements(sim: Simulation): seq[int] =
  ## DTL's Leader exhaustively simulates the Cartesian product of every
  ## follower's movement range, restoring the same RNG state for each future.
  ## This is intentionally exponential: changing the search would change the
  ## model's behavior.
  result = newSeq[int](sim.agents.len)
  for cell in result.mitems:
    cell = -1
  if sim.activeAgents.len == 0:
    return

  var
    choices = newSeq[seq[int]](sim.activeAgents.len)
    counters = newSeq[int](sim.activeAgents.len)
  for index, id in sim.activeAgents:
    for entry in sim.agents[id].cellsInRange:
      choices[index].add(entry.cell)
    if choices[index].len == 0:
      choices[index].add(sim.agents[id].cell)

  var
    bestScore = -Inf
    exhausted = false
  while not exhausted:
    var future = cloneSimulation(sim)
    var placement = newSeq[int](sim.agents.len)
    for cell in placement.mitems:
      cell = -1
    for index, id in sim.activeAgents:
      if not future.agents[id].alive:
        continue
      future.activate(id, nil, choices[index][counters[index]])
      if future.agents[id].alive and future.agents[id].cell >= 0:
        placement[id] = future.agents[id].cell
    future.updateRuntimeStats()
    let score =
      if future.runtimeStats["meanHappiness"].kind == JFloat:
        future.runtimeStats["meanHappiness"].getFloat()
      else:
        float64(future.runtimeStats["meanHappiness"].getInt())
    if score > bestScore:
      bestScore = score
      result = placement

    var carry = true
    for index in countdown(counters.high, 0):
      if not carry:
        break
      inc counters[index]
      if counters[index] >= choices[index].len:
        counters[index] = 0
      else:
        carry = false
    exhausted = carry

proc initSimulation*(config: JsonNode): Simulation =
  result.config = config
  result.timestep = 0
  result.maxTimestep = config["timesteps"].getInt()
  var seed = config["seed"].getBiggestInt()
  if seed < 0:
    var bytes: array[8, byte]
    if not urandom(bytes):
      raise newException(IOError, "could not obtain a nondeterministic seed")
    var generated = 0'u64
    for value in bytes:
      generated = (generated shl 8) or uint64(value)
    seed = BiggestInt(generated mod uint64(high(int64)))
    result.config["seed"] = newJInt(seed)
  result.rng = initPyRandom(uint64(seed))
  result.config.normalizeSpecialCases(result.rng)
  result.maxTimestep = result.config["timesteps"].getInt()
  result.runtimeStats = initialRuntimeStats(config)
  result.environment = initEnvironment(config)
  result.agents =
    createInitialAgents(config, result.environment, result.rng)
  result.agentTemplates = result.agents
  result.nextAgentId = result.agents.len
  result.agentEndowmentIndex = result.agents.len
  for id in 0 ..< result.agents.len:
    if not result.agents[id].alive:
      continue
    result.activeAgents.add(id)
    result.agents[id].cellsInRange =
      result.findCellsInRange(result.agents[id])

  result.configureDiseases()
  result.updateRuntimeStats()

proc doTimestep*(
    sim: var Simulation,
    populationPolicy: PopulationPolicy = nil,
) =
  if sim.timestep >= sim.maxTimestep:
    return
  inc sim.timestep
  if sim.activeAgents.len == 0 and
      not sim.config["keepAlivePostExtinction"].getBool():
    return

  sim.environment.doTimestep(sim.timestep)
  sim.rng.shuffle(sim.activeAgents)
  sim.addRemainingDiseases()
  let activationOrder = sim.activeAgents
  if sim.config["agentLeader"].getBool():
    let placements = sim.leaderPlacements()
    sim.appendLeaderRuntimeStats()
    for id in activationOrder:
      let destination =
        if id < placements.len and placements[id] >= 0:
          placements[id]
        else:
          sim.agents[id].cell
      sim.activate(id, nil, destination)
  else:
    for id in activationOrder:
      sim.activate(id, populationPolicy)

  var
    living = newSeqOfCap[int](sim.activeAgents.len)
    dead = newSeqOfCap[int](sim.deathsThisTimestep.len)
  for id in sim.activeAgents:
    if sim.agents[id].alive:
      living.add(id)
    else:
      dead.add(id)
  sim.activeAgents = living
  sim.deathsThisTimestep = dead
  sim.replaceAgents()
  sim.updateRuntimeStats()

proc finalEnvironmentStats(sim: var Simulation) =
  var
    environmentWealthCreated: int64
    environmentWealthTotal: int64
  for cell in sim.environment.cells:
    environmentWealthCreated +=
      cell.sugarLastProduced + cell.spiceLastProduced
    environmentWealthTotal += cell.sugar + cell.spice
  sim.runtimeStats["environmentWealthCreated"] =
    newJInt(environmentWealthCreated)
  sim.runtimeStats["environmentWealthTotal"] =
    newJInt(environmentWealthTotal)

proc csvHeader(stats: JsonNode): string =
  var keys: seq[string]
  for key in stats.keys:
    keys.add(key)
  keys.sort()
  keys.join(",") & "\n"

proc csvRow(stats: JsonNode): string =
  var keys: seq[string]
  for key in stats.keys:
    keys.add(key)
  keys.sort()
  for index, key in keys:
    if index > 0:
      result.add(",")
    result.add(pythonString(stats[key]))
  result.add("\n")

proc agentCsvHeader(stats: JsonNode): string =
  var first = true
  for key in stats.keys:
    if not first:
      result.add(",")
    result.add(key)
    first = false
  result.add("\n")

proc agentCsvRows(stats: openArray[JsonNode]): string =
  var firstRecord = true
  for record in stats:
    var first = true
    for key, value in record:
      if not first or not firstRecord:
        result.add(",")
      result.add(pythonString(value))
      first = false
    result.add("\n")
    firstRecord = false

proc agentJsonRows(stats: openArray[JsonNode], final: bool): string =
  for index, record in stats:
    result.add("\t")
    result.add(pythonJson(record))
    if final and index == stats.high:
      result.add("\n]")
    else:
      result.add(",\n")

proc runSimulation*(sim: var Simulation, logPath: string) =
  let csv = sim.config["logfileFormat"].getStr() == "csv"
  let agentLogPath =
    if sim.config["agentLogfile"].kind == JString:
      sim.config["agentLogfile"].getStr()
    else:
      ""
  var
    log: File
    agentLog: File
  if logPath.len > 0:
    if not open(log, logPath, fmAppend):
      raise newException(IOError, "could not open logfile: " & logPath)
    if csv:
      let initialStats = initialRuntimeStats(sim.config)
      log.write(csvHeader(initialStats))
      log.write(csvRow(initialStats))
    else:
      log.write("[\n")
      log.write("\t" & pythonJson(initialRuntimeStats(sim.config)) & ",\n")
  if agentLogPath.len > 0 and not open(agentLog, agentLogPath, fmAppend):
    raise newException(IOError, "could not open agent logfile: " & agentLogPath)

  while sim.timestep < sim.maxTimestep:
    if sim.activeAgents.len == 0 and
        not sim.config["keepAlivePostExtinction"].getBool():
      break
    sim.doTimestep()
    if logPath.len > 0 and sim.timestep != sim.maxTimestep and
        sim.activeAgents.len > 0:
      if csv:
        log.write(csvRow(sim.runtimeStats))
      else:
        log.write("\t" & pythonJson(sim.runtimeStats) & ",\n")
    if sim.timestep != sim.maxTimestep and sim.activeAgents.len > 0:
      if agentLogPath.len > 0:
        if sim.timestep == 1:
          if csv:
            agentLog.write(agentCsvHeader(sim.agentRuntimeStats[0]))
            agentLog.write(agentCsvRows(sim.agentRuntimeStats))
          else:
            agentLog.write("[\n")
            agentLog.write(agentJsonRows(sim.agentRuntimeStats, false))
        if csv:
          agentLog.write(agentCsvRows(sim.agentRuntimeStats))
        else:
          agentLog.write(agentJsonRows(sim.agentRuntimeStats, false))
      sim.agentRuntimeStats.setLen(0)

  if logPath.len > 0:
    sim.finalEnvironmentStats()
    if csv:
      log.write(csvRow(sim.runtimeStats))
    else:
      log.write("\t" & pythonJson(sim.runtimeStats) & "\n]")
    log.flushFile()
    log.close()
  if agentLogPath.len > 0:
    if csv:
      agentLog.write(agentCsvRows(sim.agentRuntimeStats))
    else:
      agentLog.write(agentJsonRows(sim.agentRuntimeStats, true))
    agentLog.flushFile()
    agentLog.close()
