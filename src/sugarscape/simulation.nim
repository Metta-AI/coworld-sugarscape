import std/[algorithm, json, math, syncio]

import ./agents
import ./environment
import ./py_json
import ./py_random

type
  Candidate = object
    cell: int
    welfare: float64
    distance: float64

  Simulation* = object
    config*: JsonNode
    environment*: Environment
    agents*: seq[Agent]
    activeAgents*: seq[int]
    rng*: PyRandom
    timestep*: int
    maxTimestep*: int
    meanWealth*: float64
    carryingCapacity*: int
    runtimeStats*: JsonNode

proc initialRuntimeStats(seed: int64): JsonNode =
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
  integer("seed", seed)
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
  integer("remainingRaces")
  integer("remainingTribes")
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

proc roundHalfEven(value: float64, places: int): float64 =
  let scale = pow(10.0, float64(places))
  let scaled = value * scale
  let lower = floor(scaled)
  let fraction = scaled - lower
  var rounded: float64
  if fraction < 0.5:
    rounded = lower
  elif fraction > 0.5:
    rounded = lower + 1.0
  elif int64(lower) mod 2 == 0:
    rounded = lower
  else:
    rounded = lower + 1.0
  rounded / scale

proc timeToLive(agent: Agent, ageLimited: bool): float64 =
  let
    sugarTime =
      if agent.sugarMetabolism > 0:
        agent.sugar / agent.sugarMetabolism
      else:
        float64(high(int))
    spiceTime =
      if agent.spiceMetabolism > 0:
        agent.spice / agent.spiceMetabolism
      else:
        float64(high(int))
  result = min(sugarTime, spiceTime)
  if ageLimited:
    result = min(result, float64(agent.maxAge - agent.age))

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

proc updateRuntimeStats(sim: var Simulation) =
  let population = sim.activeAgents.len
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
    totalWealthHappiness = 0.0
    maxWealth = -Inf
    minWealth = Inf
    agentWealthCollected = 0.0
    agentWealthBurnRate = 0.0
    agentMeanTimeToLive = 0.0
    optimalMoves = 0
    agentMoves = 0
    totalNeighbors = 0.0
    totalValidMoves = 0.0
    totalMoveRank = 0.0
    totalMoveDifference = 0.0
    moveSpace = 0

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
    totalWealth += wealth
    totalWealthHappiness += agent.wealthHappiness
    maxWealth = max(maxWealth, wealth)
    minWealth = min(minWealth, wealth)
    agentWealthCollected +=
      wealth - (agent.lastSugar + agent.lastSpice)
    agentWealthBurnRate += timeToLive(agent, false)
    agentMeanTimeToLive += timeToLive(agent, true)
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
        break

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
  else:
    maxWealth = 0
    minWealth = 0
    totalHappiness = 0

  sim.meanWealth = meanWealth
  template setFloat(name: string, value: float64) =
    sim.runtimeStats[name] = newJFloat(value)
  template setInt(name: string, value: int64) =
    sim.runtimeStats[name] = newJInt(value)

  setInt("timestep", int64(sim.timestep))
  setInt("population", int64(population))
  setFloat("meanMetabolism", meanMetabolism)
  setFloat("meanMovement", meanMovement)
  setFloat("meanVision", meanVision)
  setFloat("meanWealth", meanWealth)
  setFloat("meanAge", meanAge)
  setFloat("giniCoefficient", sim.giniCoefficient())
  setInt("meanTradePrice", 0)
  setInt("tradeVolume", 0)
  setInt("maxWealth", int64(maxWealth))
  setInt("minWealth", int64(minWealth))
  setFloat("meanHappiness", meanHappiness)
  setFloat("meanWealthHappiness", meanWealthHappiness)
  setFloat("meanHealthHappiness", meanHealthHappiness)
  setFloat("meanSocialHappiness", meanSocialHappiness)
  setFloat("meanFamilyHappiness", meanFamilyHappiness)
  setFloat("meanConflictHappiness", meanConflictHappiness)
  setInt("meanAgeAtDeath", 0)
  setInt("agentsReplaced", 0)
  setInt("agentsBorn", 0)
  setInt("agentStarvationDeaths", 0)
  setInt("agentDiseaseDeaths", 0)
  setInt("environmentWealthCreated", environmentWealthCreated)
  setInt("agentWealthTotal", int64(totalWealth))
  setInt("environmentWealthTotal", environmentWealthTotal)
  setInt("agentWealthCollected", int64(agentWealthCollected))
  setFloat("agentWealthBurnRate", agentWealthBurnRate)
  setFloat("agentMeanTimeToLive", agentMeanTimeToLive)
  setInt(
    "agentTotalMetabolism",
    int64(totalSugarMetabolism + totalSpiceMetabolism),
  )
  setInt("agentCombatDeaths", 0)
  setInt("agentAgingDeaths", 0)
  setInt("agentDeaths", 0)
  if population > 0:
    sim.runtimeStats["largestRace"] = newJNull()
    sim.runtimeStats["largestTribe"] = newJNull()
  else:
    setInt("largestRace", 0)
    setInt("largestTribe", 0)
  setInt("largestRaceSize", int64(population))
  setInt("largestTribeSize", int64(population))
  setInt("remainingRaces", if population > 0: 1 else: 0)
  setInt("remainingTribes", if population > 0: 1 else: 0)
  setInt("sickAgents", 0)
  setInt("carryingCapacity", int64(sim.carryingCapacity))
  setFloat("meanDeathsPercentage", 0.0)
  setFloat("sickAgentsPercentage", 0.0)
  setFloat("meanSelfishness", meanSelfishness)
  setInt("diseaseEffectiveReproductionRate", 0)
  setInt("diseaseIncidence", 0)
  setInt("diseasePrevalence", 0)
  setFloat("agentLastMoveOptimalityPercentage", optimalPercentage)
  setFloat("meanNeighbors", meanNeighbors)
  setFloat("meanMoveRank", meanMoveRank)
  setFloat("meanMoveDifferenceFromOptimal", meanMoveDifference)
  setFloat("meanValidMoves", meanValidMoves)
  setFloat("totalHappiness", totalHappiness)
  setInt("loanVolume", 0)
  setFloat("meanAgeismFactor", meanAgeism)
  setFloat("meanRacismFactor", meanRacism)
  setFloat("meanSexismFactor", meanSexism)
  setInt("moveSpace", int64(moveSpace))

proc findCellsInRange(sim: Simulation, agent: Agent): seq[RangeEntry] =
  let cellRange =
    min(min(agent.vision, agent.movement), sim.environment.maxCellDistance)
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

proc welfare(agent: Agent, cell: Cell): float64 =
  let
    totalMetabolism = agent.sugarMetabolism + agent.spiceMetabolism
    sugarProportion =
      if totalMetabolism == 0: 0.0
      else: agent.sugarMetabolism / totalMetabolism
    spiceProportion =
      if totalMetabolism == 0: 0.0
      else: agent.spiceMetabolism / totalMetabolism
    sugarReward = float64(cell.sugar) / (1.0 + cell.pollution)
    spiceReward = float64(cell.spice) / (1.0 + cell.pollution)
    sugarLookahead = agent.sugarMetabolism * agent.lookaheadFactor
    spiceLookahead = agent.spiceMetabolism * agent.lookaheadFactor
    totalSugar = max(0.0, agent.sugar + sugarReward - sugarLookahead)
    totalSpice = max(0.0, agent.spice + spiceReward - spiceLookahead)
  pow(totalSugar, sugarProportion) * pow(totalSpice, spiceProportion)

proc sortCandidates(candidates: var seq[Candidate]) =
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

proc bestCell(sim: var Simulation, id: int): int =
  sim.agents[id].movementNeighborhood.setLen(0)
  for candidate in sim.agents[id].cellsInRange:
    let occupant = sim.environment.cells[candidate.cell].agent
    if occupant >= 0 and sim.agents[occupant].alive:
      sim.agents[id].movementNeighborhood.add(occupant)
  sim.agents[id].movementNeighborhood.add(id)

  var candidates = sim.agents[id].cellsInRange
  sim.rng.shuffle(candidates)

  var ranked = newSeqOfCap[Candidate](candidates.len)
  for candidate in candidates:
    let occupant = sim.environment.cells[candidate.cell].agent
    # Base agents have zero aggression. An occupied destination is therefore
    # ineligible, matching isNeighborValidPrey(False).
    if occupant >= 0:
      continue
    ranked.add(
      Candidate(
        cell: candidate.cell,
        welfare: welfare(sim.agents[id], sim.environment.cells[candidate.cell]),
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
    return sim.agents[id].cell

  ranked.sortCandidates()
  sim.agents[id].lastMoveRank = 0
  sim.agents[id].lastValidMoves = ranked.len
  sim.agents[id].lastMoveOptimal = true
  sim.agents[id].validMoves.setLen(0)
  for candidate in ranked:
    sim.agents[id].validMoves.add(
      MoveOption(cell: candidate.cell, welfare: candidate.welfare)
    )
  ranked[0].cell

proc killAgent(sim: var Simulation, id: int) =
  sim.agents[id].alive = false
  if sim.agents[id].cell >= 0:
    sim.environment.cells[sim.agents[id].cell].agent = -1
    sim.agents[id].cell = -1

proc activate(sim: var Simulation, id: int) =
  if not sim.agents[id].alive or
      sim.agents[id].lastMovedTimestep == sim.timestep:
    return

  sim.agents[id].lastSugar = sim.agents[id].sugar
  sim.agents[id].lastSpice = sim.agents[id].spice

  let destination = sim.bestCell(id)
  sim.environment.cells[sim.agents[id].cell].agent = -1
  sim.agents[id].cell = destination
  sim.agents[id].lastMovedTimestep = sim.timestep
  sim.environment.cells[destination].agent = id

  sim.agents[id].sugar += float64(sim.environment.cells[destination].sugar)
  sim.agents[id].spice += float64(sim.environment.cells[destination].spice)
  if sim.environment.pollutionStart <= sim.timestep and
      sim.timestep <= sim.environment.pollutionEnd:
    sim.environment.cells[destination].pollution +=
      float64(sim.environment.cells[destination].sugar) *
      sim.environment.sugarProductionPollutionFactor
    sim.environment.cells[destination].pollution +=
      float64(sim.environment.cells[destination].spice) *
      sim.environment.spiceProductionPollutionFactor
  sim.environment.cells[destination].sugar = 0
  sim.environment.cells[destination].spice = 0

  sim.agents[id].sugar -= sim.agents[id].sugarMetabolism
  sim.agents[id].spice -= sim.agents[id].spiceMetabolism
  if sim.environment.pollutionStart <= sim.timestep and
      sim.timestep <= sim.environment.pollutionEnd:
    sim.environment.cells[destination].pollution +=
      sim.agents[id].sugarMetabolism *
      sim.environment.sugarConsumptionPollutionFactor
    sim.environment.cells[destination].pollution +=
      sim.agents[id].spiceMetabolism *
      sim.environment.spiceConsumptionPollutionFactor
  if sim.agents[id].sugar < 0 or sim.agents[id].spice < 0 or
      (
        sim.agents[id].sugar <= 0 and
        sim.agents[id].sugarMetabolism > 0
      ) or
      (
        sim.agents[id].spice <= 0 and
        sim.agents[id].spiceMetabolism > 0
      ):
    sim.killAgent(id)
    return

  inc sim.agents[id].age
  if sim.agents[id].maxAge != -1 and
      sim.agents[id].age >= sim.agents[id].maxAge:
    sim.killAgent(id)
    return

  sim.agents[id].cellsInRange = sim.findCellsInRange(sim.agents[id])
  sim.agents[id].conflictHappiness = 0
  sim.agents[id].familyHappiness = 0
  sim.agents[id].healthHappiness = 1
  sim.agents[id].socialHappiness = 0
  sim.agents[id].wealthHappiness =
    erf(sim.agents[id].sugar + sim.agents[id].spice - sim.meanWealth)
  sim.agents[id].happiness =
    sim.agents[id].conflictHappiness +
    sim.agents[id].familyHappiness +
    sim.agents[id].healthHappiness +
    sim.agents[id].socialHappiness +
    sim.agents[id].wealthHappiness

proc initSimulation*(config: JsonNode): Simulation =
  result.config = config
  result.timestep = 0
  result.maxTimestep = config["timesteps"].getInt()
  let seed = config["seed"].getBiggestInt()
  if seed < 0:
    raise newException(
      ValueError,
      "nondeterministic seed -1 is not implemented in the native bootstrap"
    )
  result.rng = initPyRandom(uint64(seed))
  result.runtimeStats = initialRuntimeStats(seed)
  result.environment = initEnvironment(config)
  result.agents =
    createInitialAgents(config, result.environment, result.rng)
  result.activeAgents = newSeq[int](result.agents.len)
  for id in 0 ..< result.agents.len:
    result.activeAgents[id] = id
    result.agents[id].cellsInRange =
      result.findCellsInRange(result.agents[id])

  # configureDiseases shuffles the agent list even when startingDiseases is 0.
  result.rng.shuffle(result.activeAgents)
  result.updateRuntimeStats()

proc doTimestep*(sim: var Simulation) =
  if sim.timestep >= sim.maxTimestep:
    return
  inc sim.timestep
  if sim.activeAgents.len == 0 and
      not sim.config["keepAlivePostExtinction"].getBool():
    return

  sim.environment.doTimestep(sim.timestep)
  sim.rng.shuffle(sim.activeAgents)
  let activationOrder = sim.activeAgents
  for id in activationOrder:
    sim.activate(id)

  var living = newSeqOfCap[int](sim.activeAgents.len)
  for id in sim.activeAgents:
    if sim.agents[id].alive:
      living.add(id)
  sim.activeAgents = living
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

proc runSimulation*(sim: var Simulation, logPath: string) =
  var log: File
  if logPath.len > 0:
    if not open(log, logPath, fmAppend):
      raise newException(IOError, "could not open logfile: " & logPath)
    log.write("[\n")
    log.write("\t" & pythonJson(initialRuntimeStats(
      sim.config["seed"].getBiggestInt()
    )) & ",\n")

  while sim.timestep < sim.maxTimestep:
    if sim.activeAgents.len == 0 and
        not sim.config["keepAlivePostExtinction"].getBool():
      break
    sim.doTimestep()
    if logPath.len > 0 and sim.timestep != sim.maxTimestep and
        sim.activeAgents.len > 0:
      log.write("\t" & pythonJson(sim.runtimeStats) & ",\n")

  if logPath.len > 0:
    sim.finalEnvironmentStats()
    log.write("\t" & pythonJson(sim.runtimeStats) & "\n]")
    log.flushFile()
    log.close()
