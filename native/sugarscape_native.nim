import std/[algorithm, json, math, monotimes, sequtils, strutils, tables, times]
import checksums/md5

when isMainModule:
  import std/os

const
  SchemaVersion = 7
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
    spice*: float64
    maxSpice*: float64
    occupantId*: int64

  Agent* = object
    id*: int64
    seat*: int
    x*: int
    y*: int
    sugar*: float64
    spice*: float64
    age*: int64
    sugarMetabolism*: float64
    spiceMetabolism*: float64
    sugarMetabolismModifier*: float64
    spiceMetabolismModifier*: float64
    vision*: int
    movement*: int
    visionModifier*: int
    movementModifier*: int
    aggressionFactor*: float64
    aggressionFactorModifier*: float64
    fertilityFactor*: float64
    fertilityFactorModifier*: float64
    depressed*: bool
    happinessUnit*: float64
    maxFriends*: int
    friendlinessModifier*: float64
    happinessModifier*: float64
    hasTags*: bool
    tags*: seq[int]
    tribe*: int
    tagging*: bool
    maxAge*: int64
    lookaheadFactor*: float64
    tradeFactor*: float64
    marginalRateOfSubstitution*: float64
    tradeVolume*: int
    sugarPrice*: float64
    spicePrice*: float64
    lastTradeTimestep*: int64
    lastTradePartners*: int
    diseaseProtectionChance*: float64
    hasImmuneSystem*: bool
    immuneSystem*: seq[int]
    diseases*: seq[Infection]
    born*: int64
    startingSugar*: float64
    startingSpice*: float64
    sex*: string
    hasSex*: bool
    fertilityAge*: int64
    infertilityAge*: int64
    inheritancePolicy*: string
    lendingFactor*: float64
    baseInterestRate*: float64
    loanDuration*: int64
    sugarMeanIncome*: float64
    spiceMeanIncome*: float64
    hasStartingImmuneSystem*: bool
    startingImmuneSystem*: seq[int]
    hasRacialTags*: bool
    racialTags*: seq[int]
    fatherId*: int64
    motherId*: int64
    childrenIds*: seq[int64]
    mateIds*: seq[int64]
    lastMovedTimestep*: int64
    lastReproducedTimestep*: int64
    lastMates*: int
    lastLendedTimestep*: int64
    lastLoans*: int
    creditorLoans*: seq[Loan]
    debtorLoans*: seq[Loan]

  Infection* = object
    diseaseId*: int
    hasRange*: bool
    startIndex*: int
    endIndex*: int
    infectorId*: int64
    caught*: int64
    incubation*: int

  Disease* = object
    id*: int
    aggressionPenalty*: float64
    fertilityPenalty*: float64
    friendlinessPenalty*: float64
    happinessPenalty*: float64
    incubationPeriod*: int
    movementPenalty*: int
    spiceMetabolismPenalty*: float64
    startTimestep*: int64
    sugarMetabolismPenalty*: float64
    hasTags*: bool
    tags*: seq[int]
    transmissionChance*: float64
    visionPenalty*: int
    recoverable*: bool
    infectedIds*: seq[int64]

  Loan* = object
    creditorId*: int64
    debtorId*: int64
    sugarLoan*: float64
    spiceLoan*: float64
    duration*: int64
    origin*: int64

  CreditorTombstone* = object
    id*: int64
    inheritancePolicy*: string
    childrenIds*: seq[int64]

  Candidate* = object
    target*: int
    distance*: float64

  Death* = object
    id*: int64
    seat*: int
    age*: int64
    cause*: string

  World* = object
    sourcePin*: string
    configurationSha256*: string
    rulesetSha256*: seq[string]
    timestep*: int64
    width*: int
    height*: int
    sugarRegrowRate*: float64
    spiceRegrowRate*: float64
    maxCellDistance*: int
    maxCombatLoot*: float64
    maxTribes*: int
    inheritancePolicy*: string
    nextAgentId*: int64
    depressionPercentage*: float64
    rng*: PythonMt19937
    liveOrder*: seq[int64]
    cells*: seq[Cell]
    agents*: seq[Agent]
    creditorTombstones*: seq[CreditorTombstone]
    orderedCandidates*: seq[seq[Candidate]]
    orderedNeighbors*: seq[seq[int]]
    diseases*: seq[Disease]
    remainingDiseaseIds*: seq[int]
    deaths*: seq[Death]

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

proc randomFloat*(rng: var PythonMt19937): float64 =
  let high = uint64(rng.nextUint32() shr 5)
  let low = uint64(rng.nextUint32() shr 6)
  float64(high * 67108864'u64 + low) / 9007199254740992.0

proc seedWords(rng: var PythonMt19937, words: openArray[uint32]) =
  rng.words[0] = 19650218'u32
  for index in 1 ..< MtWords:
    let previous = rng.words[index - 1]
    rng.words[index] = 1812433253'u32 * (previous xor (previous shr 30)) + uint32(index)
  var stateIndex = 1
  var wordIndex = 0
  var remaining = max(MtWords, words.len)
  while remaining > 0:
    let previous = rng.words[stateIndex - 1]
    rng.words[stateIndex] = (rng.words[stateIndex] xor
      ((previous xor (previous shr 30)) * 1664525'u32)) + words[wordIndex] + uint32(wordIndex)
    inc stateIndex
    inc wordIndex
    if stateIndex >= MtWords:
      rng.words[0] = rng.words[MtWords - 1]
      stateIndex = 1
    if wordIndex >= words.len: wordIndex = 0
    dec remaining
  remaining = MtWords - 1
  while remaining > 0:
    let previous = rng.words[stateIndex - 1]
    rng.words[stateIndex] = (rng.words[stateIndex] xor
      ((previous xor (previous shr 30)) * 1566083941'u32)) - uint32(stateIndex)
    inc stateIndex
    if stateIndex >= MtWords:
      rng.words[0] = rng.words[MtWords - 1]
      stateIndex = 1
    dec remaining
  rng.words[0] = 0x80000000'u32
  rng.index = MtWords

proc seedFromMd5(rng: var PythonMt19937, value: string, addend: uint64) =
  let digest = toMD5(value)
  var words: array[4, uint32]
  for wordIndex in 0 ..< words.len:
    let start = 12 - wordIndex * 4
    words[wordIndex] = (uint32(digest[start]) shl 24) or
      (uint32(digest[start + 1]) shl 16) or (uint32(digest[start + 2]) shl 8) or
      uint32(digest[start + 3])
  var carry = addend
  for word in words.mitems:
    let sum = uint64(word) + (carry and 0xffffffff'u64)
    word = uint32(sum)
    carry = (carry shr 32) + (sum shr 32)
  rng.seedWords(words)

proc chooseParent(first, second: int, field: string, timestep: int64): int =
  var local: PythonMt19937
  local.seedFromMd5(field, uint64(timestep))
  if local.randBelow(2) == 0: first else: second

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
  result = if node[field].kind == JInt:
    float64(node[field].getBiggestInt())
  else:
    node[field].getFloat()
  doAssert result.classify notin {fcNan, fcInf, fcNegInf}, field & " must be finite"

proc isSha256(value: string): bool =
  if value.len != 64:
    return false
  for character in value:
    if character notin {'0' .. '9', 'a' .. 'f'}:
      return false
  true

proc diseaseIndex(diseases: openArray[Disease], id: int): int =
  for index, disease in diseases:
    if disease.id == id: return index
  -1

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
    ["schemaVersion", "sourcePin", "configurationSha256", "rulesetSha256", "timestep", "width", "height",
     "sugarRegrowRate", "spiceRegrowRate",
     "maxCellDistance", "maxCombatLoot", "maxTribes", "inheritancePolicy", "rng",
     "liveOrder", "cells", "agents", "orderedCandidates", "orderedNeighbors", "diseases",
     "remainingDiseaseIds", "nextAgentId", "depressionPercentage", "creditorTombstones", "deaths"],
    "snapshot",
  )
  doAssert node["schemaVersion"].getInt() == SchemaVersion, "unsupported schema version"
  result.sourcePin = node["sourcePin"].getStr()
  doAssert result.sourcePin == SourcePin, "unsupported sourcePin"
  result.configurationSha256 = node["configurationSha256"].getStr()
  doAssert result.configurationSha256.isSha256(), "configurationSha256 must be 64 lowercase hexadecimal characters"
  doAssert node["rulesetSha256"].kind == JArray and node["rulesetSha256"].len > 0,
    "rulesetSha256 must be a nonempty array"
  for digestNode in node["rulesetSha256"].items:
    let digest = digestNode.getStr()
    doAssert digest.isSha256(), "rulesetSha256 entries must be 64 lowercase hexadecimal characters"
    result.rulesetSha256.add(digest)
  result.timestep = node.readInt("timestep")
  result.width = int(node.readInt("width"))
  result.height = int(node.readInt("height"))
  result.sugarRegrowRate = node.readNumber("sugarRegrowRate")
  result.spiceRegrowRate = node.readNumber("spiceRegrowRate")
  result.maxCellDistance = int(node.readInt("maxCellDistance"))
  result.maxCombatLoot = node.readNumber("maxCombatLoot")
  result.maxTribes = int(node.readInt("maxTribes"))
  result.inheritancePolicy = node["inheritancePolicy"].getStr()
  result.nextAgentId = node.readInt("nextAgentId")
  result.depressionPercentage = node.readNumber("depressionPercentage")
  doAssert result.timestep >= 0, "timestep must be nonnegative"
  doAssert result.width > 0 and result.height > 0, "world dimensions must be positive"
  doAssert result.sugarRegrowRate >= 0 and result.spiceRegrowRate >= 0,
    "resource regrow rates must be nonnegative"
  doAssert result.maxCellDistance >= 0, "maxCellDistance must be nonnegative"
  doAssert result.maxCombatLoot >= 0, "maxCombatLoot must be nonnegative"
  doAssert result.maxTribes > 0, "maxTribes must be positive"
  doAssert result.inheritancePolicy in ["none", "children"], "only inheritancePolicy none or children is supported"
  doAssert result.nextAgentId >= 0 and result.depressionPercentage >= 0 and
    result.depressionPercentage <= 1, "invalid reproduction world state"
  result.rng = loadRng(node["rng"])

  doAssert node["liveOrder"].kind == JArray, "liveOrder must be an array"
  for id in node["liveOrder"].items:
    result.liveOrder.add(id.getBiggestInt())

  doAssert node["cells"].kind == JArray and node["cells"].len == result.width * result.height,
    "cells must contain width * height entries in x-major order"
  for cellNode in node["cells"].items:
    cellNode.requireFields(["sugar", "maxSugar", "spice", "maxSpice", "occupantId"], "cell")
    let occupantId = if cellNode["occupantId"].kind == JNull:
      EmptyOccupant
    else:
      cellNode.readInt("occupantId")
    let cell = Cell(
      sugar: cellNode.readNumber("sugar"),
      maxSugar: cellNode.readNumber("maxSugar"),
      spice: cellNode.readNumber("spice"),
      maxSpice: cellNode.readNumber("maxSpice"),
      occupantId: occupantId,
    )
    doAssert cell.sugar >= 0 and cell.maxSugar >= 0 and cell.sugar <= cell.maxSugar,
      "cell sugar must be between zero and maxSugar"
    doAssert cell.spice >= 0 and cell.maxSpice >= 0 and cell.spice <= cell.maxSpice,
      "cell spice must be between zero and maxSpice"
    result.cells.add(cell)

  doAssert node["agents"].kind == JArray, "agents must be an array"
  var previousId = EmptyOccupant
  var agentIds = newSeq[int64]()
  for agentNode in node["agents"].items:
    agentNode.requireFields(
      ["id", "seat", "x", "y", "sugar", "spice", "age", "sugarMetabolism",
       "spiceMetabolism", "sugarMetabolismModifier", "spiceMetabolismModifier",
       "vision", "movement", "visionModifier", "movementModifier", "maxAge", "lookaheadFactor",
       "aggressionFactor", "aggressionFactorModifier", "fertilityFactor",
       "fertilityFactorModifier", "depressed", "happinessUnit", "maxFriends",
       "friendlinessModifier", "happinessModifier", "tags", "tribe", "tagging",
       "tradeFactor", "marginalRateOfSubstitution", "tradeVolume", "sugarPrice",
       "spicePrice", "lastTradeTimestep", "lastTradePartners", "diseaseProtectionChance",
       "immuneSystem", "diseases", "born", "startingSugar", "startingSpice", "sex",
       "fertilityAge", "infertilityAge", "inheritancePolicy", "lendingFactor",
       "baseInterestRate", "loanDuration", "sugarMeanIncome", "spiceMeanIncome",
       "startingImmuneSystem", "racialTags", "fatherId", "motherId", "childrenIds", "mateIds",
       "lastMovedTimestep", "lastReproducedTimestep", "lastMates", "lastLendedTimestep",
       "lastLoans", "creditorLoans", "debtorLoans"],
      "agent",
    )
    var agent = Agent(
      id: agentNode.readInt("id"),
      seat: int(agentNode.readInt("seat")),
      x: int(agentNode.readInt("x")),
      y: int(agentNode.readInt("y")),
      sugar: agentNode.readNumber("sugar"),
      spice: agentNode.readNumber("spice"),
      age: agentNode.readInt("age"),
      sugarMetabolism: agentNode.readNumber("sugarMetabolism"),
      spiceMetabolism: agentNode.readNumber("spiceMetabolism"),
      sugarMetabolismModifier: agentNode.readNumber("sugarMetabolismModifier"),
      spiceMetabolismModifier: agentNode.readNumber("spiceMetabolismModifier"),
      vision: int(agentNode.readInt("vision")),
      movement: int(agentNode.readInt("movement")),
      visionModifier: int(agentNode.readInt("visionModifier")),
      movementModifier: int(agentNode.readInt("movementModifier")),
      aggressionFactor: agentNode.readNumber("aggressionFactor"),
      aggressionFactorModifier: agentNode.readNumber("aggressionFactorModifier"),
      fertilityFactor: agentNode.readNumber("fertilityFactor"),
      fertilityFactorModifier: agentNode.readNumber("fertilityFactorModifier"),
      depressed: agentNode["depressed"].getBool(),
      happinessUnit: agentNode.readNumber("happinessUnit"),
      maxFriends: int(agentNode.readInt("maxFriends")),
      friendlinessModifier: agentNode.readNumber("friendlinessModifier"),
      happinessModifier: agentNode.readNumber("happinessModifier"),
      hasTags: agentNode["tags"].kind != JNull,
      tribe: (if agentNode["tribe"].kind == JNull: -1 else: int(agentNode.readInt("tribe"))),
      tagging: agentNode["tagging"].getBool(),
      maxAge: agentNode.readInt("maxAge"),
      lookaheadFactor: agentNode.readNumber("lookaheadFactor"),
      tradeFactor: agentNode.readNumber("tradeFactor"),
      marginalRateOfSubstitution: agentNode.readNumber("marginalRateOfSubstitution"),
      tradeVolume: int(agentNode.readInt("tradeVolume")),
      sugarPrice: agentNode.readNumber("sugarPrice"),
      spicePrice: agentNode.readNumber("spicePrice"),
      lastTradeTimestep: agentNode.readInt("lastTradeTimestep"),
      lastTradePartners: int(agentNode.readInt("lastTradePartners")),
      diseaseProtectionChance: agentNode.readNumber("diseaseProtectionChance"),
      hasImmuneSystem: agentNode["immuneSystem"].kind != JNull,
      born: agentNode.readInt("born"),
      startingSugar: agentNode.readNumber("startingSugar"),
      startingSpice: agentNode.readNumber("startingSpice"),
      sex: (if agentNode["sex"].kind == JNull: "" else: agentNode["sex"].getStr()),
      hasSex: agentNode["sex"].kind != JNull,
      fertilityAge: agentNode.readInt("fertilityAge"),
      infertilityAge: agentNode.readInt("infertilityAge"),
      inheritancePolicy: agentNode["inheritancePolicy"].getStr(),
      lendingFactor: agentNode.readNumber("lendingFactor"),
      baseInterestRate: agentNode.readNumber("baseInterestRate"),
      loanDuration: agentNode.readInt("loanDuration"),
      sugarMeanIncome: agentNode.readNumber("sugarMeanIncome"),
      spiceMeanIncome: agentNode.readNumber("spiceMeanIncome"),
      hasStartingImmuneSystem: agentNode["startingImmuneSystem"].kind != JNull,
      hasRacialTags: agentNode["racialTags"].kind != JNull,
      fatherId: (if agentNode["fatherId"].kind == JNull: EmptyOccupant else: agentNode.readInt("fatherId")),
      motherId: (if agentNode["motherId"].kind == JNull: EmptyOccupant else: agentNode.readInt("motherId")),
      lastMovedTimestep: agentNode.readInt("lastMovedTimestep"),
      lastReproducedTimestep: agentNode.readInt("lastReproducedTimestep"),
      lastMates: int(agentNode.readInt("lastMates")),
      lastLendedTimestep: agentNode.readInt("lastLendedTimestep"),
      lastLoans: int(agentNode.readInt("lastLoans")),
    )
    doAssert agent.id >= 0 and agent.id > previousId, "agents must be sorted by unique id"
    doAssert agent.seat >= 0 and agent.x >= 0 and agent.x < result.width and
      agent.y >= 0 and agent.y < result.height, "invalid agent identity or position"
    doAssert agent.sugar >= 0 and agent.spice >= 0 and agent.age >= 0 and
      agent.sugarMetabolism >= 0 and agent.spiceMetabolism >= 0 and
      agent.vision >= 0 and agent.movement >= 0 and agent.lookaheadFactor >= 0,
      "agent resources and traits must be nonnegative"
    doAssert agent.aggressionFactor >= 0 and agent.fertilityFactor >= 0 and
      agent.happinessUnit >= 0 and agent.maxFriends >= 0,
      "agent base social traits must be nonnegative"
    doAssert agent.tradeFactor >= 0 and agent.tradeVolume >= 0 and agent.sugarPrice >= 0 and
      agent.spicePrice >= 0 and agent.lastTradePartners >= 0 and
      agent.diseaseProtectionChance >= 0 and agent.diseaseProtectionChance <= 1,
      "agent trade and disease fields are invalid"
    doAssert agent.born >= 0 and agent.startingSugar >= 0 and agent.startingSpice >= 0 and
      (not agent.hasSex or agent.sex in ["female", "male"]) and agent.fertilityAge >= 0 and
      agent.infertilityAge >= agent.fertilityAge and agent.inheritancePolicy in ["none", "children"] and
      agent.lendingFactor >= 0 and agent.baseInterestRate >= 0 and agent.loanDuration >= 0 and
      agent.sugarMeanIncome >= 0 and agent.spiceMeanIncome >= 0 and agent.lastMates >= 0 and
      agent.lastLoans >= 0, "invalid reproduction or lending agent state"
    for field in ["childrenIds", "mateIds"]:
      doAssert agentNode[field].kind == JArray, field & " must be an array"
      for idNode in agentNode[field].items:
        let relationId = idNode.getBiggestInt()
        if field == "childrenIds":
          doAssert relationId >= 0 and relationId notin agent.childrenIds,
            "childrenIds must contain unique nonnegative IDs"
          agent.childrenIds.add(relationId)
        else:
          doAssert relationId >= 0 and relationId notin agent.mateIds,
            "mateIds must contain unique nonnegative IDs"
          agent.mateIds.add(relationId)
    for field in ["creditorLoans", "debtorLoans"]:
      doAssert agentNode[field].kind == JArray, field & " must be an array"
      for loanNode in agentNode[field].items:
        loanNode.requireFields(["creditorId", "debtorId", "sugarLoan", "spiceLoan",
          "loanDuration", "loanOrigin"], "loan")
        let loan = Loan(
          creditorId: loanNode.readInt("creditorId"), debtorId: loanNode.readInt("debtorId"),
          sugarLoan: loanNode.readNumber("sugarLoan"), spiceLoan: loanNode.readNumber("spiceLoan"),
          duration: loanNode.readInt("loanDuration"), origin: loanNode.readInt("loanOrigin"),
        )
        doAssert loan.creditorId >= 0 and loan.debtorId >= 0 and loan.sugarLoan >= 0 and
          loan.spiceLoan >= 0 and loan.duration >= 1 and loan.origin >= 0, "invalid loan"
        if field == "creditorLoans": agent.creditorLoans.add(loan)
        else: agent.debtorLoans.add(loan)
    if agent.hasStartingImmuneSystem:
      doAssert agentNode["startingImmuneSystem"].kind == JArray,
        "startingImmuneSystem must be null or a bit array"
      for bitNode in agentNode["startingImmuneSystem"].items:
        let bit = bitNode.getInt()
        doAssert bit in [0, 1], "startingImmuneSystem must contain only 0 or 1"
        agent.startingImmuneSystem.add(bit)
    if agent.hasRacialTags:
      doAssert agentNode["racialTags"].kind == JArray, "racialTags must be null or an array"
      for tagNode in agentNode["racialTags"].items:
        let tag = tagNode.getInt()
        doAssert tag >= 0, "racialTags must be nonnegative integers"
        agent.racialTags.add(tag)
    if agent.hasImmuneSystem:
      doAssert agentNode["immuneSystem"].kind == JArray, "immuneSystem must be null or a bit array"
      for bitNode in agentNode["immuneSystem"].items:
        let bit = bitNode.getInt()
        doAssert bit in [0, 1], "immuneSystem must contain only 0 or 1"
        agent.immuneSystem.add(bit)
    doAssert agent.hasStartingImmuneSystem == agent.hasImmuneSystem and
      (not agent.hasImmuneSystem or agent.startingImmuneSystem.len == agent.immuneSystem.len),
      "starting and current immune systems must have matching shape"
    doAssert agentNode["diseases"].kind == JArray, "agent diseases must be an array"
    for infectionNode in agentNode["diseases"].items:
      infectionNode.requireFields(["diseaseId", "startIndex", "endIndex", "infectorId", "caught", "incubation"], "infection")
      let hasRange = infectionNode["startIndex"].kind != JNull
      doAssert hasRange == (infectionNode["endIndex"].kind != JNull),
        "infection range indices must both be null or integers"
      let infector = if infectionNode["infectorId"].kind == JNull: EmptyOccupant else: infectionNode.readInt("infectorId")
      let infection = Infection(
        diseaseId: int(infectionNode.readInt("diseaseId")), hasRange: hasRange,
        startIndex: (if hasRange: int(infectionNode.readInt("startIndex")) else: -1),
        endIndex: (if hasRange: int(infectionNode.readInt("endIndex")) else: -1),
        infectorId: infector, caught: infectionNode.readInt("caught"),
        incubation: int(infectionNode.readInt("incubation")),
      )
      doAssert infection.diseaseId >= 0 and infection.caught >= 0 and infection.incubation >= 0,
        "infection fields must be nonnegative"
      agent.diseases.add(infection)
    doAssert agent.maxAge >= -1, "agent maxAge must be -1 or nonnegative"
    if agent.hasTags:
      doAssert agentNode["tags"].kind == JArray and agentNode["tags"].len > 0,
        "agent tags must be null or a nonempty array"
      for tagNode in agentNode["tags"].items:
        let tag = tagNode.getInt()
        doAssert tag in [0, 1], "agent tags must contain only 0 or 1"
        agent.tags.add(tag)
      let zeroes = agent.tags.count(0)
      let tribeSize = float64(agent.tags.len + 1) / float64(result.maxTribes)
      let expectedTribe = min(int(ceil(float64(zeroes + 1) / tribeSize)) - 1,
        result.maxTribes - 1)
      doAssert agent.tribe == expectedTribe, "agent tribe is inconsistent with tags"
    else:
      doAssert agent.tribe == -1, "agent tribe must be null when tags are null"
      doAssert not agent.tagging, "tagging requires nonempty tags"
    previousId = agent.id
    agentIds.add(agent.id)
    result.agents.add(agent)

  var orderedIds = result.liveOrder
  orderedIds.sort()
  doAssert orderedIds == agentIds, "liveOrder must contain every agent id exactly once"
  doAssert agentIds.len == 0 or result.nextAgentId > agentIds[^1],
    "nextAgentId must exceed every living agent id"
  doAssert node["creditorTombstones"].kind == JArray,
    "creditorTombstones must be an array"
  var previousTombstoneId = EmptyOccupant
  for tombstoneNode in node["creditorTombstones"].items:
    tombstoneNode.requireFields(["id", "inheritancePolicy", "childrenIds"],
      "creditor tombstone")
    var tombstone = CreditorTombstone(
      id: tombstoneNode.readInt("id"),
      inheritancePolicy: tombstoneNode["inheritancePolicy"].getStr(),
    )
    doAssert tombstone.id >= 0 and tombstone.id > previousTombstoneId and
      tombstone.id notin agentIds, "creditor tombstones must have sorted unique dead IDs"
    doAssert tombstone.inheritancePolicy in ["none", "children"],
      "invalid creditor tombstone inheritancePolicy"
    doAssert tombstoneNode["childrenIds"].kind == JArray,
      "creditor tombstone childrenIds must be an array"
    for childNode in tombstoneNode["childrenIds"].items:
      let childId = childNode.getBiggestInt()
      doAssert childId >= 0 and childId notin tombstone.childrenIds,
        "creditor tombstone childrenIds must be unique nonnegative IDs"
      tombstone.childrenIds.add(childId)
    result.creditorTombstones.add(tombstone)
    previousTombstoneId = tombstone.id
  doAssert result.creditorTombstones.len == 0 or
    result.nextAgentId > result.creditorTombstones[^1].id,
    "nextAgentId must exceed every creditor tombstone ID"
  let taggingEnabled = result.agents.anyIt(it.tagging)
  var liveCreditorRecords = newSeq[Loan]()
  var liveDebtorRecords = newSeq[Loan]()
  for agent in result.agents:
    doAssert not taggingEnabled or agent.hasTags,
      "every agent must have tags when tagging is enabled"
    doAssert max(0.0, agent.aggressionFactor + agent.aggressionFactorModifier) == 0 or
      agent.hasTags, "combat requires agent tags and tribes"
    for loan in agent.creditorLoans:
      doAssert loan.debtorId == agent.id, "loan debtorId must match its owner"
      if loan.creditorId in agentIds:
        liveCreditorRecords.add(loan)
      else:
        doAssert result.creditorTombstones.anyIt(it.id == loan.creditorId),
          "missing creditor requires a creditor tombstone"
    for loan in agent.debtorLoans:
      doAssert loan.creditorId == agent.id, "loan creditorId must match its owner"
      if loan.debtorId in agentIds:
        liveDebtorRecords.add(loan)
  for loan in liveCreditorRecords:
    doAssert liveCreditorRecords.count(loan) == liveDebtorRecords.count(loan),
      "live creditor and debtor loan records must be mirrored with equal multiplicity"
  for loan in liveDebtorRecords:
    doAssert liveDebtorRecords.count(loan) == liveCreditorRecords.count(loan),
      "live creditor and debtor loan records must be mirrored with equal multiplicity"
  for tombstone in result.creditorTombstones:
    doAssert result.agents.anyIt(it.creditorLoans.anyIt(it.creditorId == tombstone.id)),
      "creditor tombstone must be referenced by a living debtor"
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

  doAssert node["orderedNeighbors"].kind == JArray and
    node["orderedNeighbors"].len == result.cells.len,
    "orderedNeighbors must contain one array per cell"
  for neighborsNode in node["orderedNeighbors"].items:
    doAssert neighborsNode.kind == JArray, "orderedNeighbors entries must be arrays"
    var neighbors = newSeq[int]()
    for neighborNode in neighborsNode.items:
      let neighbor = neighborNode.getInt()
      doAssert neighbor >= 0 and neighbor < result.cells.len,
        "ordered neighbor index is invalid"
      neighbors.add(neighbor)
    result.orderedNeighbors.add(neighbors)

  doAssert node["diseases"].kind == JArray, "diseases must be an array"
  var previousDiseaseId = -1
  for diseaseNode in node["diseases"].items:
    diseaseNode.requireFields(["id", "aggressionPenalty", "fertilityPenalty", "friendlinessPenalty",
      "happinessPenalty", "incubationPeriod", "movementPenalty", "spiceMetabolismPenalty",
      "startTimestep", "sugarMetabolismPenalty", "tags", "transmissionChance", "visionPenalty",
      "recoverable", "infectedIds"], "disease")
    var disease = Disease(
      id: int(diseaseNode.readInt("id")), aggressionPenalty: diseaseNode.readNumber("aggressionPenalty"),
      fertilityPenalty: diseaseNode.readNumber("fertilityPenalty"),
      friendlinessPenalty: diseaseNode.readNumber("friendlinessPenalty"),
      happinessPenalty: diseaseNode.readNumber("happinessPenalty"),
      incubationPeriod: int(diseaseNode.readInt("incubationPeriod")),
      movementPenalty: int(diseaseNode.readInt("movementPenalty")),
      spiceMetabolismPenalty: diseaseNode.readNumber("spiceMetabolismPenalty"),
      startTimestep: diseaseNode.readInt("startTimestep"),
      sugarMetabolismPenalty: diseaseNode.readNumber("sugarMetabolismPenalty"),
      hasTags: diseaseNode["tags"].kind != JNull,
      transmissionChance: diseaseNode.readNumber("transmissionChance"),
      visionPenalty: int(diseaseNode.readInt("visionPenalty")),
      recoverable: diseaseNode["recoverable"].getBool(),
    )
    doAssert disease.id > previousDiseaseId and disease.incubationPeriod >= 0 and
      disease.startTimestep >= 0 and disease.transmissionChance >= 0 and disease.transmissionChance <= 1,
      "invalid disease definition"
    if disease.hasTags:
      doAssert diseaseNode["tags"].kind == JArray, "disease tags must be null or a bit array"
      for bitNode in diseaseNode["tags"].items:
        let bit = bitNode.getInt()
        doAssert bit in [0, 1], "disease tags must contain only 0 or 1"
        disease.tags.add(bit)
    doAssert diseaseNode["infectedIds"].kind == JArray, "infectedIds must be an array"
    for idNode in diseaseNode["infectedIds"].items:
      let infectedId = idNode.getBiggestInt()
      doAssert infectedId >= 0 and infectedId notin disease.infectedIds,
        "disease infectedIds must be unique nonnegative integers"
      disease.infectedIds.add(infectedId)
    result.diseases.add(disease)
    previousDiseaseId = disease.id
  doAssert node["remainingDiseaseIds"].kind == JArray, "remainingDiseaseIds must be an array"
  for idNode in node["remainingDiseaseIds"].items:
    result.remainingDiseaseIds.add(idNode.getInt())
  doAssert result.remainingDiseaseIds.len == 0, "scheduled disease introduction is unsupported"
  for agent in result.agents:
    var infectionIds = newSeq[int]()
    for infection in agent.diseases:
      let definitionIndex = diseaseIndex(result.diseases, infection.diseaseId)
      doAssert definitionIndex >= 0, "infection names an unknown disease"
      doAssert infection.diseaseId notin infectionIds, "agent disease IDs must be unique"
      if infection.hasRange:
        doAssert result.diseases[definitionIndex].hasTags and agent.hasImmuneSystem and
          infection.startIndex >= 0 and infection.endIndex >= infection.startIndex and
          infection.endIndex < agent.immuneSystem.len and
          infection.endIndex - infection.startIndex + 1 == result.diseases[definitionIndex].tags.len,
          "infection immune range must exactly match disease tags"
      else:
        doAssert not result.diseases[definitionIndex].hasTags, "tagged disease requires an immune range"
      infectionIds.add(infection.diseaseId)
  for disease in result.diseases:
    var recorded = newSeq[int64]()
    for agent in result.agents:
      if agent.diseases.anyIt(it.diseaseId == disease.id): recorded.add(agent.id)
    var declared = disease.infectedIds
    recorded.sort()
    declared.sort()
    doAssert declared == recorded, "disease infectedIds must match agent infection records"

  doAssert node["deaths"].kind == JArray, "deaths must be an array"
  for deathNode in node["deaths"].items:
    deathNode.requireFields(["id", "seat", "age", "cause"], "death")
    let death = Death(
      id: deathNode.readInt("id"),
      seat: int(deathNode.readInt("seat")),
      age: deathNode.readInt("age"),
      cause: deathNode["cause"].getStr(),
    )
    doAssert death.id >= 0 and death.id notin agentIds,
      "death id must not name a living agent"
    doAssert death.seat >= 0 and death.age >= 0, "death seat and age must be nonnegative"
    doAssert death.cause in ["starvation", "aging", "combat"], "unsupported death cause"
    for previous in result.deaths:
      doAssert previous.id != death.id, "death ids must be unique"
    result.deaths.add(death)

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
      "spice": cell.spice,
      "maxSpice": cell.maxSpice,
      "occupantId": (if cell.occupantId == EmptyOccupant: newJNull() else: %cell.occupantId),
    })
  var agents = newJArray()
  for agent in world.agents:
    agents.add(%*{
      "id": agent.id, "seat": agent.seat, "x": agent.x, "y": agent.y,
      "sugar": agent.sugar, "spice": agent.spice, "age": agent.age,
      "sugarMetabolism": agent.sugarMetabolism, "spiceMetabolism": agent.spiceMetabolism,
      "sugarMetabolismModifier": agent.sugarMetabolismModifier,
      "spiceMetabolismModifier": agent.spiceMetabolismModifier,
      "vision": agent.vision, "movement": agent.movement,
      "visionModifier": agent.visionModifier, "movementModifier": agent.movementModifier,
      "aggressionFactor": agent.aggressionFactor,
      "aggressionFactorModifier": agent.aggressionFactorModifier,
      "fertilityFactor": agent.fertilityFactor,
      "fertilityFactorModifier": agent.fertilityFactorModifier,
      "depressed": agent.depressed, "happinessUnit": agent.happinessUnit,
      "maxFriends": agent.maxFriends, "friendlinessModifier": agent.friendlinessModifier,
      "happinessModifier": agent.happinessModifier,
      "tags": (if agent.hasTags: %agent.tags else: newJNull()),
      "tribe": (if agent.hasTags: %agent.tribe else: newJNull()),
      "tagging": agent.tagging,
      "maxAge": agent.maxAge,
      "lookaheadFactor": agent.lookaheadFactor,
      "tradeFactor": agent.tradeFactor,
      "marginalRateOfSubstitution": agent.marginalRateOfSubstitution,
      "tradeVolume": agent.tradeVolume, "sugarPrice": agent.sugarPrice,
      "spicePrice": agent.spicePrice, "lastTradeTimestep": agent.lastTradeTimestep,
      "lastTradePartners": agent.lastTradePartners,
      "diseaseProtectionChance": agent.diseaseProtectionChance,
      "immuneSystem": (if agent.hasImmuneSystem: %agent.immuneSystem else: newJNull()),
      "diseases": block:
        var infections = newJArray()
        for infection in agent.diseases:
          infections.add(%*{
            "diseaseId": infection.diseaseId,
            "startIndex": (if infection.hasRange: %infection.startIndex else: newJNull()),
            "endIndex": (if infection.hasRange: %infection.endIndex else: newJNull()),
            "infectorId": (if infection.infectorId == EmptyOccupant: newJNull() else: %infection.infectorId),
            "caught": infection.caught, "incubation": infection.incubation,
          })
        infections,
      "born": agent.born, "startingSugar": agent.startingSugar,
      "startingSpice": agent.startingSpice,
      "sex": (if agent.hasSex: %agent.sex else: newJNull()),
      "fertilityAge": agent.fertilityAge, "infertilityAge": agent.infertilityAge,
      "inheritancePolicy": agent.inheritancePolicy, "lendingFactor": agent.lendingFactor,
      "baseInterestRate": agent.baseInterestRate, "loanDuration": agent.loanDuration,
      "sugarMeanIncome": agent.sugarMeanIncome, "spiceMeanIncome": agent.spiceMeanIncome,
      "startingImmuneSystem": (if agent.hasStartingImmuneSystem: %agent.startingImmuneSystem else: newJNull()),
      "racialTags": (if agent.hasRacialTags: %agent.racialTags else: newJNull()),
      "fatherId": (if agent.fatherId == EmptyOccupant: newJNull() else: %agent.fatherId),
      "motherId": (if agent.motherId == EmptyOccupant: newJNull() else: %agent.motherId),
      "childrenIds": agent.childrenIds, "mateIds": agent.mateIds,
      "lastMovedTimestep": agent.lastMovedTimestep,
      "lastReproducedTimestep": agent.lastReproducedTimestep, "lastMates": agent.lastMates,
      "lastLendedTimestep": agent.lastLendedTimestep, "lastLoans": agent.lastLoans,
      "creditorLoans": block:
        var values = newJArray()
        for loan in agent.creditorLoans:
          values.add(%*{"creditorId": loan.creditorId, "debtorId": loan.debtorId,
            "sugarLoan": loan.sugarLoan, "spiceLoan": loan.spiceLoan,
            "loanDuration": loan.duration, "loanOrigin": loan.origin})
        values,
      "debtorLoans": block:
        var values = newJArray()
        for loan in agent.debtorLoans:
          values.add(%*{"creditorId": loan.creditorId, "debtorId": loan.debtorId,
            "sugarLoan": loan.sugarLoan, "spiceLoan": loan.spiceLoan,
            "loanDuration": loan.duration, "loanOrigin": loan.origin})
        values,
    })
  var orderedCandidates = newJArray()
  for candidates in world.orderedCandidates:
    var entries = newJArray()
    for candidate in candidates:
      entries.add(%*[candidate.target, candidate.distance])
    orderedCandidates.add(entries)
  var deaths = newJArray()
  for death in world.deaths:
    deaths.add(%*{"id": death.id, "seat": death.seat, "age": death.age, "cause": death.cause})
  var orderedNeighbors = newJArray()
  for neighbors in world.orderedNeighbors:
    orderedNeighbors.add(%neighbors)
  var rulesetSha256 = newJArray()
  for digest in world.rulesetSha256:
    rulesetSha256.add(%digest)
  var diseases = newJArray()
  for disease in world.diseases:
    diseases.add(%*{
      "id": disease.id, "aggressionPenalty": disease.aggressionPenalty,
      "fertilityPenalty": disease.fertilityPenalty,
      "friendlinessPenalty": disease.friendlinessPenalty,
      "happinessPenalty": disease.happinessPenalty,
      "incubationPeriod": disease.incubationPeriod,
      "movementPenalty": disease.movementPenalty,
      "spiceMetabolismPenalty": disease.spiceMetabolismPenalty,
      "startTimestep": disease.startTimestep,
      "sugarMetabolismPenalty": disease.sugarMetabolismPenalty,
      "tags": (if disease.hasTags: %disease.tags else: newJNull()),
      "transmissionChance": disease.transmissionChance,
      "visionPenalty": disease.visionPenalty, "recoverable": disease.recoverable,
      "infectedIds": disease.infectedIds,
    })
  var creditorTombstones = newJArray()
  for tombstone in world.creditorTombstones:
    creditorTombstones.add(%*{
      "id": tombstone.id, "inheritancePolicy": tombstone.inheritancePolicy,
      "childrenIds": tombstone.childrenIds,
    })
  %*{
    "schemaVersion": SchemaVersion, "sourcePin": world.sourcePin,
    "configurationSha256": world.configurationSha256, "rulesetSha256": rulesetSha256,
    "timestep": world.timestep,
    "width": world.width, "height": world.height, "sugarRegrowRate": world.sugarRegrowRate,
    "spiceRegrowRate": world.spiceRegrowRate,
    "maxCellDistance": world.maxCellDistance, "maxCombatLoot": world.maxCombatLoot,
    "maxTribes": world.maxTribes, "inheritancePolicy": world.inheritancePolicy,
    "nextAgentId": world.nextAgentId, "depressionPercentage": world.depressionPercentage,
    "rng": rngJson(world.rng),
    "liveOrder": liveOrder, "cells": cells, "agents": agents,
    "orderedCandidates": orderedCandidates, "orderedNeighbors": orderedNeighbors,
    "diseases": diseases, "remainingDiseaseIds": world.remainingDiseaseIds,
    "creditorTombstones": creditorTombstones,
    "deaths": deaths,
  }

proc welfare(agent: Agent, cell: Cell, sugarReward, spiceReward,
    sugarMetabolism, spiceMetabolism: float64): float64 =
  let totalMetabolism = sugarMetabolism + spiceMetabolism
  let sugarProportion = if totalMetabolism == 0: 0.0 else: sugarMetabolism / totalMetabolism
  let spiceProportion = if totalMetabolism == 0: 0.0 else: spiceMetabolism / totalMetabolism
  let adjustedSugar = max(agent.sugar + cell.sugar + sugarReward -
    sugarMetabolism * agent.lookaheadFactor, 0.0)
  let adjustedSpice = max(agent.spice + cell.spice + spiceReward -
    spiceMetabolism * agent.lookaheadFactor, 0.0)
  let computed = pow(adjustedSugar, sugarProportion) * pow(adjustedSpice, spiceProportion)
  if computed.classify in {fcNan, fcInf, fcNegInf}: 0.0 else: computed

proc recomputeTribe(world: World, agent: var Agent) =
  let zeroes = agent.tags.count(0)
  let tribeSize = float64(agent.tags.len + 1) / float64(world.maxTribes)
  agent.tribe = min(int(ceil(float64(zeroes + 1) / tribeSize)) - 1,
    world.maxTribes - 1)

proc effectiveSugarMetabolism(agent: Agent): float64 =
  max(0.0, agent.sugarMetabolism + agent.sugarMetabolismModifier)

proc effectiveSpiceMetabolism(agent: Agent): float64 =
  max(0.0, agent.spiceMetabolism + agent.spiceMetabolismModifier)

proc roundedMultiply(left, right: float64): float64 {.noinline.} =
  left * right

proc updateMeanIncome(previous, collected: float64): float64 =
  let alpha = 0.05
  roundedMultiply(alpha, collected) + roundedMultiply(1 - alpha, previous)

proc marginalRate(agent: Agent): float64 =
  let spiceMetabolism = agent.effectiveSpiceMetabolism()
  let sugarMetabolism = agent.effectiveSugarMetabolism()
  let spiceNeed = if spiceMetabolism > 0: agent.spice / spiceMetabolism else: 1.0
  let sugarNeed = if sugarMetabolism > 0: agent.sugar / sugarMetabolism else: 1.0
  agent.tradeFactor * (spiceNeed / sugarNeed)

proc newMarginalRate(agent: Agent, sugar, spice: float64): float64 =
  let spiceMetabolism = agent.effectiveSpiceMetabolism()
  let sugarMetabolism = agent.effectiveSugarMetabolism()
  let spiceNeed = if spiceMetabolism > 0: spice / spiceMetabolism else: 1.0
  let sugarNeed = if sugarMetabolism > 0: sugar / sugarMetabolism else: 1.0
  if spiceNeed == 1 and sugarNeed == 1: return 1
  if spiceNeed == 0: return spiceMetabolism
  if sugarNeed == 0: return 1 / sugarMetabolism
  spiceNeed / sugarNeed

proc welfareRewards(agent: Agent, sugarReward, spiceReward: float64): float64 =
  let sugarMetabolism = agent.effectiveSugarMetabolism()
  let spiceMetabolism = agent.effectiveSpiceMetabolism()
  let totalMetabolism = sugarMetabolism + spiceMetabolism
  let sugarProportion = if totalMetabolism == 0: 0.0 else: sugarMetabolism / totalMetabolism
  let spiceProportion = if totalMetabolism == 0: 0.0 else: spiceMetabolism / totalMetabolism
  pow(max(0.0, agent.sugar + sugarReward - sugarMetabolism * agent.lookaheadFactor), sugarProportion) *
    pow(max(0.0, agent.spice + spiceReward - spiceMetabolism * agent.lookaheadFactor), spiceProportion)

proc trigger(agent: var Agent, disease: Disease) =
  agent.aggressionFactorModifier += disease.aggressionPenalty
  agent.fertilityFactorModifier += disease.fertilityPenalty
  agent.friendlinessModifier += disease.friendlinessPenalty
  agent.happinessModifier += disease.happinessPenalty
  agent.movementModifier += disease.movementPenalty
  agent.spiceMetabolismModifier += disease.spiceMetabolismPenalty
  agent.sugarMetabolismModifier += disease.sugarMetabolismPenalty
  agent.visionModifier += disease.visionPenalty

proc recover(agent: var Agent, disease: Disease) =
  agent.aggressionFactorModifier -= disease.aggressionPenalty
  agent.fertilityFactorModifier -= disease.fertilityPenalty
  agent.friendlinessModifier -= disease.friendlinessPenalty
  agent.happinessModifier -= disease.happinessPenalty
  agent.movementModifier -= disease.movementPenalty
  agent.spiceMetabolismModifier -= disease.spiceMetabolismPenalty
  agent.sugarMetabolismModifier -= disease.sugarMetabolismPenalty
  agent.visionModifier -= disease.visionPenalty

proc nearestImmuneMatch(agent: Agent, disease: Disease): tuple[distance, startIndex, endIndex: int] =
  result = (disease.tags.len, 0, disease.tags.len - 1)
  if not disease.hasTags:
    result.distance = 1
    return
  if not agent.hasImmuneSystem:
    return
  for startIndex in 0 ..< agent.immuneSystem.len - disease.tags.len:
    var distance = 0
    for offset, bit in disease.tags:
      if agent.immuneSystem[startIndex + offset] != bit: inc distance
    if distance < result.distance:
      result = (distance, startIndex, startIndex + disease.tags.len - 1)

proc hasDisease(agent: Agent, diseaseId: int): bool =
  agent.diseases.anyIt(it.diseaseId == diseaseId)

proc catchDisease(world: var World, agentIndex, diseaseId: int, infectorId = EmptyOccupant,
    initial = false): bool =
  if world.agents[agentIndex].hasDisease(diseaseId): return false
  let definitionIndex = diseaseIndex(world.diseases, diseaseId)
  doAssert definitionIndex >= 0, "infection names an unknown disease"
  let disease = world.diseases[definitionIndex]
  let matched = nearestImmuneMatch(world.agents[agentIndex], disease)
  if disease.hasTags and matched.distance == 0: return false
  if not initial:
    let attack = world.rng.randomFloat()
    let defense = world.rng.randomFloat()
    if disease.transmissionChance == 0 or attack > disease.transmissionChance or
        (world.agents[agentIndex].diseaseProtectionChance != 0 and
         defense <= world.agents[agentIndex].diseaseProtectionChance):
      return false
  let caught = if infectorId == EmptyOccupant: world.timestep else: world.timestep
  world.agents[agentIndex].diseases.add(Infection(
    diseaseId: diseaseId, hasRange: disease.hasTags,
    startIndex: matched.startIndex, endIndex: matched.endIndex,
    infectorId: infectorId, caught: caught, incubation: disease.incubationPeriod,
  ))
  world.diseases[definitionIndex].infectedIds.add(world.agents[agentIndex].id)
  if disease.incubationPeriod == 0:
    world.agents[agentIndex].trigger(disease)
  true

proc doTrading(world: var World, id: int64, agentIndexById: Table[int64, int], dead: Table[int64, Death]) =
  let actorIndex = agentIndexById[id]
  if world.agents[actorIndex].tradeFactor == 0: return
  world.agents[actorIndex].tradeVolume = 0
  world.agents[actorIndex].sugarPrice = 0
  world.agents[actorIndex].spicePrice = 0
  world.agents[actorIndex].marginalRateOfSubstitution = marginalRate(world.agents[actorIndex])
  let cell = world.agents[actorIndex].x * world.height + world.agents[actorIndex].y
  var traders = newSeq[int64]()
  for neighborCell in world.orderedNeighbors[cell]:
    let traderId = world.cells[neighborCell].occupantId
    if traderId != EmptyOccupant and not dead.hasKey(traderId) and
        world.agents[agentIndexById[traderId]].marginalRateOfSubstitution !=
        world.agents[actorIndex].marginalRateOfSubstitution:
      traders.add(traderId)
  world.rng.pythonShuffle(traders)
  var partners = newSeq[int64]()
  for traderId in traders:
    let traderIndex = agentIndexById[traderId]
    var spiceSeller = -1
    var sugarSeller = -1
    var sugarPrice = 0.0
    var spicePrice = 0.0
    while true:
      let first = world.agents[actorIndex].marginalRateOfSubstitution
      let second = world.agents[traderIndex].marginalRateOfSubstitution
      if (first >= 1 and second >= 1) or (first < 1 and second < 1) or first == second: break
      if second > first:
        spiceSeller = traderIndex; sugarSeller = actorIndex
      else:
        spiceSeller = actorIndex; sugarSeller = traderIndex
      let spiceMRS = world.agents[spiceSeller].marginalRateOfSubstitution
      let sugarMRS = world.agents[sugarSeller].marginalRateOfSubstitution
      if spiceMRS < 0 or sugarMRS < 0:
        spiceSeller = -1; sugarSeller = -1; break
      let price = sqrt(spiceMRS * sugarMRS)
      if price < 1: spicePrice = 1; sugarPrice = price
      else: spicePrice = price; sugarPrice = 1
      if world.agents[spiceSeller].spice - spicePrice < world.agents[spiceSeller].spiceMetabolism or
          world.agents[sugarSeller].sugar - sugarPrice < world.agents[sugarSeller].sugarMetabolism: break
      let spiceNew = newMarginalRate(world.agents[spiceSeller],
        world.agents[spiceSeller].sugar + sugarPrice, world.agents[spiceSeller].spice - spicePrice)
      let sugarNew = newMarginalRate(world.agents[sugarSeller],
        world.agents[sugarSeller].sugar - sugarPrice, world.agents[sugarSeller].spice + spicePrice)
      let spiceBetter = abs(1 - spiceMRS) > abs(1 - spiceNew) or
        welfareRewards(world.agents[spiceSeller], sugarPrice, -spicePrice) >= welfareRewards(world.agents[spiceSeller], 0, 0)
      let sugarBetter = abs(1 - sugarMRS) > abs(1 - sugarNew) or
        welfareRewards(world.agents[sugarSeller], -sugarPrice, spicePrice) >= welfareRewards(world.agents[sugarSeller], 0, 0)
      if not spiceBetter or not sugarBetter or spiceNew < sugarNew: break
      world.agents[spiceSeller].sugar += sugarPrice
      world.agents[spiceSeller].spice -= spicePrice
      world.agents[sugarSeller].sugar -= sugarPrice
      world.agents[sugarSeller].spice += spicePrice
      world.agents[spiceSeller].marginalRateOfSubstitution = marginalRate(world.agents[spiceSeller])
      world.agents[sugarSeller].marginalRateOfSubstitution = marginalRate(world.agents[sugarSeller])
    if spiceSeller >= 0 and sugarSeller >= 0:
      inc world.agents[actorIndex].tradeVolume
      world.agents[actorIndex].sugarPrice += sugarPrice
      world.agents[actorIndex].spicePrice += spicePrice
      world.agents[actorIndex].lastTradeTimestep = world.timestep
      if traderId notin partners: partners.add(traderId)
  if world.agents[actorIndex].lastTradeTimestep == world.timestep:
    world.agents[actorIndex].lastTradePartners = partners.len

proc doDisease(world: var World, id: int64, agentIndexById: Table[int64, int], dead: Table[int64, Death]) =
  let agentIndex = agentIndexById[id]
  world.rng.pythonShuffle(world.agents[agentIndex].diseases)
  var infectionIndex = 0
  while infectionIndex < world.agents[agentIndex].diseases.len:
    var infection = world.agents[agentIndex].diseases[infectionIndex]
    let definitionIndex = diseaseIndex(world.diseases, infection.diseaseId)
    let disease = world.diseases[definitionIndex]
    if infection.caught != world.timestep and infection.incubation > 0:
      dec infection.incubation
      world.agents[agentIndex].diseases[infectionIndex].incubation = infection.incubation
    if infection.incubation == 0: world.agents[agentIndex].trigger(disease)
    if disease.recoverable and disease.hasTags:
      let responseEnd = min(infection.endIndex + 1, world.agents[agentIndex].immuneSystem.len)
      var responseMatches = true
      for offset in 0 ..< responseEnd - infection.startIndex:
        if world.agents[agentIndex].immuneSystem[infection.startIndex + offset] != disease.tags[offset]:
          world.agents[agentIndex].immuneSystem[infection.startIndex + offset] = disease.tags[offset]
          world.agents[agentIndex].startingImmuneSystem[infection.startIndex + offset] = disease.tags[offset]
          responseMatches = false
          break
      if responseMatches:
        world.agents[agentIndex].recover(disease)
        world.agents[agentIndex].diseases.delete(infectionIndex)
        let infectedIndex = world.diseases[definitionIndex].infectedIds.find(id)
        if infectedIndex >= 0: world.diseases[definitionIndex].infectedIds.delete(infectedIndex)
        inc infectionIndex # Preserve DTL remove-during-iteration skip quirk.
        continue
    inc infectionIndex
  let diseaseCount = world.agents[agentIndex].diseases.len
  if diseaseCount == 0: return
  let cell = world.agents[agentIndex].x * world.height + world.agents[agentIndex].y
  var neighbors = newSeq[int64]()
  for neighborCell in world.orderedNeighbors[cell]:
    let neighborId = world.cells[neighborCell].occupantId
    if neighborId != EmptyOccupant and not dead.hasKey(neighborId): neighbors.add(neighborId)
  world.rng.pythonShuffle(neighbors)
  for neighborId in neighbors:
    let infection = world.agents[agentIndex].diseases[int(world.rng.randBelow(uint64(diseaseCount)))]
    discard world.catchDisease(agentIndexById[neighborId], infection.diseaseId, id)

proc clearDiseasesOnDeath(world: var World, agentIndex: int) =
  let id = world.agents[agentIndex].id
  for infection in world.agents[agentIndex].diseases:
    let definitionIndex = diseaseIndex(world.diseases, infection.diseaseId)
    world.agents[agentIndex].recover(world.diseases[definitionIndex])
    let infectedIndex = world.diseases[definitionIndex].infectedIds.find(id)
    if infectedIndex >= 0: world.diseases[definitionIndex].infectedIds.delete(infectedIndex)
  world.agents[agentIndex].diseases.setLen(0)

proc fertile(agent: Agent): bool =
  agent.sugar >= agent.startingSugar and agent.spice >= agent.startingSpice and
    agent.age >= agent.fertilityAge and agent.age < agent.infertilityAge and
    agent.fertilityFactor + agent.fertilityFactorModifier > 0

proc emptyNeighborCells(world: World, agent: Agent): seq[int] =
  let cell = agent.x * world.height + agent.y
  for neighbor in world.orderedNeighbors[cell]:
    if world.cells[neighbor].occupantId == EmptyOccupant: result.add(neighbor)

proc createChild(world: var World, firstIndex, secondIndex, cell: int): Agent =
  let first = world.agents[firstIndex]
  let second = world.agents[secondIndex]
  let paired = chooseParent(firstIndex, secondIndex, "decisionModel", world.timestep)
  result = world.agents[paired]
  template choose(name: string, field: untyped) =
    result.field = world.agents[chooseParent(firstIndex, secondIndex, name, world.timestep)].field
  choose("aggressionFactor", aggressionFactor)
  choose("baseInterestRate", baseInterestRate)
  choose("diseaseProtectionChance", diseaseProtectionChance)
  choose("fertilityAge", fertilityAge)
  choose("fertilityFactor", fertilityFactor)
  choose("infertilityAge", infertilityAge)
  choose("inheritancePolicy", inheritancePolicy)
  choose("lendingFactor", lendingFactor)
  choose("loanDuration", loanDuration)
  choose("lookaheadFactor", lookaheadFactor)
  choose("maxAge", maxAge)
  choose("maxFriends", maxFriends)
  choose("movement", movement)
  choose("spiceMetabolism", spiceMetabolism)
  choose("sugarMetabolism", sugarMetabolism)
  choose("sex", sex)
  choose("tradeFactor", tradeFactor)
  choose("vision", vision)
  result.startingSugar = first.startingSugar / (first.fertilityFactor * 2) +
    second.startingSugar / (second.fertilityFactor * 2)
  result.startingSpice = first.startingSpice / (first.fertilityFactor * 2) +
    second.startingSpice / (second.fertilityFactor * 2)
  result.sugar = result.startingSugar
  result.spice = result.startingSpice
  var local: PythonMt19937
  local.seedFromMd5("tags", uint64(world.timestep))
  result.tags.setLen(0)
  result.hasTags = first.hasTags
  if first.hasTags:
    for index, bit in first.tags:
      result.tags.add(if bit == second.tags[index]: bit else: int(local.randBelow(2)))
  local.seedFromMd5("racialTags", uint64(world.timestep))
  result.racialTags.setLen(0)
  result.hasRacialTags = first.hasRacialTags
  if first.hasRacialTags:
    for index, bit in first.racialTags:
      result.racialTags.add(if local.randBelow(2) == 0: bit else: second.racialTags[index])
  result.depressed = local.randomFloat() <= world.depressionPercentage
  local.seedFromMd5("immuneSystem", uint64(world.timestep))
  result.immuneSystem.setLen(0)
  result.hasImmuneSystem = first.hasImmuneSystem
  if first.hasImmuneSystem:
    for index, bit in first.startingImmuneSystem:
      result.immuneSystem.add(if bit == second.startingImmuneSystem[index]: bit else: int(local.randBelow(2)))
  result.startingImmuneSystem = result.immuneSystem
  result.hasStartingImmuneSystem = result.hasImmuneSystem
  result.id = world.nextAgentId
  inc world.nextAgentId
  result.seat = if world.rng.randomFloat() < 0.5: first.seat else: second.seat
  result.born = world.timestep
  result.x = cell div world.height
  result.y = cell mod world.height
  result.age = 0
  result.fatherId = if first.sex == "male": first.id else: second.id
  result.motherId = if first.sex == "female": first.id else: second.id
  result.childrenIds = @[]
  result.mateIds = @[]
  result.diseases = @[]
  result.creditorLoans = @[]
  result.debtorLoans = @[]
  result.fertilityFactorModifier = 0
  result.aggressionFactorModifier = 0
  result.friendlinessModifier = 0
  result.happinessModifier = 0
  result.movementModifier = 0
  result.visionModifier = 0
  result.sugarMetabolismModifier = 0
  result.spiceMetabolismModifier = 0
  result.happinessUnit = 1
  result.marginalRateOfSubstitution = 1
  result.tradeVolume = 0
  result.sugarPrice = 0
  result.spicePrice = 0
  result.lastMovedTimestep = world.timestep
  result.lastTradeTimestep = -1
  result.lastTradePartners = 0
  result.lastReproducedTimestep = -1
  result.lastMates = 0
  result.lastLendedTimestep = -1
  result.lastLoans = 0
  result.sugarMeanIncome = 1
  result.spiceMeanIncome = 1
  if result.depressed:
    result.aggressionFactor *= 1.145
    result.maxFriends = int(ceil(float64(result.maxFriends) * 0.6333))
    result.happinessUnit *= 0.5763
    result.movement *= int(ceil(float64(result.movement) * 0.429))
    result.spiceMetabolism *= ceil(result.spiceMetabolism * 1.544)
    result.sugarMetabolism *= ceil(result.sugarMetabolism * 1.544)
  if result.hasTags: world.recomputeTribe(result)
  let sugarCollected = world.cells[cell].sugar
  let spiceCollected = world.cells[cell].spice
  result.sugar += sugarCollected
  result.spice += spiceCollected
  result.sugarMeanIncome = updateMeanIncome(result.sugarMeanIncome, sugarCollected)
  result.spiceMeanIncome = updateMeanIncome(result.spiceMeanIncome, spiceCollected)
  world.cells[cell].sugar = 0
  world.cells[cell].spice = 0
  world.cells[cell].occupantId = result.id

proc doReproduction(world: var World, id: int64, agentIndexById: var Table[int64, int],
    dead: Table[int64, Death]) =
  let actorIndex = agentIndexById[id]
  if not world.agents[actorIndex].fertile(): return
  let origin = world.agents[actorIndex].x * world.height + world.agents[actorIndex].y
  var neighborCells = world.orderedNeighbors[origin]
  world.rng.pythonShuffle(neighborCells)
  let ownEmpty = world.emptyNeighborCells(world.agents[actorIndex])
  var timestepMates = newSeq[int64]()
  for neighborCell in neighborCells:
    let mateId = world.cells[neighborCell].occupantId
    if mateId == EmptyOccupant or dead.hasKey(mateId): continue
    let mateIndex = agentIndexById[mateId]
    let compatible = world.agents[actorIndex].hasSex and world.agents[mateIndex].hasSex and
      world.agents[mateIndex].fertile() and
      world.agents[actorIndex].sex != world.agents[mateIndex].sex
    var emptyCells = ownEmpty & world.emptyNeighborCells(world.agents[mateIndex])
    world.rng.pythonShuffle(emptyCells)
    if not world.agents[actorIndex].fertile() or not compatible or emptyCells.len == 0: continue
    var childCell = emptyCells.pop()
    while world.cells[childCell].occupantId != EmptyOccupant and emptyCells.len > 0:
      childCell = emptyCells.pop()
    if world.cells[childCell].occupantId != EmptyOccupant: continue
    if mateId notin world.agents[actorIndex].mateIds: world.agents[actorIndex].mateIds.add(mateId)
    let child = world.createChild(actorIndex, mateIndex, childCell)
    world.agents[actorIndex].childrenIds.add(child.id)
    world.agents[actorIndex].sugar -= world.agents[actorIndex].startingSugar /
      (world.agents[actorIndex].fertilityFactor * 2)
    world.agents[actorIndex].spice -= world.agents[actorIndex].startingSpice /
      (world.agents[actorIndex].fertilityFactor * 2)
    world.agents[mateIndex].sugar -= world.agents[mateIndex].startingSugar /
      (world.agents[mateIndex].fertilityFactor * 2)
    world.agents[mateIndex].spice -= world.agents[mateIndex].startingSpice /
      (world.agents[mateIndex].fertilityFactor * 2)
    world.agents[actorIndex].lastReproducedTimestep = world.timestep
    if mateId notin timestepMates: timestepMates.add(mateId)
    agentIndexById[child.id] = world.agents.len
    world.agents.add(child)
    world.liveOrder.add(child.id)
  world.agents[actorIndex].lastMates = timestepMates.len

proc removeLoan(values: var seq[Loan], loan: Loan) =
  for index, value in values:
    if value == loan:
      values.delete(index)
      return

proc addLoan(world: var World, creditorIndex, debtorIndex: int, origin: int64,
    sugarPrincipal, sugarLoan, spicePrincipal, spiceLoan: float64, duration: int64) =
  let loan = Loan(
    creditorId: world.agents[creditorIndex].id, debtorId: world.agents[debtorIndex].id,
    sugarLoan: sugarLoan, spiceLoan: spiceLoan, duration: duration, origin: origin,
  )
  world.agents[creditorIndex].debtorLoans.add(loan)
  world.agents[debtorIndex].creditorLoans.add(loan)
  world.agents[creditorIndex].sugar -= sugarPrincipal
  world.agents[creditorIndex].spice -= spicePrincipal
  world.agents[debtorIndex].sugar += sugarPrincipal
  world.agents[debtorIndex].spice += spicePrincipal

proc currentDebt(agent: Agent, sugar: bool): float64 =
  for loan in agent.creditorLoans:
    if loan.duration != 0:
      result += (if sugar: loan.sugarLoan else: loan.spiceLoan) / float64(loan.duration)

proc creditWorthy(agent: Agent, sugarLoan, spiceLoan: float64, duration: int64): bool =
  if duration == 0: return false
  agent.sugarMeanIncome - agent.effectiveSugarMetabolism() - agent.currentDebt(true) -
      sugarLoan / float64(duration) >= 0 and
    agent.spiceMeanIncome - agent.effectiveSpiceMetabolism() - agent.currentDebt(false) -
      spiceLoan / float64(duration) >= 0

proc payDebt(world: var World, debtorIndex, loanIndex: int,
    agentIndexById: Table[int64, int], dead: Table[int64, Death]) =
  let loan = world.agents[debtorIndex].creditorLoans[loanIndex]
  if not agentIndexById.hasKey(loan.creditorId):
    let tombstoneIndex = world.creditorTombstones.findIt(it.id == loan.creditorId)
    doAssert tombstoneIndex >= 0, "missing creditor requires a creditor tombstone"
    let tombstone = world.creditorTombstones[tombstoneIndex]
    if tombstone.inheritancePolicy == "children":
      var heirs = newSeq[int]()
      for childId in tombstone.childrenIds:
        if childId != world.agents[debtorIndex].id and agentIndexById.hasKey(childId) and
            not dead.hasKey(childId):
          heirs.add(agentIndexById[childId])
      if heirs.len > 0:
        for heir in heirs:
          world.addLoan(heir, debtorIndex, world.agents[debtorIndex].lastMovedTimestep,
            0, loan.sugarLoan / float64(heirs.len), 0,
            loan.spiceLoan / float64(heirs.len), 1)
    world.agents[debtorIndex].creditorLoans.delete(loanIndex)
    return
  let creditorIndex = agentIndexById[loan.creditorId]
  if dead.hasKey(loan.creditorId):
    # Canonical v7 supports children inheritance only while the creditor remains in this tick.
    if world.agents[creditorIndex].inheritancePolicy == "children":
      var heirs = newSeq[int]()
      for childId in world.agents[creditorIndex].childrenIds:
        if childId != world.agents[debtorIndex].id and agentIndexById.hasKey(childId) and
            not dead.hasKey(childId): heirs.add(agentIndexById[childId])
      if heirs.len > 0:
        for heir in heirs:
          world.addLoan(heir, debtorIndex, world.agents[debtorIndex].lastMovedTimestep,
            0, loan.sugarLoan / float64(heirs.len), 0,
            loan.spiceLoan / float64(heirs.len), 1)
    world.agents[debtorIndex].creditorLoans.delete(loanIndex)
    world.agents[creditorIndex].debtorLoans.removeLoan(loan)
    return
  if world.agents[debtorIndex].sugar - loan.sugarLoan > 0 and
      world.agents[debtorIndex].spice - loan.spiceLoan > 0:
    world.agents[debtorIndex].sugar -= loan.sugarLoan
    world.agents[debtorIndex].spice -= loan.spiceLoan
    world.agents[creditorIndex].sugar += loan.sugarLoan
    world.agents[creditorIndex].spice += loan.spiceLoan
    world.agents[debtorIndex].creditorLoans.delete(loanIndex)
    world.agents[creditorIndex].debtorLoans.removeLoan(loan)
    return
  let sugarPayout = world.agents[debtorIndex].sugar / 2
  let spicePayout = world.agents[debtorIndex].spice / 2
  let sugarLeft = loan.sugarLoan - sugarPayout
  let spiceLeft = loan.spiceLoan - spicePayout
  world.agents[debtorIndex].sugar -= sugarPayout
  world.agents[debtorIndex].spice -= spicePayout
  world.agents[creditorIndex].sugar += sugarPayout
  world.agents[creditorIndex].spice += spicePayout
  world.agents[debtorIndex].creditorLoans.delete(loanIndex)
  world.agents[creditorIndex].debtorLoans.removeLoan(loan)
  let interest = world.agents[creditorIndex].lendingFactor *
    world.agents[creditorIndex].baseInterestRate
  world.addLoan(creditorIndex, debtorIndex, world.agents[debtorIndex].lastMovedTimestep,
    0, sugarLeft + interest * sugarLeft, 0, spiceLeft + interest * spiceLeft,
    world.agents[creditorIndex].loanDuration)

proc updateLoans(world: var World, agentIndex: int, agentIndexById: Table[int64, int],
    dead: Table[int64, Death]) =
  var index = 0
  while index < world.agents[agentIndex].debtorLoans.len:
    let debtorId = world.agents[agentIndex].debtorLoans[index].debtorId
    if not agentIndexById.hasKey(debtorId) or dead.hasKey(debtorId):
      world.agents[agentIndex].debtorLoans.delete(index)
    inc index # Preserve Python remove-during-iteration skip.
  index = 0
  while index < world.agents[agentIndex].creditorLoans.len:
    let loan = world.agents[agentIndex].creditorLoans[index]
    if world.agents[agentIndex].lastMovedTimestep - loan.origin - loan.duration == 0:
      world.payDebt(agentIndex, index, agentIndexById, dead)
    inc index # Preserve Python remove-during-iteration skip.

proc doLending(world: var World, id: int64, agentIndexById: Table[int64, int],
    dead: Table[int64, Death]) =
  let lenderIndex = agentIndexById[id]
  world.updateLoans(lenderIndex, agentIndexById, dead)
  let lender = world.agents[lenderIndex]
  if lender.lendingFactor == 0 or lender.age < lender.fertilityAge or
      (lender.fertile() and
       (lender.sugar <= lender.startingSugar or lender.spice <= lender.startingSpice)):
    return
  let rate = min(1.0, lender.lendingFactor * lender.baseInterestRate)
  let cell = lender.x * world.height + lender.y
  var borrowers = newSeq[int64]()
  for neighborCell in world.orderedNeighbors[cell]:
    let borrowerId = world.cells[neighborCell].occupantId
    if borrowerId != EmptyOccupant and not dead.hasKey(borrowerId):
      let borrower = world.agents[agentIndexById[borrowerId]]
      if borrower.age >= borrower.fertilityAge and borrower.age < borrower.infertilityAge and
          not borrower.fertile(): borrowers.add(borrowerId)
  world.rng.pythonShuffle(borrowers)
  var loans = 0
  for borrowerId in borrowers:
    let borrowerIndex = agentIndexById[borrowerId]
    var maxSugar = world.agents[lenderIndex].sugar / 2
    var maxSpice = world.agents[lenderIndex].spice / 2
    if world.agents[lenderIndex].fertile():
      maxSugar = max(0.0, world.agents[lenderIndex].sugar - world.agents[lenderIndex].startingSugar)
      maxSpice = max(0.0, world.agents[lenderIndex].spice - world.agents[lenderIndex].startingSpice)
    if maxSugar == 0 and maxSpice == 0: return
    let sugarNeed = max(0.0, world.agents[borrowerIndex].startingSugar - world.agents[borrowerIndex].sugar)
    let spiceNeed = max(0.0, world.agents[borrowerIndex].startingSpice - world.agents[borrowerIndex].spice)
    let sugarPrincipal = min(maxSugar, sugarNeed)
    let spicePrincipal = min(maxSpice, spiceNeed)
    let sugarAmount = sugarPrincipal + sugarPrincipal * rate
    let spiceAmount = spicePrincipal + spicePrincipal * rate
    if (sugarNeed == 0 and spiceNeed == 0) or (sugarAmount == 0 and spiceAmount == 0): continue
    if world.agents[lenderIndex].sugar - sugarPrincipal <= world.agents[lenderIndex].effectiveSugarMetabolism() or
        world.agents[lenderIndex].spice - spicePrincipal <= world.agents[lenderIndex].effectiveSpiceMetabolism(): continue
    if not world.agents[borrowerIndex].creditWorthy(sugarAmount, spiceAmount,
        world.agents[lenderIndex].loanDuration): continue
    world.addLoan(lenderIndex, borrowerIndex, world.agents[lenderIndex].lastMovedTimestep,
      sugarPrincipal, sugarAmount, spicePrincipal, spiceAmount,
      world.agents[lenderIndex].loanDuration)
    inc loans
  if loans > 0:
    world.agents[lenderIndex].lastLendedTimestep = world.timestep
    world.agents[lenderIndex].lastLoans = loans

proc doInheritance(world: var World, agentIndex: int, agentIndexById: Table[int64, int],
    dead: Table[int64, Death]) =
  if world.agents[agentIndex].inheritancePolicy == "none": return
  world.agents[agentIndex].sugar = max(0.0, world.agents[agentIndex].sugar)
  world.agents[agentIndex].spice = max(0.0, world.agents[agentIndex].spice)
  var heirs = newSeq[int]()
  for childId in world.agents[agentIndex].childrenIds:
    if agentIndexById.hasKey(childId) and not dead.hasKey(childId):
      heirs.add(agentIndexById[childId])
  if heirs.len == 0: return
  let sugarShare = world.agents[agentIndex].sugar / float64(heirs.len)
  let spiceShare = world.agents[agentIndex].spice / float64(heirs.len)
  for heir in heirs:
    world.agents[heir].sugar += sugarShare
    world.agents[heir].spice += spiceShare
    world.agents[agentIndex].sugar -= sugarShare
    world.agents[agentIndex].spice -= spiceShare

proc stepOne*(world: var World) =
  world.deaths.setLen(0)
  inc world.timestep
  for cell in world.cells.mitems:
    cell.sugar = min(cell.maxSugar, cell.sugar + world.sugarRegrowRate)
    cell.spice = min(cell.maxSpice, cell.spice + world.spiceRegrowRate)

  world.rng.pythonShuffle(world.liveOrder)
  var agentIndexById = initTable[int64, int]()
  for index, agent in world.agents:
    agentIndexById[agent.id] = index
  var dead = initTable[int64, Death]()

  var turnIndex = 0
  while turnIndex < world.liveOrder.len:
    let id = world.liveOrder[turnIndex]
    if dead.hasKey(id):
      inc turnIndex
      continue
    let agentIndex = agentIndexById[id]
    var agent = world.agents[agentIndex]
    if agent.lastMovedTimestep == world.timestep:
      inc turnIndex
      continue
    let origin = agent.x * world.height + agent.y
    let effectiveVision = max(0, agent.vision + agent.visionModifier)
    let effectiveMovement = max(0, agent.movement + agent.movementModifier)
    let effectiveSugarMetabolism = max(0.0,
      agent.sugarMetabolism + agent.sugarMetabolismModifier)
    let effectiveSpiceMetabolism = max(0.0,
      agent.spiceMetabolism + agent.spiceMetabolismModifier)
    let aggression = max(0.0, agent.aggressionFactor + agent.aggressionFactorModifier)
    let cellRange = min(min(effectiveVision, effectiveMovement), world.maxCellDistance)
    var candidates = newSeq[Candidate]()
    for candidate in world.orderedCandidates[origin]:
      if candidate.distance <= float64(cellRange):
        candidates.add(candidate)
    world.rng.pythonShuffle(candidates)

    var retaliators = initTable[int, float64]()
    for candidate in candidates:
      let occupantId = world.cells[candidate.target].occupantId
      if occupantId != EmptyOccupant and not dead.hasKey(occupantId):
        let occupant = world.agents[agentIndexById[occupantId]]
        let wealth = occupant.sugar + occupant.spice
        if not retaliators.hasKey(occupant.tribe) or retaliators[occupant.tribe] < wealth:
          retaliators[occupant.tribe] = wealth

    var destination = origin
    var bestWelfare = low(float64)
    var bestDistance = high(float64)
    for candidate in candidates:
      let occupantId = world.cells[candidate.target].occupantId
      var sugarReward = 0.0
      var spiceReward = 0.0
      var preyTribe = -1
      if occupantId != EmptyOccupant:
        if dead.hasKey(occupantId):
          continue
        let prey = world.agents[agentIndexById[occupantId]]
        if aggression <= 0 or agent.tribe == prey.tribe or
          agent.sugar + agent.spice < prey.sugar + prey.spice:
          continue
        preyTribe = prey.tribe
        sugarReward = aggression * min(world.maxCombatLoot, prey.sugar)
        spiceReward = aggression * min(world.maxCombatLoot, prey.spice)
      let score = welfare(agent, world.cells[candidate.target], sugarReward, spiceReward,
        effectiveSugarMetabolism, effectiveSpiceMetabolism)
      if occupantId != EmptyOccupant and retaliators[preyTribe] >
          agent.sugar + agent.spice + score:
        continue
      if score > bestWelfare or (score == bestWelfare and candidate.distance < bestDistance):
        destination = candidate.target
        bestWelfare = score
        bestDistance = candidate.distance

    let preyId = world.cells[destination].occupantId
    if destination != origin and preyId != EmptyOccupant:
      let preyIndex = agentIndexById[preyId]
      var prey = world.agents[preyIndex]
      let sugarLoot = min(world.maxCombatLoot, prey.sugar)
      let spiceLoot = min(world.maxCombatLoot, prey.spice)
      agent.sugar += sugarLoot
      agent.spice += spiceLoot
      prey.sugar -= sugarLoot
      prey.spice -= spiceLoot
      world.agents[preyIndex] = prey
      dead[preyId] = Death(id: prey.id, seat: prey.seat, age: prey.age, cause: "combat")
      world.cells[destination].occupantId = EmptyOccupant
      world.doInheritance(preyIndex, agentIndexById, dead)
      world.clearDiseasesOnDeath(preyIndex)
    if destination != origin:
      world.cells[origin].occupantId = EmptyOccupant
      world.cells[destination].occupantId = agent.id
      agent.x = destination div world.height
      agent.y = destination mod world.height

    let sugarCollected = world.cells[destination].sugar
    let spiceCollected = world.cells[destination].spice
    agent.sugar += sugarCollected
    agent.spice += spiceCollected
    agent.sugarMeanIncome = updateMeanIncome(agent.sugarMeanIncome, sugarCollected)
    agent.spiceMeanIncome = updateMeanIncome(agent.spiceMeanIncome, spiceCollected)
    world.cells[destination].sugar = 0
    world.cells[destination].spice = 0
    agent.sugar -= effectiveSugarMetabolism
    agent.spice -= effectiveSpiceMetabolism
    agent.lastMovedTimestep = world.timestep
    var cause = ""
    if agent.sugar < 0 or agent.spice < 0 or
      (effectiveSugarMetabolism > 0 and agent.sugar <= 0) or
      (effectiveSpiceMetabolism > 0 and agent.spice <= 0):
      cause = "starvation"
    else:
      if agent.tagging:
        var neighbors = world.orderedNeighbors[destination]
        world.rng.pythonShuffle(neighbors)
        for neighbor in neighbors:
          let neighborId = world.cells[neighbor].occupantId
          if neighborId != EmptyOccupant and not dead.hasKey(neighborId):
            let position = int(world.rng.randBelow(uint64(agent.tags.len)))
            if neighborId == agent.id:
              agent.tags[position] = agent.tags[position]
              world.recomputeTribe(agent)
            else:
              let neighborIndex = agentIndexById[neighborId]
              var target = world.agents[neighborIndex]
              target.tags[position] = agent.tags[position]
              world.recomputeTribe(target)
              world.agents[neighborIndex] = target
      world.agents[agentIndex] = agent
      world.doTrading(agent.id, agentIndexById, dead)
      world.doReproduction(agent.id, agentIndexById, dead)
      world.doLending(agent.id, agentIndexById, dead)
      world.doDisease(agent.id, agentIndexById, dead)
      agent = world.agents[agentIndex]
      inc agent.age
      if agent.maxAge != -1 and agent.age >= agent.maxAge:
        cause = "aging"
    if cause.len > 0:
      world.cells[destination].occupantId = EmptyOccupant
      dead[agent.id] = Death(id: agent.id, seat: agent.seat, age: agent.age, cause: cause)
    world.agents[agentIndex] = agent
    if cause.len > 0:
      world.doInheritance(agentIndex, agentIndexById, dead)
      world.clearDiseasesOnDeath(agentIndex)
    inc turnIndex

  for id in world.liveOrder:
    if dead.hasKey(id):
      world.deaths.add(dead[id])
  var referencedDeadCreditors = newSeq[int64]()
  for debtor in world.agents:
    if not dead.hasKey(debtor.id):
      for loan in debtor.creditorLoans:
        if (not agentIndexById.hasKey(loan.creditorId) or dead.hasKey(loan.creditorId)) and
            loan.creditorId notin referencedDeadCreditors:
          referencedDeadCreditors.add(loan.creditorId)
  referencedDeadCreditors.sort()
  var retainedTombstones = newSeq[CreditorTombstone]()
  for creditorId in referencedDeadCreditors:
    let priorIndex = world.creditorTombstones.findIt(it.id == creditorId)
    if priorIndex >= 0:
      retainedTombstones.add(world.creditorTombstones[priorIndex])
    else:
      let creditor = world.agents[agentIndexById[creditorId]]
      retainedTombstones.add(CreditorTombstone(
        id: creditor.id, inheritancePolicy: creditor.inheritancePolicy,
        childrenIds: creditor.childrenIds,
      ))
  world.creditorTombstones = retainedTombstones
  if world.deaths.len > 0:
    world.agents.keepItIf(not dead.hasKey(it.id))
    world.liveOrder.keepItIf(not dead.hasKey(it))

proc step*(world: var World, ticks: int): int {.discardable.} =
  doAssert ticks >= 0, "ticks must be nonnegative"
  for _ in 0 ..< ticks:
    if world.liveOrder.len == 0:
      break
    world.stepOne()
    inc result

when isMainModule:
  proc usage(): string =
    "usage: sugarscape-native (step|bench|bench-worker) --ticks N < snapshot.json"

  proc writeLine(node: JsonNode) =
    stdout.write($node & "\n")
    stdout.flushFile()

  let arguments = commandLineParams()
  doAssert arguments.len == 3 and arguments[0] in ["step", "bench", "bench-worker"] and
    arguments[1] == "--ticks", usage()
  let ticks = parseInt(arguments[2])
  if arguments[0] == "bench-worker":
    var snapshotLine: string
    doAssert stdin.readLine(snapshotLine), "bench-worker requires one snapshot line"
    var world = loadWorld(parseJson(snapshotLine))
    writeLine(%*{"phase": "ready"})
    var command: string
    doAssert stdin.readLine(command) and command == "start", "bench-worker expected start"
    let started = getMonoTime()
    let completedTicks = world.step(ticks)
    let elapsedNs = (getMonoTime() - started).inNanoseconds
    writeLine(%*{
      "phase": "finished", "ticks": completedTicks, "elapsedNs": elapsedNs,
    })
    doAssert stdin.readLine(command) and command == "collect", "bench-worker expected collect"
    writeLine(%*{"phase": "result", "snapshot": world.snapshot()})
    quit(0)

  var world = loadWorld(parseJson(stdin.readAll()))
  let started = getMonoTime()
  let completedTicks = world.step(ticks)
  let elapsedNs = (getMonoTime() - started).inNanoseconds
  if arguments[0] == "bench":
    stdout.write($(%*{
      "ticks": completedTicks, "elapsedNs": elapsedNs, "snapshot": world.snapshot(),
    }))
  else:
    stdout.write($world.snapshot())
  stdout.write("\n")
