import std/[algorithm, json, monotimes, strutils, tables, times]

when isMainModule:
  import std/os

const
  SchemaVersion = 1
  SourcePin = "585282e9ce7b22a33b89abb0d777917bd5887d1a"
  MtWords = 624
  EmptyOccupant = -1'i64

type
  PythonMt19937* = object
    words*: array[MtWords, uint32]
    index*: int

  Cell* = object
    sugar*: float64
    maxSugar*: float64
    occupantId*: int64

  Agent* = object
    id*: int64
    seat*: int
    x*: int
    y*: int
    sugar*: float64
    age*: int64
    sugarMetabolism*: float64
    vision*: int
    movement*: int
    maxAge*: int64
    lookaheadFactor*: float64

  Candidate* = object
    target*: int
    distance*: float64

  World* = object
    sourcePin*: string
    timestep*: int64
    width*: int
    height*: int
    sugarRegrowRate*: float64
    maxCellDistance*: int
    rng*: PythonMt19937
    liveOrder*: seq[int64]
    cells*: seq[Cell]
    agents*: seq[Agent]
    orderedCandidates*: seq[seq[Candidate]]

proc twist(rng: var PythonMt19937) =
  const
    UpperMask = 0x80000000'u32
    LowerMask = 0x7fffffff'u32
    MatrixA = 0x9908b0df'u32
  for i in 0 ..< MtWords:
    let combined = (rng.words[i] and UpperMask) or
      (rng.words[(i + 1) mod MtWords] and LowerMask)
    rng.words[i] = rng.words[(i + 397) mod MtWords] xor (combined shr 1)
    if (combined and 1'u32) != 0:
      rng.words[i] = rng.words[i] xor MatrixA
  rng.index = 0

proc nextUint32*(rng: var PythonMt19937): uint32 =
  if rng.index == MtWords:
    rng.twist()
  doAssert rng.index >= 0 and rng.index < MtWords, "invalid MT19937 index"
  result = rng.words[rng.index]
  inc rng.index
  result = result xor (result shr 11)
  result = result xor ((result shl 7) and 0x9d2c5680'u32)
  result = result xor ((result shl 15) and 0xefc60000'u32)
  result = result xor (result shr 18)

proc getRandBits*(rng: var PythonMt19937, bits: int): uint64 =
  doAssert bits >= 0 and bits <= 64, "getRandBits supports 0..64 bits"
  if bits == 0:
    return 0
  if bits <= 32:
    return uint64(rng.nextUint32() shr (32 - bits))
  let low = uint64(rng.nextUint32())
  let highBits = bits - 32
  let high = uint64(rng.nextUint32() shr (32 - highBits))
  low or (high shl 32)

proc bitLength(value: uint64): int =
  var remaining = value
  while remaining != 0:
    inc result
    remaining = remaining shr 1

proc randBelow*(rng: var PythonMt19937, upperBound: uint64): uint64 =
  doAssert upperBound > 0, "randBelow upper bound must be positive"
  let bits = bitLength(upperBound)
  result = rng.getRandBits(bits)
  while result >= upperBound:
    result = rng.getRandBits(bits)

proc pythonShuffle*[T](rng: var PythonMt19937, values: var seq[T]) =
  if values.len < 2:
    return
  for i in countdown(values.high, 1):
    let j = int(rng.randBelow(uint64(i + 1)))
    swap(values[i], values[j])

proc requireFields(node: JsonNode, expected: openArray[string], context: string) =
  doAssert node.kind == JObject, context & " must be an object"
  var actual = newSeq[string]()
  for key in node.keys:
    actual.add(key)
  actual.sort()
  var wanted = @expected
  wanted.sort()
  doAssert actual == wanted, context & " fields must be " & wanted.join(", ")

proc readInt(node: JsonNode, field: string): int64 =
  doAssert node[field].kind == JInt, field & " must be an integer"
  node[field].getBiggestInt()

proc readNumber(node: JsonNode, field: string): float64 =
  doAssert node[field].kind in {JInt, JFloat}, field & " must be a number"
  if node[field].kind == JInt:
    float64(node[field].getBiggestInt())
  else:
    node[field].getFloat()

proc loadRng*(node: JsonNode): PythonMt19937 =
  node.requireFields(["version", "words", "index", "gaussNext"], "rng")
  doAssert node["version"].getInt() == 3, "unsupported Python RNG state version"
  doAssert node["gaussNext"].kind == JNull, "rng.gaussNext must be null"
  doAssert node["words"].kind == JArray and node["words"].len == MtWords,
    "rng.words must contain 624 integers"
  result.index = node["index"].getInt()
  doAssert result.index >= 0 and result.index <= MtWords, "invalid MT19937 index"
  var i = 0
  for word in node["words"].items:
    let value = word.getBiggestInt()
    doAssert value >= 0 and value <= int64(high(uint32)), "invalid MT19937 word"
    result.words[i] = uint32(value)
    inc i

proc loadWorld*(node: JsonNode): World =
  node.requireFields(
    ["schemaVersion", "sourcePin", "timestep", "width", "height", "sugarRegrowRate",
     "maxCellDistance", "rng", "liveOrder", "cells", "agents", "orderedCandidates"],
    "snapshot",
  )
  doAssert node["schemaVersion"].getInt() == SchemaVersion, "unsupported schema version"
  result.sourcePin = node["sourcePin"].getStr()
  doAssert result.sourcePin == SourcePin, "unsupported sourcePin"
  result.timestep = node.readInt("timestep")
  result.width = int(node.readInt("width"))
  result.height = int(node.readInt("height"))
  result.sugarRegrowRate = node.readNumber("sugarRegrowRate")
  result.maxCellDistance = int(node.readInt("maxCellDistance"))
  doAssert result.timestep >= 0, "timestep must be nonnegative"
  doAssert result.width > 0 and result.height > 0, "world dimensions must be positive"
  doAssert result.sugarRegrowRate >= 0, "sugarRegrowRate must be nonnegative"
  doAssert result.maxCellDistance >= 0, "maxCellDistance must be nonnegative"
  result.rng = loadRng(node["rng"])

  doAssert node["liveOrder"].kind == JArray, "liveOrder must be an array"
  for id in node["liveOrder"].items:
    result.liveOrder.add(id.getBiggestInt())

  doAssert node["cells"].kind == JArray and node["cells"].len == result.width * result.height,
    "cells must contain width * height entries in x-major order"
  for cellNode in node["cells"].items:
    cellNode.requireFields(["sugar", "maxSugar", "occupantId"], "cell")
    let occupantId = if cellNode["occupantId"].kind == JNull:
      EmptyOccupant
    else:
      cellNode.readInt("occupantId")
    let cell = Cell(
      sugar: cellNode.readNumber("sugar"),
      maxSugar: cellNode.readNumber("maxSugar"),
      occupantId: occupantId,
    )
    doAssert cell.sugar >= 0 and cell.maxSugar >= 0 and cell.sugar <= cell.maxSugar,
      "cell sugar must be between zero and maxSugar"
    result.cells.add(cell)

  doAssert node["agents"].kind == JArray, "agents must be an array"
  var previousId = EmptyOccupant
  var agentIds = newSeq[int64]()
  for agentNode in node["agents"].items:
    agentNode.requireFields(
      ["id", "seat", "x", "y", "sugar", "age", "sugarMetabolism", "vision", "movement",
       "maxAge", "lookaheadFactor"],
      "agent",
    )
    let agent = Agent(
      id: agentNode.readInt("id"),
      seat: int(agentNode.readInt("seat")),
      x: int(agentNode.readInt("x")),
      y: int(agentNode.readInt("y")),
      sugar: agentNode.readNumber("sugar"),
      age: agentNode.readInt("age"),
      sugarMetabolism: agentNode.readNumber("sugarMetabolism"),
      vision: int(agentNode.readInt("vision")),
      movement: int(agentNode.readInt("movement")),
      maxAge: agentNode.readInt("maxAge"),
      lookaheadFactor: agentNode.readNumber("lookaheadFactor"),
    )
    doAssert agent.id >= 0 and agent.id > previousId, "agents must be sorted by unique id"
    doAssert agent.seat >= 0 and agent.x >= 0 and agent.x < result.width and
      agent.y >= 0 and agent.y < result.height, "invalid agent identity or position"
    doAssert agent.sugar >= 0 and agent.age >= 0 and agent.sugarMetabolism >= 0 and
      agent.vision >= 0 and agent.movement >= 0 and agent.lookaheadFactor >= 0,
      "agent resources and traits must be nonnegative"
    doAssert agent.maxAge == -1, "aging death is unsupported"
    previousId = agent.id
    agentIds.add(agent.id)
    result.agents.add(agent)

  var orderedIds = result.liveOrder
  orderedIds.sort()
  doAssert orderedIds == agentIds, "liveOrder must contain every agent id exactly once"
  for index, cell in result.cells:
    if cell.occupantId != EmptyOccupant:
      doAssert cell.occupantId in agentIds, "cell occupantId does not name an agent"
      let agentIndex = agentIds.find(cell.occupantId)
      doAssert result.agents[agentIndex].x * result.height + result.agents[agentIndex].y == index,
        "cell occupantId disagrees with the agent position"
  for agent in result.agents:
    doAssert result.cells[agent.x * result.height + agent.y].occupantId == agent.id,
      "agent position disagrees with the cell occupantId"

  doAssert node["orderedCandidates"].kind == JArray and
    node["orderedCandidates"].len == result.cells.len,
    "orderedCandidates must contain one array per cell"
  var origin = 0
  for candidatesNode in node["orderedCandidates"].items:
    doAssert candidatesNode.kind == JArray, "orderedCandidates entries must be arrays"
    var candidates = newSeq[Candidate]()
    for candidateNode in candidatesNode.items:
      doAssert candidateNode.kind == JArray and candidateNode.len == 2,
        "ordered candidate must be [cellIndex, distance]"
      let target = candidateNode[0].getInt()
      let distance = if candidateNode[1].kind == JInt:
        float64(candidateNode[1].getBiggestInt())
      else:
        candidateNode[1].getFloat()
      doAssert target >= 0 and target < result.cells.len and target != origin,
        "ordered candidate index is invalid"
      doAssert distance > 0 and distance <= float64(result.maxCellDistance),
        "ordered candidate distance is invalid"
      for candidate in candidates:
        doAssert candidate.target != target, "ordered candidates must be unique"
      candidates.add(Candidate(target: target, distance: distance))
    result.orderedCandidates.add(candidates)
    inc origin

proc rngJson(rng: PythonMt19937): JsonNode =
  var words = newJArray()
  for word in rng.words:
    words.add(%uint64(word))
  %*{"version": 3, "words": words, "index": rng.index, "gaussNext": newJNull()}

proc snapshot*(world: World): JsonNode =
  var liveOrder = newJArray()
  for id in world.liveOrder:
    liveOrder.add(%id)
  var cells = newJArray()
  for cell in world.cells:
    cells.add(%*{
      "sugar": cell.sugar,
      "maxSugar": cell.maxSugar,
      "occupantId": (if cell.occupantId == EmptyOccupant: newJNull() else: %cell.occupantId),
    })
  var agents = newJArray()
  for agent in world.agents:
    agents.add(%*{
      "id": agent.id, "seat": agent.seat, "x": agent.x, "y": agent.y,
      "sugar": agent.sugar, "age": agent.age, "sugarMetabolism": agent.sugarMetabolism,
      "vision": agent.vision, "movement": agent.movement, "maxAge": agent.maxAge,
      "lookaheadFactor": agent.lookaheadFactor,
    })
  var orderedCandidates = newJArray()
  for candidates in world.orderedCandidates:
    var entries = newJArray()
    for candidate in candidates:
      entries.add(%*[candidate.target, candidate.distance])
    orderedCandidates.add(entries)
  %*{
    "schemaVersion": SchemaVersion, "sourcePin": world.sourcePin, "timestep": world.timestep,
    "width": world.width, "height": world.height, "sugarRegrowRate": world.sugarRegrowRate,
    "maxCellDistance": world.maxCellDistance, "rng": rngJson(world.rng),
    "liveOrder": liveOrder, "cells": cells, "agents": agents,
    "orderedCandidates": orderedCandidates,
  }

proc stepOne*(world: var World) =
  inc world.timestep
  for cell in world.cells.mitems:
    cell.sugar = min(cell.maxSugar, cell.sugar + world.sugarRegrowRate)

  world.rng.pythonShuffle(world.liveOrder)
  var agentIndexById = initTable[int64, int]()
  for index, agent in world.agents:
    agentIndexById[agent.id] = index

  for id in world.liveOrder:
    let agentIndex = agentIndexById[id]
    var agent = world.agents[agentIndex]
    let origin = agent.x * world.height + agent.y
    let cellRange = min(min(agent.vision, agent.movement), world.maxCellDistance)
    var candidates = newSeq[Candidate]()
    for candidate in world.orderedCandidates[origin]:
      if candidate.distance <= float64(cellRange):
        candidates.add(candidate)
    world.rng.pythonShuffle(candidates)

    var destination = origin
    var bestWelfare = low(float64)
    var bestDistance = high(float64)
    for candidate in candidates:
      if world.cells[candidate.target].occupantId != EmptyOccupant:
        continue
      let welfare = if agent.sugarMetabolism == 0:
        1.0
      else:
        max(agent.sugar + world.cells[candidate.target].sugar -
          agent.sugarMetabolism * agent.lookaheadFactor, 0.0)
      if welfare > bestWelfare or (welfare == bestWelfare and candidate.distance < bestDistance):
        destination = candidate.target
        bestWelfare = welfare
        bestDistance = candidate.distance

    if destination != origin:
      world.cells[origin].occupantId = EmptyOccupant
      world.cells[destination].occupantId = agent.id
      agent.x = destination div world.height
      agent.y = destination mod world.height
    agent.sugar += world.cells[destination].sugar
    world.cells[destination].sugar = 0
    agent.sugar -= agent.sugarMetabolism
    doAssert agent.sugarMetabolism == 0 or agent.sugar > 0,
      "agent death is unsupported in fixed-population mode"
    inc agent.age
    world.agents[agentIndex] = agent

proc step*(world: var World, ticks: int) =
  doAssert ticks >= 0, "ticks must be nonnegative"
  for _ in 0 ..< ticks:
    world.stepOne()

when isMainModule:
  proc usage(): string =
    "usage: sugarscape-native (step|bench) --ticks N < snapshot.json"

  let arguments = commandLineParams()
  doAssert arguments.len == 3 and arguments[0] in ["step", "bench"] and
    arguments[1] == "--ticks", usage()
  let ticks = parseInt(arguments[2])
  var world = loadWorld(parseJson(stdin.readAll()))
  let started = getMonoTime()
  world.step(ticks)
  let elapsedNs = (getMonoTime() - started).inNanoseconds
  if arguments[0] == "bench":
    stdout.write($(%*{"ticks": ticks, "elapsedNs": elapsedNs, "snapshot": world.snapshot()}))
  else:
    stdout.write($world.snapshot())
  stdout.write("\n")
