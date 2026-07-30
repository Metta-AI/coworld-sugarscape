import std/[json, math]

type
  RangeEntry* = object
    cell*: int
    distance*: float64

  Season* = enum
    noSeason
    wet
    dry

  Cell* = object
    x*, y*: int
    maxSugar*, maxSpice*: int64
    sugar*, spice*: int64
    sugarLastProduced*, spiceLastProduced*: int64
    pollution*, pollutionFlux*: float64
    agent*: int
    neighbors*: array[8, int]
    neighborCount*: int
    season*: Season
    timestep*: int

  Environment* = object
    width*, height*: int
    equator*: int
    wraparound*: bool
    neighborhoodMode*: string
    visionMode*, movementMode*: string
    maxCellDistance*: int
    sugarRegrowRate*, spiceRegrowRate*: int64
    seasonInterval*: int
    seasonalGrowbackDelay*, seasonalGrowbackCountdown*: int
    pollutionDiffusionDelay*, pollutionDiffusionCountdown*: int
    pollutionDiffusionStart*, pollutionDiffusionEnd*: int
    pollutionStart*, pollutionEnd*: int
    sugarConsumptionPollutionFactor*: float64
    sugarProductionPollutionFactor*: float64
    spiceConsumptionPollutionFactor*: float64
    spiceProductionPollutionFactor*: float64
    timestep*: int
    cells*: seq[Cell]
    ## Indexed by cell ID, then integer distance. Entry order is observable:
    ## DTL copies these ordered dicts before shuffling movement candidates.
    ranges*: seq[seq[seq[RangeEntry]]]

proc cellId*(world: Environment, x, y: int): int {.inline.} =
  x * world.height + y

proc wrapCoordinate(value, border: int): int {.inline.} =
  let remainder = value mod border
  if remainder < 0: remainder + border else: remainder

proc wraparoundDistance(delta, border: int, enabled: bool): int {.inline.} =
  result = abs(delta)
  if enabled and float64(result) > float64(border) / 2.0:
    result = border - result

proc setRange(
    world: var Environment,
    source, distance, destination: int,
    exactDistance: float64,
) =
  for entry in world.ranges[source][distance].mitems:
    if entry.cell == destination:
      entry.distance = exactDistance
      return
  world.ranges[source][distance].add(
    RangeEntry(cell: destination, distance: exactDistance)
  )

proc addResourcePeak(
    world: var Environment,
    startX, startY, radius, maximum: int,
    sugar: bool,
) =
  let radialDispersion =
    sqrt(
      float64(max(startX, world.width - startX) ^ 2) +
      float64(max(startY, world.height - startY) ^ 2)
    ) * (float64(radius) / float64(world.width))

  for x in 0 ..< world.width:
    for y in 0 ..< world.height:
      let
        euclideanDistance =
          sqrt(float64((startX - x) ^ 2 + (startY - y) ^ 2))
        currentDispersion =
          1.0 + float64(maximum) *
          (1.0 - euclideanDistance / radialDispersion)
        capacity = int64(ceil(min(currentDispersion, float64(maximum))))
        id = world.cellId(x, y)
      if sugar and capacity > world.cells[id].maxSugar:
        world.cells[id].maxSugar = capacity
        world.cells[id].sugar = capacity
      elif not sugar and capacity > world.cells[id].maxSpice:
        world.cells[id].maxSpice = capacity
        world.cells[id].spice = capacity

proc neighborId(
    world: Environment,
    x, y, deltaX, deltaY: int,
    preserveSouthBoundaryBug = false,
): int =
  if not world.wraparound:
    if deltaX > 0 and x + deltaX > world.width - 1:
      return -1
    if deltaX < 0 and x + deltaX < 0:
      return -1
    if deltaY < 0 and y + deltaY < 0:
      return -1
    # This intentionally reproduces Cell.findSouthNeighbor's inverted check.
    if deltaY > 0 and preserveSouthBoundaryBug and
        y + deltaY < world.height - 1:
      return -1
  world.cellId(
    wrapCoordinate(x + deltaX, world.width),
    wrapCoordinate(y + deltaY, world.height),
  )

proc findCellNeighbors(world: var Environment) =
  for x in 0 ..< world.width:
    for y in 0 ..< world.height:
      let id = world.cellId(x, y)
      var count = 0
      template addNeighbor(candidate: int) =
        if candidate >= 0:
          world.cells[id].neighbors[count] = candidate
          inc count

      let
        north = world.neighborId(x, y, 0, -1)
        south = world.neighborId(x, y, 0, 1, true)
        east = world.neighborId(x, y, 1, 0)
        west = world.neighborId(x, y, -1, 0)
      addNeighbor(north)
      addNeighbor(south)
      addNeighbor(east)
      addNeighbor(west)

      if world.neighborhoodMode == "moore":
        if north >= 0:
          addNeighbor(
            world.neighborId(
              world.cells[north].x,
              world.cells[north].y,
              1,
              0,
            )
          )
          addNeighbor(
            world.neighborId(
              world.cells[north].x,
              world.cells[north].y,
              -1,
              0,
            )
          )
        if south >= 0:
          addNeighbor(
            world.neighborId(
              world.cells[south].x,
              world.cells[south].y,
              1,
              0,
            )
          )
          addNeighbor(
            world.neighborId(
              world.cells[south].x,
              world.cells[south].y,
              -1,
              0,
            )
          )
      world.cells[id].neighborCount = count

proc findCardinalCellRanges(
    world: var Environment,
    maxDeltaX, maxDeltaY: int,
) =
  for x in 0 ..< world.width:
    for y in 0 ..< world.height:
      let source = world.cellId(x, y)
      for destinationX in x + 1 .. x + maxDeltaX:
        let
          distance = wraparoundDistance(
            destinationX - x,
            world.width,
            world.wraparound,
          )
          destination = world.cellId(destinationX mod world.width, y)
        world.setRange(source, distance, destination, float64(distance))
        world.setRange(destination, distance, source, float64(distance))
      for destinationY in y + 1 .. y + maxDeltaY:
        let
          distance = wraparoundDistance(
            destinationY - y,
            world.height,
            world.wraparound,
          )
          destination = world.cellId(x, destinationY mod world.height)
        world.setRange(source, distance, destination, float64(distance))
        world.setRange(destination, distance, source, float64(distance))

proc findRadialCellRanges(
    world: var Environment,
    maxDeltaX, maxDeltaY, maxRadius: int,
) =
  for source in 0 ..< world.cells.len:
    let
      x1 = world.cells[source].x
      y1 = world.cells[source].y
    for destination in source + 1 ..< world.cells.len:
      let
        x2 = world.cells[destination].x
        y2 = world.cells[destination].y
        deltaX = wraparoundDistance(x1 - x2, world.width, world.wraparound)
        deltaY = wraparoundDistance(y1 - y2, world.height, world.wraparound)
      if deltaX > maxDeltaX or deltaY > maxDeltaY:
        continue
      let
        distance = sqrt(float64(deltaX ^ 2 + deltaY ^ 2))
        gridRange = int(floor(distance))
      if gridRange <= maxRadius:
        world.setRange(source, gridRange, destination, distance)
        world.setRange(destination, gridRange, source, distance)

proc findCellRanges(world: var Environment, config: JsonNode) =
  let
    maximumVision =
      config["startingDiseases"].getInt() *
      max(config["diseaseVisionPenalty"][1].getInt(), 0) +
      config["agentVision"][1].getInt()
    maximumMovement =
      config["startingDiseases"].getInt() *
      max(config["diseaseMovementPenalty"][1].getInt(), 0) +
      config["agentMovement"][1].getInt()
    maximumAgentRange = max(maximumVision, maximumMovement)
  var
    maxDeltaX = min(maximumAgentRange, world.width div 2)
    maxDeltaY = min(maximumAgentRange, world.height div 2)
  if not world.wraparound:
    maxDeltaX = min(maximumAgentRange, world.width - 1)
    maxDeltaY = min(maximumAgentRange, world.height - 1)
  let
    radialBorderX =
      if world.wraparound: world.width div 2 else: world.width - 1
    radialBorderY =
      if world.wraparound: world.height div 2 else: world.height - 1
    maxRadialDistance = min(
      maximumAgentRange,
      int(floor(sqrt(float64(radialBorderX ^ 2 + radialBorderY ^ 2)))),
    )

  world.maxCellDistance =
    if world.visionMode == "radial" and world.movementMode == "radial":
      maxRadialDistance
    else:
      max(maxDeltaX, maxDeltaY)
  world.ranges = newSeq[seq[seq[RangeEntry]]](world.cells.len)
  for cell in 0 ..< world.cells.len:
    world.ranges[cell] =
      newSeq[seq[RangeEntry]](world.maxCellDistance + 1)

  if world.visionMode == "radial" and world.movementMode == "radial":
    world.findRadialCellRanges(
      maxDeltaX,
      maxDeltaY,
      maxRadialDistance,
    )
  else:
    world.findCardinalCellRanges(maxDeltaX, maxDeltaY)

proc updatePollution(world: var Environment) =
  if world.pollutionDiffusionStart <= world.timestep and
      world.timestep <= world.pollutionDiffusionEnd and
      world.pollutionDiffusionDelay > 0:
    dec world.pollutionDiffusionCountdown
    if world.pollutionDiffusionCountdown == 0:
      world.pollutionDiffusionCountdown = world.pollutionDiffusionDelay

proc updateSeasons(world: var Environment) =
  if world.seasonInterval > 0:
    dec world.seasonalGrowbackCountdown
    if world.seasonalGrowbackCountdown == 0:
      world.seasonalGrowbackCountdown = world.seasonalGrowbackDelay

proc doCellUpdate(world: var Environment) =
  for cell in world.cells.mitems:
    let
      sugarRegrowth = min(cell.sugar + world.sugarRegrowRate, cell.maxSugar)
      spiceRegrowth = min(cell.spice + world.spiceRegrowRate, cell.maxSpice)
      previousSeason = cell.season
    cell.timestep = world.timestep
    if world.seasonInterval > 0:
      if world.timestep mod world.seasonInterval == 0:
        cell.season =
          if cell.season == wet: dry
          else: wet
      if previousSeason == wet or
          (
            previousSeason == dry and
            world.seasonalGrowbackCountdown == world.seasonalGrowbackDelay
          ):
        cell.sugarLastProduced =
          if world.sugarRegrowRate != 0: world.sugarRegrowRate else: 0
        cell.spiceLastProduced =
          if world.spiceRegrowRate != 0: world.spiceRegrowRate else: 0
        cell.sugar = sugarRegrowth
        cell.spice = spiceRegrowth
    else:
      cell.sugarLastProduced =
        if world.sugarRegrowRate != 0: world.sugarRegrowRate else: 0
      cell.spiceLastProduced =
        if world.spiceRegrowRate != 0: world.spiceRegrowRate else: 0
      cell.sugar = sugarRegrowth
      cell.spice = spiceRegrowth

  if world.pollutionDiffusionStart <= world.timestep and
      world.timestep <= world.pollutionDiffusionEnd and
      world.pollutionDiffusionDelay > 0 and
      world.pollutionDiffusionCountdown == world.pollutionDiffusionDelay:
    for cell in world.cells.mitems:
      var pollution = 0.0
      for index in 0 ..< cell.neighborCount:
        pollution += world.cells[cell.neighbors[index]].pollution
      cell.pollutionFlux = pollution / float64(cell.neighborCount)
    for cell in world.cells.mitems:
      cell.pollution = cell.pollutionFlux

proc doTimestep*(world: var Environment, timestep: int) =
  world.timestep = timestep
  world.updateSeasons()
  world.updatePollution()
  world.doCellUpdate()

proc initEnvironment*(config: JsonNode): Environment =
  result.width = config["environmentWidth"].getInt()
  result.height = config["environmentHeight"].getInt()
  result.equator =
    if config["environmentEquator"].getInt() >= 0:
      config["environmentEquator"].getInt()
    else:
      int(ceil(float64(result.height) / 2.0))
  result.wraparound = config["environmentWraparound"].getBool()
  result.neighborhoodMode = config["neighborhoodMode"].getStr()
  result.visionMode = config["agentVisionMode"].getStr()
  result.movementMode = config["agentMovementMode"].getStr()
  result.sugarRegrowRate = int64(config["environmentSugarRegrowRate"].getInt())
  result.spiceRegrowRate = int64(config["environmentSpiceRegrowRate"].getInt())
  result.seasonInterval = config["environmentSeasonInterval"].getInt()
  result.seasonalGrowbackDelay =
    config["environmentSeasonalGrowbackDelay"].getInt()
  result.seasonalGrowbackCountdown = result.seasonalGrowbackDelay
  result.pollutionDiffusionDelay =
    config["environmentPollutionDiffusionDelay"].getInt()
  result.pollutionDiffusionCountdown = result.pollutionDiffusionDelay
  result.pollutionDiffusionStart =
    config["environmentPollutionDiffusionTimeframe"][0].getInt()
  result.pollutionDiffusionEnd =
    config["environmentPollutionDiffusionTimeframe"][1].getInt()
  result.pollutionStart =
    config["environmentPollutionTimeframe"][0].getInt()
  result.pollutionEnd =
    config["environmentPollutionTimeframe"][1].getInt()
  result.sugarConsumptionPollutionFactor =
    config["environmentSugarConsumptionPollutionFactor"].getFloat()
  result.sugarProductionPollutionFactor =
    config["environmentSugarProductionPollutionFactor"].getFloat()
  result.spiceConsumptionPollutionFactor =
    config["environmentSpiceConsumptionPollutionFactor"].getFloat()
  result.spiceProductionPollutionFactor =
    config["environmentSpiceProductionPollutionFactor"].getFloat()
  result.cells = newSeq[Cell](result.width * result.height)

  for x in 0 ..< result.width:
    for y in 0 ..< result.height:
      let id = result.cellId(x, y)
      result.cells[id].x = x
      result.cells[id].y = y
      result.cells[id].agent = -1
      result.cells[id].season =
        if result.seasonInterval == 0:
          noSeason
        elif y < result.equator:
          wet
        else:
          dry

  let radius = int(ceil(sqrt(2.0 * float64(result.height + result.width))))
  for peak in config["environmentSugarPeaks"]:
    result.addResourcePeak(
      peak[0].getInt(),
      peak[1].getInt(),
      radius,
      peak[2].getInt(),
      true,
    )
  for peak in config["environmentSpicePeaks"]:
    result.addResourcePeak(
      peak[0].getInt(),
      peak[1].getInt(),
      radius,
      peak[2].getInt(),
      false,
    )

  result.findCellNeighbors()
  result.findCellRanges(config)
